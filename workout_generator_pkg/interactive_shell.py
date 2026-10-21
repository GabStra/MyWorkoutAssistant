"""Interactive CLI shell handlers."""

from __future__ import annotations

import argparse
import atexit
import copy
import json
import os
import sys
import uuid
import time
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from .constants import EXACT_GENERATION_CONFIRMATION
from .llm_config import require_api_key, resolve_llm_endpoint
from .planning_tools import (
    SET_WORKOUT_REQUIREMENTS_TOOL, AUDIT_WORKOUT_PLAN_TOOL, REPAIR_WORKOUT_PLAN_TOOL,
    workout_requirements_tool, construction_workout_tool,
    set_workout_requirements, audit_workout_plan, confirmed_draft,
    planning_tool_failure, requirements_approved, require_approved_requirements, PlanningInputError,
    _latest_result, requirement_sources,
    latest_draft_submission,
    GET_WORKOUT_DRAFT_TOOL, get_workout_draft,
    PREPARE_WORKOUT_SESSION_TOOL, prepare_workout_session,
    validate_repair_scope,
)
from .session_drafting import PREPARE_WORKOUT_SESSIONS_TOOL, PREPARATION_PATCH_TOOL, preparation_patch_tool, prepare_workout_sessions, draft_workout_sessions, revalidate_saved_preparation
from .conversation_store import normalize_conversation_messages
from .logging_ui import LoadingIndicator, print_markdown, print_question, format_question
from .usage_reporting import report_usage
from .user_interaction import ASK_USER_TOOL, clarification_question, pending_question, answer_question, PROPOSE_WORKOUT_ALTERNATIVES_TOOL, ACCEPT_WORKOUT_ALTERNATIVE_TOOL, repair_workout_alternative_tool
from .image_attachments import save_image, image_message
from .training_history import TrainingHistory, GET_TRAINING_EVIDENCE_TOOL, HISTORY_PLANNING_INSTRUCTION, LOAD_PROGRESSION_INSTRUCTION
from .plan_review import review_draft, review_followup_instructions, review_requirements, record_planning_decisions, pending_review_checkpoint
from .planning_decisions import RECORD_PLANNING_DECISIONS_TOOL, render_decisions
from .generation_audit import audit_policy, available_muscle_targets
from .planner_context import focus_planner_context, focus_alternative_repair_request, request_planning_state, pending_reaudit, planner_response_profile, pending_evidence, discovery_tool_failure, construction_tool_failure, current_unresolved_joint_candidate, _sanitize_stale_history_receipts
from .lookup_batch import execute_lookup_batch, LOOKUP_TOOLS
from .deps import resolve_shell_deps
from .allocation import ALLOCATE_WORKOUT_SETS_TOOL, allocate_workout_sets, auto_allocate_workout
from .planning_tools import planning_failure_signature, metadata_patch_tool, is_metadata_error
from .api_metrics import api_metrics_scope, start_planning_budget
from .exercise_library_tools import (
    SEARCH_EXERCISE_LIBRARY_TOOL, exercise_library_search_tool, execute_library_tool, execute_library_searches,
    GET_EXERCISE_CANDIDATES_TOOL, get_exercise_candidates,
)

CANONICAL_PLANNING_INSTRUCTION = (
    "You are a workout assistant using a strict exercise library, the sole allowed movement source. "
    "Preserve supplied movement identities, equipment data and muscle roles; choose another library entry rather than reclassifying one. "
    "Follow the current backend work order and supplied constructionTask, repairTask and discoveryPaused instructions. Tool schemas define the permitted arguments. "
    "Record source-backed requirements before planning. Preserve quantities, units, scope, exceptions and qualifiers; never relax them to pass validation. "
    "Before recording requirements, cross-check every explicit source category and qualifier together: targets, movement/muscle coverage and scope, restrictions/exceptions, order, rest, effort, warm-up and recovery. Do not defer independent omissions to later submissions. "
    "Use resolvedDecisions and existing delegation. Ask only about material ambiguity or a concrete new conflict, using ask_user and waiting for an answer. "
    "Record requirement interpretations with planningDecisions in set_workout_requirements, or record_planning_decisions when they must be resolved first. "
    "Ordinary exercise choices and prescriptions within approved requirements go directly through the draft audit. "
    "Reuse current candidates, completed searches and retrieved evidence. Batch independent lookups and search only for missing information needed by the current task. "
    "When two or more sessions remain, use prepare_workout_sessions for the complete remaining week. Python allocates counts and reviews the design before independent session prescriptions. "
    "Apply auditPolicy and programmingGuidelines; Python owns arithmetic, selectable loads and validation. Use the audit and allocation tools instead of solving totals in reasoning. "
    "Submit the weekly structure promptly; do not draft detailed sessions before its allocation and design checks. A single remaining session uses the normal bounded audit path. "
    "For every saved-draft repair or user-requested edit, use the typed stable WORKOUT_n and EXERCISE_n edit contract; never calculate or invent array indexes. "
    "Metadata-only repairs use their explicitly scoped metadata edit schema. JSON Patch is for initial construction and internal revalidation only. "
    "Mobility and ramp-up instructions belong in notes and warm-up flags, not invented movements. "
    "Treat unresolved findings as open until rechecked. Never fabricate evidence, alter library data or resubmit unchanged failures to obtain a different verdict. "
    "Questions do not mutate the draft; audit actual edits before claiming they were applied. "
    "Python displays reviewed requirements, passing previews and separate approval questions. Do not reproduce previews, request approval through ask_user, or invent consent. "
    "Export requires fresh confirmation and uses the exact approved draft. "
    "The command /continue resumes saved work and pending feedback without changing requirements or restarting discovery. "
    "Report execution failures; do not hide them with draft changes or repeat failed expensive requests without an explicit retry. "
    + LOAD_PROGRESSION_INSTRUCTION
)


def _resolve_api_key() -> str:
    """Resolve API key for the configured LLM endpoint, loading .env when present."""
    return require_api_key(resolve_llm_endpoint())


def _timestamp_now() -> str:
    return datetime.now().astimezone().isoformat()


def _message(role: str, **fields: Any) -> Dict[str, Any]:
    payload = {"role": role, "timestamp": _timestamp_now()}
    payload.update(fields)
    return payload


def _merge_completed_tool_checkpoint(failure: Dict[str, Any], checkpoint: Dict[str, Any]) -> Dict[str, Any]:
    """Retain completed stage evidence while keeping the terminal failure authoritative."""
    terminal_fields = {'passed', 'errors', 'instruction', 'preview', 'planIndex', 'cached', 'planningOutcome'}
    for key, value in checkpoint.items():
        if key not in terminal_fields:
            failure[key] = copy.deepcopy(value)
    failure.update(passed=False, checkpointPreserved=True)
    failure.pop('preview', None)
    failure.pop('planIndex', None)
    return failure


def _bind_current_draft_id(tool: Dict[str, Any], current_draft_id: Optional[str]) -> Dict[str, Any]:
    """Advertise the exact current base ID on every available draft-bound tool."""
    bound = copy.deepcopy(tool)
    function = bound.get('function', {})
    parameters = function.get('parameters', {})
    changed = False

    def visit(schema):
        nonlocal changed
        if not isinstance(schema, dict):
            return
        for name, property_schema in schema.get('properties', {}).items():
            if name == 'baseDraftId' and isinstance(property_schema, dict):
                field_types = property_schema.get('type', [])
                if isinstance(field_types, str):
                    field_types = [field_types]
                if current_draft_id is not None or 'null' in field_types:
                    property_schema['enum'] = [current_draft_id]
                    state = f'Current value is exactly {current_draft_id}.' if current_draft_id is not None else 'There is no current draft; use null exactly.'
                    property_schema['description'] = (property_schema.get('description', '') + ' ' + state).strip()
                    changed = True
            visit(property_schema)
        if isinstance(schema.get('items'), dict):
            visit(schema['items'])
        for key in ('oneOf', 'anyOf', 'allOf'):
            for item in schema.get(key, []):
                visit(item)

    visit(parameters)
    if changed:
        label = current_draft_id if current_draft_id is not None else 'null (no current draft)'
        function['description'] = (function.get('description', '') + f' For this request, baseDraftId must be exactly {label}.').strip()
    return bound


def _candidate_menu_expansion_attempt(task):
    if not isinstance(task, dict) or not task.get('sourceProblemFingerprint'):
        return None
    return {
        'version': 1,
        'attempted': True,
        'auditedCandidate': False,
        'sourceBaseDraftId': task.get('sourceBaseDraftId'),
        'sourceProblemFingerprint': task.get('sourceProblemFingerprint'),
        'sourceMenuFingerprint': task.get('sourceMenuFingerprint'),
        'requirementsId': task.get('requirementsId'),
        'libraryFingerprint': task.get('libraryFingerprint'),
        'historyFingerprint': task.get('historyFingerprint'),
        'resolvedDecisions': copy.deepcopy(task.get('resolvedDecisions', {})),
        'blockers': copy.deepcopy(task.get('blockers', [])),
    }


def _candidate_menu_expansion_audit_marker(task, payload, arguments=None):
    if not isinstance(task, dict) or not task.get('sourceProblemFingerprint'):
        return None
    if isinstance(arguments, dict) and not (
            arguments.get('workouts')
            or arguments.get('patch')
            or arguments.get('edits')):
        return None
    submitted = payload.get('submittedDraft') if isinstance(payload, dict) else None
    joint_receipt = (payload.get('coordinatedJointPlanning') or payload.get('automaticAllocation') or {}) if isinstance(payload, dict) else {}
    materialized = (payload.get('currentDraftId') is not None
        and payload.get('currentDraftId') != task.get('sourceBaseDraftId')) if isinstance(payload, dict) else False
    if not (materialized and isinstance(submitted, dict) and isinstance(submitted.get('workouts'), list) and joint_receipt):
        return None
    from .joint_planning import candidate_menu_fingerprint
    return {
        **_candidate_menu_expansion_attempt(task),
        'auditedCandidate': True,
        'resultMenuFingerprint': candidate_menu_fingerprint(submitted['workouts']),
        'resultingProblemFingerprint': joint_receipt.get('problemFingerprint'),
    }


def _candidate_menu_expansion_tools(request_tools, task):
    if not task:
        return request_tools
    if task.get('proofScope') == 'exercise_selection_repair':
        if task.get('stage') == 'discover_candidates':
            allowed = {'search_exercise_library'}
        else:
            allowed = {'audit_workout_plan', 'propose_workout_alternatives'}
            if task.get('missingDraftReferences'):
                allowed.add('get_workout_draft')
        return [tool for tool in request_tools if tool.get('function', {}).get('name') in allowed]
    blocked = {'ask_user', 'propose_workout_alternatives', 'accept_workout_alternative'}
    return [tool for tool in request_tools if tool.get('function', {}).get('name') not in blocked]


def _repair_attempt_counts(messages, attempt_start_index, equipment=None):
    """Count repair tool submissions separately from marked code-owned audit actions."""
    start = max(0, min(int(attempt_start_index or 0), len(messages)))
    calls = {call['id']: (index, call['function'].get('name'), call['function']) for index, message in enumerate(messages)
             for call in message.get('tool_calls', [])
             if call.get('function', {}).get('name') in ('audit_workout_plan', 'repair_workout_alternative')}
    internal_actions = {call_id: action for message in messages
                        for call_id, action in (message.get('_internalAuditActions') or {}).items()}
    prior_draft = None
    counts = {'changed': 0, 'rejected': 0, 'internal': 0}
    seen_tool_call_ids = set()
    alternative_candidates = {}

    def alternative_candidate_state(payload):
        if not isinstance(payload, dict):
            return None
        snapshot = payload.get('candidateSnapshot')
        if not isinstance(snapshot, dict):
            return None
        state = {}
        for field in ('workouts', 'currentDraft'):
            if field in snapshot:
                state[field] = snapshot[field]
        return state or None

    # Seed the comparison with the latest saved snapshot before this repair window.
    for message in messages[:start]:
        tool_call_id = message.get('tool_call_id')
        call = calls.get(tool_call_id)
        if message.get('role') != 'tool' or not call or call[1] != 'repair_workout_alternative':
            continue
        try:
            prior_payload = json.loads(message.get('content') or '{}')
        except (TypeError, ValueError):
            continue
        prior_snapshot = prior_payload.get('candidateSnapshot') if isinstance(prior_payload, dict) else None
        prior_id = prior_snapshot.get('repairCandidateId') if isinstance(prior_snapshot, dict) else None
        prior_state = alternative_candidate_state(prior_payload)
        if isinstance(prior_id, str) and prior_state is not None:
            alternative_candidates[prior_id] = prior_state

    for index, message in enumerate(messages):
        tool_call_id = message.get('tool_call_id')
        if (message.get('role') != 'tool' or tool_call_id not in calls
                or tool_call_id in seen_tool_call_ids):
            continue
        seen_tool_call_ids.add(tool_call_id)
        call_index, function_name, function = calls[tool_call_id]
        try:
            payload = json.loads(message.get('content') or '{}')
        except (TypeError, ValueError):
            if call_index >= start and function_name == 'repair_workout_alternative':
                counts['rejected'] += 1
            continue
        if function_name == 'repair_workout_alternative':
            if call_index < start:
                continue
            try:
                arguments = json.loads(function.get('arguments') or '{}')
            except (TypeError, ValueError):
                arguments = {}
            candidate_id_changed = (isinstance(payload, dict)
                and isinstance(arguments, dict)
                and isinstance(payload.get('repairCandidateId'), str)
                and isinstance(arguments.get('repairCandidateId'), str)
                and payload['repairCandidateId'] != arguments['repairCandidateId'])
            candidate_snapshot = payload.get('candidateSnapshot') if isinstance(payload, dict) else None
            candidate_snapshot_id = (candidate_snapshot.get('repairCandidateId')
                if isinstance(candidate_snapshot, dict) else None)
            candidate_state = alternative_candidate_state(payload)
            previous_state = alternative_candidates.get(arguments.get('repairCandidateId'))
            serialized_candidate_changed = (candidate_state is not None and previous_state is not None
                and candidate_state != previous_state)
            if candidate_id_changed or serialized_candidate_changed:
                counts['changed'] += 1
            else:
                counts['rejected'] += 1
            if isinstance(candidate_snapshot_id, str) and candidate_state is not None:
                alternative_candidates[candidate_snapshot_id] = candidate_state
            continue
        internal_action = internal_actions.get(tool_call_id)
        candidate = payload.get('submittedDraft') if isinstance(payload, dict) else None
        if call_index >= start:
            if internal_action:
                counts['internal'] += 1
                if isinstance(candidate, dict) and isinstance(candidate.get('workouts'), list):
                    prior_draft = copy.deepcopy(candidate)
                continue
            changed = (isinstance(candidate, dict) and isinstance(candidate.get('workouts'), list)
                       and prior_draft is not None and candidate != prior_draft)
            rejected_without_change = (isinstance(payload, dict) and payload.get('passed') is False
                and bool(payload.get('errors')) and not payload.get('executionFailure') and not changed
                )
            if changed:
                counts['changed'] += 1
            elif rejected_without_change:
                counts['rejected'] += 1
        if isinstance(candidate, dict) and isinstance(candidate.get('workouts'), list):
            prior_draft = copy.deepcopy(candidate)
    return counts


def _model_repair_submissions_used(counts):
    return counts.get('changed', 0) + counts.get('rejected', 0)


def _repair_budget_pause(planning_state, messages, attempt_start_index, maximum, equipment=None):
    """Stop before another model proposal once the current repair window is spent."""
    if not (planning_state.get('repairTask') or planning_state.get('alternativeRepairTask')):
        return None
    counts = _repair_attempt_counts(messages, attempt_start_index, equipment)
    used = _model_repair_submissions_used(counts)
    if used < maximum:
        return None
    return (f'This repair attempt used {used} of {maximum} model repair submissions: '
        f'{counts["changed"]} changed the candidate and {counts["rejected"]} were rejected without changing it. '
        f'Code-owned automatic audit actions: {counts["internal"]}. '
        'The current candidate and findings are preserved. Type /continue for a new bounded repair attempt.')


def _repair_requires_coordinated_qualification(edits, current_draft):
    if edits.get('exerciseAdditions'):
        return True
    current_ids = [exercise.get('definition_id') for day in current_draft.get('workouts', [])
                   for exercise in day.get('exercises', [])]
    for update in edits.get('exerciseUpdates', []):
        if (set(update.get('setFields', {})) | set(update.get('removeOptionalFields', []))) & {
                'progressionPlan', 'satisfiesCoverage'}:
            return True
        if 'definition_id' not in update.get('setFields', {}):
            continue
        reference = update.get('exerciseRef', '')
        if reference.startswith('EXERCISE_') and reference[9:].isdigit():
            index = int(reference[9:])
            if index >= len(current_ids) or update['setFields']['definition_id'] != current_ids[index]:
                return True
    return False


def _repair_cap_pause(failures):
    error = next((item for item in failures if isinstance(item, dict)
        and item.get('code') == 'repair_round_cap_reached'), None)
    return ((error.get('repair') or error.get('message') or
             'The candidate-changing repair limit was reached; the current draft and findings remain saved.')
            if error else None)


def _repair_capability_pause(planning_state):
    if planning_state.get('alternativeRepairTask'):
        return None
    alternative = planning_state.get('alternativeRepairCapabilityUnresolved')
    draft = planning_state.get('repairCapabilityUnresolved')
    if alternative:
        subject, identity = 'Alternative', alternative.get('repairCandidateId', 'candidate')
        evidence = alternative
    elif draft:
        subject, identity = 'Draft', draft.get('currentDraftId', 'candidate')
        evidence = draft
    else:
        joint = planning_state.get('alternativeJointRepairUnresolved')
        if not joint:
            return None
        return (joint.get('reason', 'The bounded joint repair solve did not establish feasibility or infeasibility.')
            + ' The candidate and solver receipt are saved; no automatic retry was made. Type /continue for one bounded retry with a changed proposal.')
    if evidence.get('assessmentUnavailable'):
        return (f'{subject} {identity} has an unresolved review capability result, but its current assessment could not be bound to the saved candidate. '
            'The finding and review error are saved; no repair or impossibility conclusion was made.')
    indexes = ', '.join(str(index) for index in evidence.get('findingIndexes', [])) or 'unknown'
    return (f'{subject} {identity} has review findings {indexes} that the supported repair contract cannot express. '
        'The candidate and review evidence are saved; no repair was attempted, and no impossibility was established.')


def _unchanged_repair_failure_pause(repair_task, feedback, messages, attempt_start_index=0):
    alternative_id = (repair_task or {}).get('repairCandidateId')
    if alternative_id:
        start = max(0, min(int(attempt_start_index or 0), len(messages)))
        feedback_status = feedback.get('attemptStatus')
        if (feedback.get('passed') is not False or feedback.get('repairCandidateId') != alternative_id
                or feedback_status not in ('repair_failed', 'repair_menu_infeasible') or not feedback.get('errors')):
            return None
        calls = {call.get('id'): call for message in messages[start:] if message.get('role') == 'assistant'
            for call in message.get('tool_calls', [])
            if call.get('function', {}).get('name') == 'repair_workout_alternative'}
        failures = 0
        seen_tool_call_ids = set()
        for message in messages[start:]:
            tool_call_id = message.get('tool_call_id')
            if message.get('role') != 'tool' or tool_call_id not in calls or tool_call_id in seen_tool_call_ids:
                continue
            seen_tool_call_ids.add(tool_call_id)
            try:
                arguments = json.loads(calls[tool_call_id].get('function', {}).get('arguments', '{}'))
                result = json.loads(message.get('content', '{}'))
            except (TypeError, ValueError):
                continue
            if (arguments.get('repairCandidateId') == alternative_id
                    and result.get('repairCandidateId') == alternative_id
                    and result.get('passed') is False and result.get('errors')):
                if feedback_status == 'repair_menu_infeasible':
                    current_solve = feedback.get('jointSolve') or {}
                    result_solve = result.get('jointSolve') or {}
                    problem_fingerprint = current_solve.get('problemFingerprint')
                    if (result.get('attemptStatus') == 'repair_menu_infeasible'
                            and problem_fingerprint and result_solve.get('problemFingerprint') == problem_fingerprint):
                        failures += 1
                elif result.get('attemptStatus') == 'repair_failed':
                    failures += 1
        if failures < 3:
            return None
        if feedback_status == 'repair_menu_infeasible':
            return (f'The same alternative exercise menu was proven infeasible three times for {alternative_id}; '
                    'the candidate and solver evidence are saved for a changed-menu retry.')
        return (f'Three alternative repair submissions failed before changing {alternative_id}; '
                'the candidate and findings are saved for a targeted retry.')

    receipt = feedback.get('coordinatedRepairReceipt') or {}
    base_id = (repair_task or {}).get('baseDraftId') or receipt.get('baseDraftId')
    current_id = feedback.get('currentDraftId') or receipt.get('currentDraftId')
    if not base_id or current_id != base_id or not (feedback.get('errors') or []):
        return None
    start = max(0, min(int(attempt_start_index or 0), len(messages)))
    repair_calls = {call.get('id'): call for message in messages[start:] if message.get('role') == 'assistant'
        for call in message.get('tool_calls', [])
        if call.get('function', {}).get('name') == 'audit_workout_plan'}
    failures = 0
    for message in messages[start:]:
        if message.get('role') != 'tool' or message.get('tool_call_id') not in repair_calls:
            continue
        call = repair_calls[message['tool_call_id']]
        try:
            arguments = json.loads(call.get('function', {}).get('arguments', '{}'))
            result = json.loads(message.get('content', '{}'))
        except (TypeError, ValueError):
            continue
        submitted = bool(arguments.get('workouts') or arguments.get('edits') or arguments.get('patch'))
        if (submitted and arguments.get('baseDraftId') == base_id and result.get('passed') is False
                and result.get('currentDraftId') == base_id and result.get('errors')):
            failures += 1
    if failures < 3:
        return None
    return (f'Three coordinated repair submissions failed without changing {base_id}; '
            'the candidate and findings are saved for a targeted retry.')


def _admit_repair_scope(function_args, repair_task, current_draft, messages, attempt_start_index,
                        max_repair_rounds, equipment=None, scope_validator=None, return_context=False,
                        submission_context=None):
    counts = _repair_attempt_counts(messages, attempt_start_index, equipment)
    attempts = counts['changed'] + counts['rejected']
    if attempts >= max_repair_rounds:
        raise PlanningInputError('repair_round_cap_reached', 'The repair attempt reached its submission limit.', '/edits',
            f'This attempt has used {attempts} of {max_repair_rounds} repair submissions: {counts["changed"]} changed the candidate and {counts["rejected"]} were rejected without changing it. Preserve the candidate and findings; report unresolved issues or propose a validated trade-off instead of repeating review.')
    validator = scope_validator or validate_repair_scope
    if function_args.get('patch') == []:
        raise PlanningInputError('empty_repair_noop', 'An empty edit cannot repair the saved draft.', '/edits',
            'Submit a concrete typed stable-reference edit for the current candidate. Internal revalidation is handled separately.')
    if 'edits' not in function_args:
        raise PlanningInputError('repair_edit_contract_required', 'A saved-draft edit requires typed stable references.', '/edits',
            'Submit the intended changes through WORKOUT_n and EXERCISE_n edits. Raw patches are reserved for internal revalidation.')
    from .planning_tools import compile_coordinated_repair
    compiler_draft = current_draft
    if repair_task.get('rejectedSubmission'):
        from .json_patching import apply_json_patch
        compiler_draft = apply_json_patch(current_draft, repair_task['rejectedSubmission']['patch'])
    compiled, operation_refs, reference_map = compile_coordinated_repair(
        function_args, repair_task, compiler_draft, return_reference_map=True,
        proposal_context=submission_context)
    scoped_task = copy.deepcopy(repair_task)
    scoped_task['_compiledRepairOperationRefs'] = operation_refs
    admitted = validator(compiled, scoped_task, compiler_draft)
    if return_context:
        return admitted, {
            'operationRefs': operation_refs,
            'exerciseRefsByWorkout': reference_map.get('exerciseRefsByWorkout', {}),
            'initialExerciseRefsByWorkout': reference_map.get('initialExerciseRefsByWorkout', {}),
            'workoutRefsByPosition': reference_map.get('workoutRefsByPosition', []),
            'initialDefinitionByExerciseRef': reference_map.get('initialDefinitionByExerciseRef', {}),
            'typedEdits': copy.deepcopy(reference_map.get('composedEdits', function_args.get('edits', {}))),
            'baseDraft': copy.deepcopy(compiler_draft),
        }
    return admitted


def _coordinated_repair_receipt_context(repair_task, baseline_audit):
    repair_task = repair_task or {}
    assessment = repair_task.get('findingsAssessment') or {}
    input_hash = assessment.get('inputHash')
    baseline_audit = baseline_audit or {}
    prior_receipt = baseline_audit.get('coordinatedRepairReceipt')
    findings = repair_task.get('reviewFindings')
    expected_assessment_hash = None
    if input_hash and isinstance(findings, list):
        from .review_assessment import assessment_hash
        expected_assessment_hash = assessment_hash({'inputHash': input_hash, 'findings': findings})
    prior_matches = (isinstance(prior_receipt, dict)
        and prior_receipt.get('status') == 'rejected_before_materialization'
        and prior_receipt.get('requirementsId') == repair_task.get('requirementsId')
        and prior_receipt.get('baseDraftId') == repair_task.get('baseDraftId')
        and prior_receipt.get('currentDraftId') == repair_task.get('baseDraftId')
        and prior_receipt.get('reviewedDraftId') == repair_task.get('baseDraftId')
        and prior_receipt.get('assessmentInputHash') == input_hash
        and (not expected_assessment_hash
             or prior_receipt.get('assessmentHash') == expected_assessment_hash))

    def source_value(key, *fallback_keys):
        value = baseline_audit.get(key)
        if value is not None:
            return value
        review = baseline_audit.get('review')
        if isinstance(review, dict):
            review_key = {'reviewVersion': 'version', 'reviewInputHash': 'inputHash'}.get(key)
            if review_key and review.get(review_key) is not None:
                return review[review_key]
        if prior_matches:
            for fallback_key in (key, *fallback_keys):
                value = prior_receipt.get(fallback_key)
                if value is not None:
                    return value
        return None

    identity = {
        'assessmentInputHash': input_hash,
        'assessmentHash': expected_assessment_hash,
        'reviewVersion': source_value('reviewVersion'),
        'auditVersion': source_value('auditVersion'),
        'reviewInputHash': source_value('reviewInputHash'),
        'reviewedDraftId': source_value('assessmentDraftId', 'reviewedDraftId')
            or source_value('currentDraftId'),
        'libraryFingerprint': source_value('libraryFingerprint'),
        'historyFingerprint': source_value('historyFingerprint'),
        'resolvedDecisions': copy.deepcopy(source_value('resolvedDecisions') or {}),
    }
    return identity


def _format_timestamp(value: Optional[str]) -> str:
    if not value:
        return "unknown time"
    try:
        return datetime.fromisoformat(value).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return value


def _format_json(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, indent=2, ensure_ascii=False)


def _build_initial_messages(
    base_system_prompt: str,
    provided_equipment: Optional[Dict[str, Any]],
    format_equipment_for_conversation,
    exercise_definitions: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    messages = [_message("system", content=base_system_prompt)]
    if provided_equipment:
        messages.append(
            _message(
                "system",
                content=format_equipment_for_conversation(provided_equipment),
            )
        )
    if exercise_definitions:
        messages.append(_message(
            "system",
            content=(
                f"A strict exercise library with {len(exercise_definitions)} definitions is loaded. "
                "It is the sole allowed movement source. Its metadata is available through the planning tools."
            ),
        ))
    return messages


def _load_exercise_library_payload(filepath: str) -> Dict[str, Any]:
    with open(filepath, "r", encoding="utf-8") as source:
        root = json.load(source)
    payload = root
    if isinstance(root, dict) and isinstance(root.get("WorkoutStore"), dict):
        payload = root["WorkoutStore"]
    definitions = payload.get("exerciseDefinitions") if isinstance(payload, dict) else None
    if not isinstance(definitions, list):
        raise ValueError("expected a schema-v2 store or object containing exerciseDefinitions")
    if any(not isinstance(item, dict) or not item.get("id") for item in definitions):
        raise ValueError("every exercise definition must be an object with an id")
    movements = []
    if isinstance(root, dict):
        movements = root.get("exerciseMovements") or root.get("ExerciseMovements") or []
    return {
        "exerciseDefinitions": definitions,
        "equipments": payload.get("equipments", []) if isinstance(payload, dict) else [],
        "accessoryEquipments": payload.get("accessoryEquipments", []) if isinstance(payload, dict) else [],
        "exerciseMovements": movements,
    }


def _load_exercise_definitions(filepath: str) -> List[Dict[str, Any]]:
    return _load_exercise_library_payload(filepath)["exerciseDefinitions"]


def _merge_library_items(existing: List[Dict[str, Any]], imported: List[Dict[str, Any]], label: str):
    merged = {item.get("id"): item for item in existing if isinstance(item, dict)}
    for item in imported:
        item_id = item.get("id") if isinstance(item, dict) else None
        if not item_id:
            raise ValueError(f"every {label} item must have an id")
        if item_id in merged and merged[item_id] != item:
            raise ValueError(f"conflicting {label} content for id {item_id}")
        merged[item_id] = item
    return list(merged.values())


def _conversation_log_path(script_dir: str, conversation_id: str) -> str:
    short_cid = conversation_id[:8] if len(conversation_id) >= 8 else conversation_id
    return os.path.join(script_dir, "logs", f"conversation_{short_cid}.log")


def _create_logger(ConversationLogger, script_dir: str, conversation_id: str):
    log_path = _conversation_log_path(script_dir, conversation_id)
    log_dir = os.path.dirname(log_path)
    os.makedirs(log_dir, exist_ok=True)
    recover_transcript = os.path.isfile(log_path) and os.path.getsize(log_path) == 0
    logger = ConversationLogger(log_path)
    logger.log(f"Conversation logging started: {conversation_id}")
    if recover_transcript:
        from .conversation_store import load_conversation_record
        record = load_conversation_record(conversation_id, script_dir) or {}
        logger.log('Recovering empty log from saved conversation; original timestamps are included below.')
        for message in record.get('messages', []):
            if message.get('role') != 'system':
                logger.log(json.dumps(message, ensure_ascii=False))
    return logger, log_path


def _metadata_for_generation_result(
    generation_result: Dict[str, Any],
    log_path: Optional[str],
    previous_paths: Optional[List[str]] = None,
) -> Dict[str, Any]:
    filepath = generation_result.get("filepath")
    guidance_filepath = generation_result.get("guidance_filepath")
    generated_paths = list(previous_paths or [])
    for output_path in (filepath, guidance_filepath):
        if output_path and output_path not in generated_paths:
            generated_paths.append(output_path)
    return {
        "last_generation_result": {
            "success": bool(generation_result.get("success")),
            "filepath": filepath,
            "guidance_filepath": guidance_filepath,
            "error": generation_result.get("error"),
            "recorded_at": _timestamp_now(),
        },
        "generated_output_paths": generated_paths,
        "log_filename": os.path.basename(log_path) if log_path else None,
    }


def _render_turns(messages: List[Dict[str, Any]], logger) -> None:
    logger.log_print("")
    logger.log_print("=" * 70)
    logger.log_print("Conversation Turns")
    logger.log_print("=" * 70)

    visible_roles = {"system", "user", "assistant"}
    visible_messages = [
        message for message in messages
        if message.get("role") in visible_roles
        and (
            message.get("role") != "assistant"
            or message.get("content") not in (None, "")
            or message.get("tool_calls")
        )
    ]

    for index, message in enumerate(visible_messages, start=1):
        role = message.get("role", "unknown")
        timestamp = _format_timestamp(message.get("timestamp"))
        logger.log_print(f"[{index}] {role} | {timestamp}")

        content = message.get("content")
        if content is not None:
            if role == "assistant" and isinstance(content, str):
                if message.get('unvalidatedProposal'):
                    logger.log_print('[Unvalidated draft discussion; use the passing preview for actual prescriptions.]')
                print_markdown(content, logger)
            else:
                logger.log_print(_format_json(content))
        if role == "assistant" and message.get("tool_calls"):
            logger.log_print("[Tool call triggered]")
        for attachment in message.get('imageAttachments', []):
            logger.log_print(f'[Attached image: {attachment["name"]}]')

        logger.log_print("-" * 70)


def _ensure_tool_responses(messages: List[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], bool]:
    repaired = normalize_conversation_messages(messages)
    return repaired, repaired != messages


def _messages_for_api(messages: List[Dict[str, Any]], planning_enabled=False, training_history=None, provided_equipment=None) -> List[Dict[str, Any]]:
    repaired, _ = _ensure_tool_responses(messages)
    result = [{key: value for key, value in message.items() if key not in ("canonicalDraftPreview", "canonicalRequirementsPreview", "unvalidatedProposal", "userInteraction", "candidateMenuExpansionAttempt", "_internalAuditActions")}
              for message in repaired if message.get("role") != "emitter"]
    tool_names = {call["id"]: call["function"]["name"] for message in result
                  for call in message.get("tool_calls", [])}
    seen_entries = set()
    for message in result:
        name = tool_names.get(message.get("tool_call_id"))
        if training_history and name == "get_training_evidence":
            try:
                evidence = json.loads(message.get('content', ''))
                if evidence.get('historyFingerprint') != training_history.fingerprint:
                    message['content'] = json.dumps({'staleHistory': True, 'instruction': 'Retrieve current training evidence again.'})
                elif provided_equipment and hasattr(training_history,'refresh_evidence_metadata'):
                    message['content'] = json.dumps(training_history.refresh_evidence_metadata(evidence,provided_equipment),separators=(',',':'))
            except (TypeError, ValueError, AttributeError):
                pass
        if name not in ("audit_workout_plan", "search_exercise_library", "propose_workout_alternatives"):
            continue
        try:
            payload = json.loads(message.get("content", ""))
        except (ValueError, TypeError):
            continue
        if not isinstance(payload, dict):
            continue
        if name == "audit_workout_plan" and "audit" in payload:
            audit = payload["audit"]
            compact = {key: payload[key] for key in ("passed", "requirementsId", "draftId", "currentDraftId", "auditVersion", "instruction", "libraryFingerprint", "historyFingerprint", "allowEducatedLoadGuesses", "resolvedDecisions", "planningOutcome", "automaticAllocation", "coordinatedJointPlanning", "jointPlanningStopped", "coordinatedRepairReceipt", "reviewFindings", "reviewChecklist", "candidateMenuExpansion") if key in payload}
            submitted_draft = payload.get('submittedDraft')
            if isinstance(submitted_draft, dict) and isinstance(submitted_draft.get('workouts'), list):
                from .joint_planning import candidate_menu_fingerprint
                compact['candidateMenuFingerprint'] = candidate_menu_fingerprint(submitted_draft['workouts'])
            compact["errors"] = payload.get("errors", [])
            compact['reviewVersion'] = payload.get('review', {}).get('version', payload.get('reviewVersion'))
            compact['reviewInputHash'] = payload.get('review', {}).get('inputHash', payload.get('reviewInputHash'))
            compact['reviewWarnings'] = [f for f in payload.get('review', {}).get('findings', []) if f.get('severity') == 'warning']
            compact['reviewFindings'] = payload.get('review', {}).get('findings', payload.get('reviewFindings', []))
            assessment = payload.get('review', {}).get('assessment') or payload.get('findingsAssessment')
            compact['findingsAssessment'] = assessment
            compact['assessmentDraftId'] = (payload.get('assessmentDraftId') or
                (payload.get('currentDraftId') if assessment else None))
            if isinstance(payload.get('review', {}).get('findings'), list):
                compact['reviewFindings'] = payload['review']['findings']
            if payload.get('review', {}).get('followupReview'):
                compact['followupReview'] = payload['review']['followupReview']
            for key in ('reviewPending', 'previousReviewFindings'):
                if key in payload:
                    compact[key] = payload[key]
            compact["audit"] = {key: audit[key] for key in ("targets", "assumptions", "weeklyVolume") if key in audit}
            compact["audit"]["workouts"] = [
                {key: workout[key] for key in ("name", "volume", "contributions", "timing", "estimatedSeconds") if key in workout}
                for workout in audit.get("workouts", [])]
            payload = compact
        elif name == "propose_workout_alternatives":
            from .plan_review import REVIEW_VERSION
            from .review_assessment import validate_assessment
            for field in ('alternativeRepairCandidates', 'proposals'):
                candidates = payload.get(field)
                if not isinstance(candidates, list):
                    continue
                for candidate in candidates:
                    review = candidate.get('review') if isinstance(candidate, dict) else None
                    if (not isinstance(review, dict) or review.get('version') != REVIEW_VERSION
                            or review.get('failure') or review.get('inProgress')):
                        continue
                    try:
                        assessment = validate_assessment(review)
                    except (KeyError, TypeError, ValueError):
                        continue
                    candidate['findingsAssessment'] = assessment
                    candidate['reviewFindings'] = review['findings']
        elif name == "search_exercise_library" and "results" in payload:
            payload = json.loads(json.dumps(payload))
            for query in payload["results"]:
                for index, exercise in enumerate(query.get("exercises", [])):
                    if training_history and payload.get('historyFingerprint') != training_history.fingerprint:
                        exercise.pop('trainingEvidence', None)
                    identity = (payload.get("libraryFingerprint"), exercise["id"])
                    if identity in seen_entries:
                        query["exercises"][index] = {"id": exercise["id"], "relevanceScore": exercise.get("relevanceScore")}
                    else:
                        seen_entries.add(identity)
        if name == 'audit_workout_plan':
            if isinstance(payload.get('submittedDraft'), dict):
                payload['materializedDraftId'] = payload.get('currentDraftId')
            payload.pop('submittedDraft', None)
        message["content"] = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    if planning_enabled:
        # Saved conversations may still contain superseded application prompts.
        result = [message for message in result if not (message.get('role') == 'system'
            and (message.get('content') or '').startswith(('You are a workout assistant.', 'A strict exercise library with ')))]
        result = focus_planner_context(result, repaired, provided_equipment,
            history_enabled=training_history is not None,
            history_fingerprint=getattr(training_history, 'fingerprint', None),
            history_identity_known=training_history is not None,
            training_history=training_history)
        if request_planning_state(result).get('metadataOnlyRepair'):
            return result
        result.append({"role": "system", "content": CANONICAL_PLANNING_INSTRUCTION})
        result.append({'role': 'system', 'content': 'Application auditPolicy (estimates and counting conventions, not user requirements): '
            + json.dumps(audit_policy(available_muscle_targets(provided_equipment))) + '. Muscle credits use the selected library roles. Omit unspecified muscle targets; 0-0 is a prohibition. '
            'Apply auditPolicy.capabilityLimits when extracting targets or proposing choices. '
            'Explicit timing instructions must be reflected in estimates; ask about a conflict the current estimator cannot represent.'})
        if not requirements_approved(messages):
            result.append({'role': 'system', 'content': 'Current stage: extract requirements only. Submit set_workout_requirements for independent review; Python displays the approval question. Planning starts after approval.'})
    if training_history:
        result.append({'role': 'system', 'content': HISTORY_PLANNING_INSTRUCTION + '\nCurrent history snapshot: ' + json.dumps(training_history.context())})
    if planning_enabled and any((m.get('content') or '').startswith('Current planning state') for m in result):
        # Keep invariant policy ahead of changing state so provider prefix caches can be reused.
        changing = [m for m in result if (m.get('content') or '').startswith('Current planning state')]
        fixed = [m for m in result if m.get('role') == 'system' and m not in changing]
        result = fixed + changing + [m for m in result if m.get('role') != 'system']
    images = image_message(requirement_sources(messages))
    if images:
        result = [{key: value for key, value in message.items() if key != 'imageAttachments'} for message in result]
        result.extend(images)
    return result


def _show_commands(logger) -> None:
    logger.log_print("Commands:")
    logger.log_print("  • Type normal messages to chat with the assistant")
    logger.log_print("  • Type /ml (or /multiline) to enter multi-line mode, finish with a line containing /end")
    logger.log_print("  • Type /generate or /generate <prompt> to generate workout JSON")
    logger.log_print("  • Type /resume to reopen a saved conversation and show all stored turns")
    logger.log_print("  • Type /resume-progress to resume an interrupted generation directly")
    logger.log_print("  • Type /list-progress to list all saved generation progress")
    logger.log_print("  • Type /list-conversations to list saved conversations")
    logger.log_print("  • Type /resume-conversation <conversation_id> to reopen a conversation and show all stored turns")
    logger.log_print("  • Type /show-turns [conversation_id] to print exact stored turns")
    logger.log_print("  • Type /view to view the latest workout preview in a Markdown pager")
    logger.log_print("  • Type /usage to show cumulative API tokens and estimated model cost for this conversation")
    logger.log_print('  • Type /image <path> (also inside /ml) to attach a JPEG/PNG/GIF/WebP; /image clear to discard queued images')
    logger.log_print("  • Type /continue to resume a paused draft using saved lookups and audit feedback")
    logger.log_print("  • Type /clear-progress <session_id> to delete a progress file")
    logger.log_print("  • Type /exit to quit")
    logger.log_print("  • Type /clear to start a fresh conversation")
    logger.log_print("  • Press Ctrl+C during generation to cancel")


def _print_welcome(logger) -> None:
    logger.log_print("=" * 70)
    logger.log_print("Workout Assistant & Generator")
    logger.log_print("=" * 70)
    logger.log_print("")
    logger.log_print("This script is an AI-powered workout assistant that helps you:")
    logger.log_print("  • Chat about workouts, exercises, and fitness goals")
    logger.log_print("  • Generate structured workout JSON files compatible with")
    logger.log_print("    the MyWorkoutAssistant app")
    logger.log_print("")
    logger.log_print("The assistant will ask you about:")
    logger.log_print("  • Your fitness goals and training preferences")
    logger.log_print("  • Available equipment (to suggest compatible exercises)")
    logger.log_print("")
    logger.log_print("The generated JSON includes:")
    logger.log_print("  • Complete workout definitions with exercises, sets, and rest periods")
    logger.log_print("  • Equipment configurations (barbells, dumbbells, machines, etc.)")
    logger.log_print("  • Exercise details (reps, weights, muscle groups, progression settings)")
    logger.log_print("  • Validated against a comprehensive JSON schema")
    logger.log_print("")
    _show_commands(logger)
    logger.log_print("")
    logger.log_print("=" * 70)
    logger.log_print("")


def handle_function_call(
    client,
    messages,
    function_name,
    function_args,
    provided_equipment=None,
    logger=None,
    script_dir=None,
    deps=None,
    force_use_reasoner=None,
    allow_educated_load_guesses=True,
    training_history=None,
    progress=None,
    checkpoint=None,
    coordinated_repair=False,
    alternative_repair_task=None,
):
    deps = deps or resolve_shell_deps()
    execute_workout_generation = deps.execute_workout_generation
    """
    Handle function call execution.

    Returns:
        dict: Result with keys:
            - result: The function result (formatted for assistant)
            - should_exit: bool indicating if conversation should end
            - generation_result: Optional raw generation result
    """

    def _last_user_message_content():
        for message in reversed(messages):
            if message.get("role") == "user":
                return '' if message.get('imageAttachments') else (message.get("content") or "").strip()
        return ""

    if function_name == 'ask_user':
        question = clarification_question(function_args)
        return {'result': json.dumps({'userQuestion': question}), 'waiting_for_user': True,
                'should_exit': False, 'generation_result': None}

    if function_name == "generate_workout":
        last_user_index = next((i for i in range(len(messages) - 1, -1, -1) if messages[i].get("role") == "user"), -1)
        for message in messages[last_user_index + 1:]:
            if message.get("role") == "tool":
                try:
                    feedback = json.loads(message.get("content") or "{}")
                except (TypeError, ValueError):
                    continue
                if isinstance(feedback, dict) and feedback.get("requires_plan_revision"):
                    return {"result": "Generation blocked: show the revised preview and wait for a fresh CONFIRM GENERATE.",
                            "should_exit": False, "generation_result": None}
        last_user_message = _last_user_message_content()
        if last_user_message != EXACT_GENERATION_CONFIRMATION:
            return {
                "result": (
                    "Workout generation blocked. "
                    f"Wait for the user to reply with exactly {EXACT_GENERATION_CONFIRMATION!r} "
                    "before calling generate_workout."
                ),
                "should_exit": False,
                "generation_result": None,
            }
        library = (provided_equipment or {}).get("exerciseDefinitions")
        if library:
            try:
                snapshot = confirmed_draft(messages, provided_equipment, allow_educated_load_guesses, require_confirmation=True)
                review_followup_instructions(client, snapshot, messages, provided_equipment, training_history, logger)
                if training_history and (snapshot.get('historyFingerprint') != training_history.fingerprint
                    or training_history.unreviewed(snapshot['planIndex'], messages, provided_equipment)
                    or training_history.load_suitability_errors(snapshot['planIndex'], messages, provided_equipment)):
                    raise ValueError('Review current training evidence and re-audit the draft before confirming generation.')
            except ValueError as error:
                feedback = planning_tool_failure("generate_workout", error)
                feedback["requires_plan_revision"] = True
                return {
                    "result": json.dumps(feedback, ensure_ascii=False), "continue_planning": True,
                    "should_exit": False, "generation_result": None,
                }
        custom_prompt = function_args.get("custom_prompt", "")
        generation_result = execute_workout_generation(
            client,
            messages,
            custom_prompt,
            None,
            provided_equipment,
            logger,
            script_dir,
            force_use_reasoner=force_use_reasoner,
            allow_educated_load_guesses=allow_educated_load_guesses,
            training_history=training_history,
        )

        if generation_result["success"]:
            for emitter_turn in generation_result.get("emitter_conversations", []):
                messages.append(
                    _message(
                        "emitter",
                        step=emitter_turn["step"],
                        item_id=emitter_turn["item_id"],
                        request_messages=emitter_turn["request_messages"],
                        response_content=emitter_turn["response_content"],
                    )
                )
            if generation_result["filepath"]:
                result_message = (
                    f"Workout generated successfully and saved to: {generation_result['filepath']}"
                )
                if generation_result.get("guidance_filepath"):
                    result_message += f"\nManual program guidance saved to: {generation_result['guidance_filepath']}"
            else:
                result_message = "Workout generated successfully (but file save failed - check output above)"
        else:
            result_message = f"Workout generation failed: {generation_result.get('error', 'Unknown error')}"
            if generation_result.get("requires_plan_revision"):
                result_message = json.dumps({
                    "requires_plan_revision": True,
                    "instruction": "Revise the plan using this deterministic audit. Keep the user's agreed goals and equipment restrictions. You may change exercises, pairings and prescriptions as needed. Validate library selection, show the entire revised preview, and obtain a NEW CONFIRM GENERATE before regenerating. If goals cannot be met, explain the conflict and ask the user to resolve it; never silently relax them.",
                    "audit": generation_result["programming_audit"],
                }, ensure_ascii=False)

        return {
            "result": result_message,
            "should_exit": False,
            "generation_result": generation_result,
        }

    if function_name == 'record_planning_decisions':
        result = record_planning_decisions(client, function_args, messages, logger, progress, equipment=provided_equipment)
        return {'result': json.dumps(result, ensure_ascii=False), 'should_exit': False, 'generation_result': None,
                'decision_preview': ('Recorded planning choices:\n' + render_decisions(result['decisions'])) if result['passed'] and not result.get('cached') else None}

    if function_name == "set_workout_requirements":
        arguments = dict(function_args)
        decisions = arguments.pop('planningDecisions', None)
        result = set_workout_requirements(arguments, messages, provided_equipment or {}, client, progress)
        review_options = {'planning_decisions': decisions} if decisions is not None else {}
        result = review_requirements(client, result, messages, logger, progress, **review_options)
        if not result['passed']:
            return {'result': json.dumps(result, ensure_ascii=False), 'should_exit': False, 'generation_result': None}
        pending = not requirements_approved(messages, result)
        return {"result": json.dumps(result, ensure_ascii=False), "requirements_preview": result["requirementsPreview"] if pending else None,
                "requirements_pending": pending, "requirements_id": result['requirementsId'],
                "should_exit": False, "generation_result": None}

    if function_name == 'propose_workout_alternatives':
        if function_args.get('staleAlternativeAssessment'):
            from .conflict_resolution import CONFLICT_RESOLUTION_VERSION
            diagnosis_index, previous = _latest_result(messages, 'propose_workout_alternatives')
            if previous.get('executionFailure'):
                call_names = {call.get('id'): call.get('function', {}).get('name')
                    for message in messages for call in message.get('tool_calls', [])}
                for index in range(len(messages) - 1, -1, -1):
                    message = messages[index]
                    if (message.get('role') != 'tool'
                            or call_names.get(message.get('tool_call_id')) != 'propose_workout_alternatives'):
                        continue
                    try:
                        saved_result = json.loads(message.get('content') or '{}')
                    except (TypeError, ValueError):
                        continue
                    if (not isinstance(saved_result, dict)
                            or saved_result.get('requirementsId') != function_args.get('requirementsId')
                            or saved_result.get('baseDraftId') != function_args.get('baseDraftId')
                            or saved_result.get('diagnosisVersion') != CONFLICT_RESOLUTION_VERSION
                            or not any(item.get('repairCandidateId') == function_args.get('repairCandidateId')
                                for item in saved_result.get('alternativeRepairCandidates', [])
                                if isinstance(item, dict))):
                        continue
                    diagnosis_index, previous = index, saved_result
                    break
            repair_index, repair_result = _latest_result(messages, 'repair_workout_alternative')
            requested_candidate_id = function_args.get('repairCandidateId')
            candidate = next((item for item in previous.get('alternativeRepairCandidates', [])
                if item.get('repairCandidateId') == requested_candidate_id), None)
            source_candidate_id = candidate.get('repairCandidateId') if candidate else None
            if (repair_index > diagnosis_index
                    and repair_result.get('repairCandidateId') in (requested_candidate_id, source_candidate_id)):
                from .alternative_repair import _fresh_binding, _latest_materialized_reviewed_candidate
                from .planning_decisions import resolved_decisions
                source_candidate = candidate
                for possible_source in previous.get('alternativeRepairCandidates', []):
                    reviewed_candidate = _latest_materialized_reviewed_candidate(
                        messages, possible_source, diagnosis_index)
                    if (reviewed_candidate is not None
                            and reviewed_candidate.get('repairCandidateId') == requested_candidate_id):
                        source_candidate = possible_source
                        candidate = reviewed_candidate
                        source_candidate_id = possible_source.get('repairCandidateId')
                        break
                if source_candidate is not None and candidate is not None:
                    _, original_record = _latest_result(messages, 'set_workout_requirements')
                    candidate_binding = copy.deepcopy(candidate)
                    candidate_binding['resolvedDecisions'] = copy.deepcopy(resolved_decisions(messages))
                    if not _fresh_binding(candidate_binding, messages, original_record.get('requirements', {}),
                            provided_equipment or {}, training_history, resolved_decisions(messages)):
                        candidate = None
                    else:
                        candidate = candidate_binding
                        source_candidate_id = source_candidate.get('repairCandidateId')
            if candidate:
                from .alternative_repair import _fresh_binding
                from .planning_decisions import resolved_decisions
                _, original_record = _latest_result(messages, 'set_workout_requirements')
                current_decisions = resolved_decisions(messages)
                refreshed_binding = copy.deepcopy(candidate)
                refreshed_binding['resolvedDecisions'] = copy.deepcopy(current_decisions)
                if _fresh_binding(refreshed_binding, messages, original_record.get('requirements', {}),
                        provided_equipment or {}, training_history, current_decisions):
                    candidate = refreshed_binding
            if (candidate and previous.get('diagnosisVersion') == CONFLICT_RESOLUTION_VERSION
                    and candidate.get('diagnosisVersion') in (None, CONFLICT_RESOLUTION_VERSION)):
                from .alternative_repair import refresh_candidate_assessment
                candidate = copy.deepcopy(candidate)
                candidate['diagnosisVersion'] = previous['diagnosisVersion']
                refreshed = refresh_candidate_assessment(candidate, messages, provided_equipment or {},
                    training_history, allow_educated_load_guesses, client, logger, progress)
                refreshed_candidate = copy.deepcopy(refreshed['candidate'])
                result = copy.deepcopy(previous)
                refreshed_candidate['diagnosisCandidateId'] = (candidate.get('diagnosisCandidateId')
                    or source_candidate_id or candidate['repairCandidateId'])
                result['alternativeRepairCandidates'] = [
                    refreshed_candidate if item.get('repairCandidateId') == source_candidate_id
                    else copy.deepcopy(item) for item in previous.get('alternativeRepairCandidates', [])]
                result['assessmentRefresh'] = {'status': refreshed['status'],
                    'repairCandidateId': candidate['repairCandidateId'],
                    **({'reason': refreshed['reason']} if refreshed.get('reason') else {})}
                previews = []
                if refreshed['status'] == 'proposal_ready':
                    proposal = refreshed['proposal']
                    result.update(passed=True, outcome='alternatives_ready', proposals=[proposal], errors=[],
                        instruction='The saved alternative passed the current numerical audit and independent review. Show the exact validated proposal and wait for explicit approval.',
                        reason='The alternative passed full numerical audit and a fresh independent review. It still requires explicit user approval.',
                        jointPlanningStopped=False,
                        originalRequirementsHash=candidate['originalRequirementsHash'],
                        libraryFingerprint=candidate['libraryFingerprint'],
                        trainingHistoryFingerprint=candidate['trainingHistoryFingerprint'],
                        approvalInstruction='No proposal changes the active requirements until its exact proposalId is explicitly approved.')
                    from .conflict_resolution import render_alternative_preview
                    previews = [{'id': proposal['proposalId'], 'text': render_alternative_preview(proposal)}]
                elif refreshed['status'] == 'refreshed':
                    result.update(passed=False, jointPlanningStopped=False,
                        errors=copy.deepcopy(refreshed_candidate.get('reviewErrors', [])),
                        instruction='Repair the saved alternative using its refreshed findings assessment; it remains unapproved.',
                        reason='The saved assessment is current; actionable findings require coordinated candidate repair.')
                elif refreshed['status'] != 'refreshed':
                    result.update(passed=False, outcome='unresolved', reason=refreshed.get('reason',
                        'The saved alternative assessment remains unresolved; its requirements and candidate are unchanged.'))
                return {'result': json.dumps(result, ensure_ascii=False), 'alternative_previews': previews,
                    'should_exit': False, 'generation_result': None}

        from .conflict_resolution import diagnose_conflict_and_propose
        from .conflict_resolution import CONFLICT_RESOLUTION_VERSION
        from .restriction_policy import effective_restrictions
        from .planning_tools import latest_draft_submission as resolve_latest_draft_submission, build_draft_plan, library_fingerprint, _fingerprint, render_draft, AUDIT_VERSION
        require_approved_requirements(messages)
        _, stored = _latest_result(messages, 'set_workout_requirements')
        draft, revision = resolve_latest_draft_submission(messages, provided_equipment)
        if function_args['requirementsId'] != stored['requirementsId'] or function_args['baseDraftId'] != revision:
            raise ValueError('Alternative diagnosis requires the current approved requirements and saved draft revision.')
        workouts = function_args.get('workouts', (draft or {}).get('workouts'))
        if workouts != (draft or {}).get('workouts'):
            raise ValueError('Diagnose the saved candidate; audit substantive menu changes before proposing trade-offs.')
        allocation_conflict = None
        from .allocation import latest_allocation_conflict
        _, saved_allocation = latest_allocation_conflict(messages)
        _, current_audit = _latest_result(messages, 'audit_workout_plan')
        from .planning_decisions import resolved_decisions
        current_resolved_decisions = resolved_decisions(messages)
        candidate_conflict = saved_allocation.get('allocationConflict') if isinstance(saved_allocation, dict) else None
        if (isinstance(candidate_conflict, dict) and candidate_conflict.get('status') == 'infeasible'
                and candidate_conflict.get('requirementsId') == stored['requirementsId']
                and candidate_conflict.get('baseDraftId') == revision
                and current_audit.get('requirementsId') == stored['requirementsId']
                and current_audit.get('currentDraftId') == revision
                and candidate_conflict.get('libraryFingerprint') == library_fingerprint(provided_equipment)
                and candidate_conflict.get('historyFingerprint') == current_audit.get('historyFingerprint')
                and candidate_conflict.get('resolvedDecisions', {}) == current_audit.get('resolvedDecisions', {})):
            from .allocation import allocation_input_fingerprint
            current_fingerprint = allocation_input_fingerprint(draft, stored['requirementsId'], provided_equipment,
                history_fingerprint=current_audit.get('historyFingerprint'),
                resolved_decisions=current_audit.get('resolvedDecisions', {}),
                allow_educated_load_guesses=candidate_conflict.get('allowEducatedLoadGuesses', True),
                requirements=stored['requirements'])
            if current_fingerprint == candidate_conflict.get('conflictFingerprint'):
                allocation_conflict = copy.deepcopy(candidate_conflict)
        failed_alternative_candidates = []
        def review_candidate(sessions, variant, joint):
            identifier = 'PROPOSAL_' + _fingerprint(variant)[:20]
            from .requirement_accounting import relaxation_paths, pointer
            from .requirement_accounting import relaxation_rank_by_path
            source_ranks = relaxation_rank_by_path(stored['requirements'])
            changes = [{'path': path, 'from': pointer(stored['requirements'], path), 'to': pointer(variant, path)}
                       for path in relaxation_paths(stored['requirements'])
                       if pointer(stored['requirements'], path) != pointer(variant, path)]
            proposed = {**copy.deepcopy(stored), 'requirements': variant, 'requirementsId': identifier,
                        'proposedAlternative': {'originalRequirementsId': stored['requirementsId'],
                            'changes': changes, 'requiresUserApproval': True}}
            local = messages + [{'role': 'assistant', 'tool_calls': [{'id': 'hypothetical_requirements', 'type': 'function',
                'function': {'name': 'set_workout_requirements', 'arguments': json.dumps(variant)}}]},
                {'role': 'tool', 'tool_call_id': 'hypothetical_requirements', 'content': json.dumps(proposed)}]
            arguments = {'requirementsId': identifier, 'name': (draft or {}).get('name', 'Alternative'), 'workouts': sessions}
            source_program_guidance = (current_audit.get('submittedDraft') or {}).get('programGuidance', '')
            if isinstance(source_program_guidance, str) and source_program_guidance.strip():
                arguments['programGuidance'] = source_program_guidance
            _, previous_proposals = _latest_result(messages, 'propose_workout_alternatives')
            previous_candidate = next((item for item in previous_proposals.get('alternativeRepairCandidates', [])
                if item.get('requirementsId') == identifier and item.get('baseDraftId') == revision
                and item.get('requirements') == variant and item.get('workouts') == sessions
                and item.get('libraryFingerprint') == library_fingerprint(provided_equipment)
                and item.get('trainingHistoryFingerprint') == getattr(training_history, 'fingerprint', None)
                and isinstance(item.get('review'), dict)), None)
            if previous_candidate:
                cached_review_call = 'cached_alternative_review_' + identifier
                local.extend([
                    {'role': 'assistant', 'tool_calls': [{'id': cached_review_call, 'type': 'function',
                        'function': {'name': 'audit_workout_plan', 'arguments': '{}'}}]},
                    {'role': 'tool', 'tool_call_id': cached_review_call, 'content': json.dumps({
                        'passed': False, 'requirementsId': identifier, 'currentDraftId': revision,
                        'submittedDraft': arguments, 'audit': copy.deepcopy(previous_candidate.get('audit', {})),
                        'review': copy.deepcopy(previous_candidate['review'])})},
                ])
            snapshot = {'passed': True, 'requirementsId': identifier, 'draftId': 'PROPOSED_' + _fingerprint(arguments),
                'submittedDraft': arguments, 'currentDraftId': revision, 'audit': joint['audit'], 'errors': [],
                'planIndex': build_draft_plan(arguments, provided_equipment, variant, effective_restrictions(stored, provided_equipment)),
                'auditVersion': AUDIT_VERSION,
                'libraryFingerprint': library_fingerprint(provided_equipment),
                'historyFingerprint': getattr(training_history, 'fingerprint', None),
                'allowEducatedLoadGuesses': allow_educated_load_guesses,
                'resolvedDecisions': copy.deepcopy(current_resolved_decisions)}
            from .training_history import apply_native_load_calibration_policy
            apply_native_load_calibration_policy(snapshot['planIndex'], local, provided_equipment,
                getattr(training_history, 'fingerprint', None),
                allow_educated_load_guesses=allow_educated_load_guesses)
            snapshot['preview'] = render_draft(snapshot['planIndex'], variant, joint['audit'],
                effective_restrictions(stored, provided_equipment), arguments)
            review = review_draft(client, snapshot, local, provided_equipment, training_history, logger, progress)
            review_receipt = review.get('review', {})
            if (review.get('passed') is not True and review_receipt.get('assessment')
                    and not review_receipt.get('failure') and not review_receipt.get('inProgress')):
                from .joint_planning import candidate_menu_fingerprint
                changes = [{'path': path, 'from': pointer(stored['requirements'], path), 'to': pointer(variant, path)}
                           for path in relaxation_paths(stored['requirements'])
                           if pointer(stored['requirements'], path) != pointer(variant, path)]
                candidate_core = {'requirementsId': identifier, 'baseDraftId': revision,
                    **({'programGuidance': source_program_guidance}
                        if isinstance(source_program_guidance, str) and source_program_guidance.strip() else {}),
                    'diagnosisVersion': CONFLICT_RESOLUTION_VERSION,
                    'reviewVersion': review_receipt.get('version'),
                    'originalRequirementsId': stored['requirementsId'],
                    'requirements': variant, 'workouts': sessions, 'candidateName': (draft or {}).get('name', 'Alternative'),
                    'changes': changes,
                    'restrictionPolicy': effective_restrictions(stored, provided_equipment),
                    **({'relaxationRanks': {change['path']: source_ranks[change['path']] for change in changes
                        if change['path'] in source_ranks}} if any(change['path'] in source_ranks for change in changes) else {}),
                    'audit': joint['audit'], 'review': review_receipt,
                    'originalRequirementsHash': _fingerprint(stored['requirements']),
                    'libraryFingerprint': library_fingerprint(provided_equipment),
                    'trainingHistoryFingerprint': getattr(training_history, 'fingerprint', None),
                    'resolvedDecisions': copy.deepcopy(current_resolved_decisions),
                    'sourceMenuFingerprint': candidate_menu_fingerprint(workouts),
                    'candidateMenuFingerprint': candidate_menu_fingerprint(sessions),
                    'problemFingerprint': joint.get('problemFingerprint')}
                failed_alternative_candidates.append({
                    'repairCandidateId': 'REVISION_' + str(int(_fingerprint(candidate_core)[:12], 16)),
                    **copy.deepcopy(candidate_core), 'reviewErrors': copy.deepcopy(review.get('errors', []))})
            return review
        result = diagnose_conflict_and_propose(requirements_id=stored['requirementsId'], base_draft_id=revision,
            workouts=workouts, requirements=stored['requirements'], equipment=provided_equipment,
            restriction_policy=effective_restrictions(stored, provided_equipment), review_candidate=review_candidate,
            training_history=training_history, messages=messages, allow_educated_load_guesses=allow_educated_load_guesses,
            existing_conflict=(_latest_result(messages, 'audit_workout_plan')[1].get('coordinatedJointPlanning')
                or _latest_result(messages, 'audit_workout_plan')[1].get('automaticAllocation')),
            allocation_conflict=allocation_conflict)
        result.setdefault('diagnosisVersion', CONFLICT_RESOLUTION_VERSION)
        result.setdefault('historyFingerprint', getattr(training_history, 'fingerprint', None))
        result.setdefault('libraryFingerprint', library_fingerprint(provided_equipment or {}))
        result.setdefault('resolvedDecisions', copy.deepcopy(current_resolved_decisions))
        from .conflict_resolution import render_alternative_preview
        result.setdefault('baseDraftId', revision)
        result.setdefault('requirementsId', stored['requirementsId'])
        if failed_alternative_candidates:
            result['alternativeRepairCandidates'] = failed_alternative_candidates[:2]
        if not result.get('proposals'):
            from .repair_capabilities import has_unresolved_capabilities
            repairable_candidates = [candidate for candidate in failed_alternative_candidates[:2]
                if not has_unresolved_capabilities(candidate['review'].get('assessment'))
                and any(group.get('disposition') == 'repair'
                    for group in candidate['review'].get('assessment', {}).get('groups', []))]
            result.update(passed=False, jointPlanningStopped=not bool(repairable_candidates),
                instruction=('Continue with coordinated repair of the saved alternative and its current findings; '
                    'do not repeat conflict diagnosis or approve the candidate.' if repairable_candidates else
                    result.get('reason', 'No complete reviewed alternative was established.')),
                errors=([error for candidate in repairable_candidates for error in candidate.get('reviewErrors', [])]
                    if repairable_candidates else [{'code': 'joint_diagnosis_' + result['outcome'],
                        'owner': 'conflict_diagnosis', 'message': result.get('reason', result['outcome'])}]))
        previews = [{'id': proposal['proposalId'], 'text': render_alternative_preview(proposal)}
                    for proposal in result.get('proposals', [])]
        return {'result': json.dumps(result, ensure_ascii=False), 'alternative_previews': previews,
                'should_exit': False, 'generation_result': None,
                'decision_preview': None if previews else result.get('reason', result.get('outcome'))}

    if function_name == 'repair_workout_alternative':
        if not isinstance(alternative_repair_task, dict):
            raise ValueError('There is no current saved hypothetical alternative to repair.')
        from .alternative_repair import execute_repair
        result = execute_repair(function_args, alternative_repair_task, messages, provided_equipment or {},
            training_history, allow_educated_load_guesses, client, logger, progress)
        if isinstance(result, dict) and alternative_repair_task.get('trainingHistoryFingerprint') is not None:
            result['trainingHistoryFingerprint'] = alternative_repair_task['trainingHistoryFingerprint']
        previews = []
        if result.get('outcome') == 'alternatives_ready' and result.get('repairStatus') == 'repaired_and_reviewed':
            from .conflict_resolution import render_alternative_preview
            previews = [{'id': result['proposal']['proposalId'],
                'text': render_alternative_preview(result['proposal'])}]
        return {'result': json.dumps(result, ensure_ascii=False), 'alternative_previews': previews,
                'should_exit': False, 'generation_result': None,
                'decision_preview': None if previews else result.get('reason', result.get('outcome'))}

    if function_name == 'accept_workout_alternative':
        from .conflict_resolution import accept_workout_alternative
        from .planning_tools import REQUIREMENTS_VERSION, available_muscle_targets
        _, stored = _latest_result(messages, 'set_workout_requirements')
        repair_index, repaired = _latest_result(messages, 'repair_workout_alternative')
        proposal_index, _ = _latest_result(messages, 'propose_workout_alternatives')
        if (repair_index > proposal_index and isinstance(repaired, dict) and repaired.get('outcome') == 'alternatives_ready'
                and repaired.get('repairStatus') == 'repaired_and_reviewed'
                and repaired.get('passed') is True and isinstance(repaired.get('proposal'), dict)):
            proposal = repaired['proposal']
            if proposal.get('proposalId') != function_args['proposalId']:
                raise ValueError('Only the latest repaired alternative can be approved.')
            proposals = {'outcome': 'alternatives_ready', 'requirementsId': stored['requirementsId'],
                'diagnosisVersion': proposal.get('diagnosisVersion'),
                'reviewVersion': proposal.get('reviewVersion'),
                'baseDraftId': proposal['baseDraftId'], 'originalRequirementsHash': proposal['originalRequirementsHash'],
                'libraryFingerprint': proposal['libraryFingerprint'],
                'trainingHistoryFingerprint': proposal['trainingHistoryFingerprint'], 'proposals': [proposal]}
            approval_messages = messages + [
                {'role': 'assistant', 'tool_calls': [{'id': 'repaired_alternative_acceptance', 'type': 'function',
                    'function': {'name': 'propose_workout_alternatives', 'arguments': '{}'}}]},
                {'role': 'tool', 'tool_call_id': 'repaired_alternative_acceptance', 'content': json.dumps(proposals)},
            ]
        else:
            _, proposals = _latest_result(messages, 'propose_workout_alternatives')
            approval_messages = messages
        accepted = accept_workout_alternative(proposal_id=function_args['proposalId'], proposal_result=proposals,
            messages=approval_messages, current_requirements=stored, equipment=provided_equipment, training_history=training_history)
        candidate = {**copy.deepcopy(stored), **accepted, 'requirementsVersion': REQUIREMENTS_VERSION,
            'sourceMessages': requirement_sources(messages), 'supportedMuscleTargets': available_muscle_targets(provided_equipment),
            'proposedAlternative': {'originalRequirementsId': stored['requirementsId'],
                'approvedAlternativeId': accepted['approvedAlternativeId'],
                'changes': next(p['changes'] for p in proposals['proposals'] if p['proposalId'] == accepted['approvedAlternativeId']),
                'requiresUserApproval': False}}
        candidate.pop('sourceReview', None)
        result = review_requirements(client, candidate, messages, logger, progress)
        return {'result': json.dumps(result, ensure_ascii=False), 'requirements_preview': result.get('requirementsPreview'),
                'requirements_id': result['requirementsId'], 'requirements_pending': False,
                'should_exit': False, 'generation_result': None}

    if function_name == "audit_workout_plan":
        qualification = None
        if coordinated_repair:
            from .allocation import qualify_coordinated_candidate
            function_args, qualification = qualify_coordinated_candidate(client, function_args, provided_equipment or {},
                messages, training_history, logger,
                coordinated_repair_context=coordinated_repair if isinstance(coordinated_repair, dict) else None)
        _, prior_candidate = _latest_result(messages, 'audit_workout_plan')
        _, stored_requirements = _latest_result(messages, 'set_workout_requirements')
        worker_index, workers = _latest_result(messages, 'draft_workout_sessions')
        audit_index, prior_audit = _latest_result(messages, 'audit_workout_plan')
        unresolved_record = ((workers.get('jointUnresolvedCandidate') or {}) if worker_index > audit_index
            else (prior_audit.get('jointUnresolvedCandidate') or {}))
        _, current_revision = latest_draft_submission(messages, provided_equipment or {})
        retained_unresolved = current_unresolved_joint_candidate(unresolved_record, stored_requirements,
            provided_equipment or {}, messages, training_history, current_revision,
            allow_educated_load_guesses, expected_submission=function_args)
        if not qualification and retained_unresolved:
            qualification = copy.deepcopy(retained_unresolved['recipeQualification'])
        if not qualification and prior_candidate.get('coordinatedCandidatePending'):
            qualification = prior_candidate.get('recipeQualification')
        try:
            result = audit_workout_plan(function_args, provided_equipment or {}, messages, allow_educated_load_guesses, training_history)
        except PlanningInputError as error:
            if not qualification:
                raise
            result = planning_tool_failure('audit_workout_plan', error, function_args)
            if not result.get('submittedDraft') and all(is_metadata_error(item) for item in result.get('errors', [])):
                from .planning_tools import latest_draft_submission as resolve_latest_draft_submission, library_fingerprint
                from .json_patching import apply_json_patch
                previous, revision = resolve_latest_draft_submission(messages, provided_equipment or {})
                candidate = (apply_json_patch(previous, function_args['patch']) if 'patch' in function_args else copy.deepcopy(function_args))
                result.update(submittedDraft=candidate, libraryFingerprint=library_fingerprint(provided_equipment or {}),
                    currentDraftId=(revision if candidate == previous else f'REVISION_{int(revision.removeprefix("REVISION_")) + 1}' if revision else 'REVISION_0'))
            from .planning_decisions import resolved_decisions
            from .review_assessment import latest_assessment
            result.update(requirementsId=function_args['requirementsId'],
                historyFingerprint=getattr(training_history, 'fingerprint', None), resolvedDecisions=resolved_decisions(messages),
                recipeQualification=qualification, coordinatedCandidatePending=True)
            result['findingsAssessment'] = latest_assessment(messages, result)
            return {'result': json.dumps(result, ensure_ascii=False), 'draft_preview': None,
                    'should_exit': False, 'generation_result': None}
        retained_conflict = workers.get('jointConflictCandidate') or {}
        if retained_conflict:
            import hashlib
            from .joint_planning import prescription_fingerprint, SELECTION_POLICY_VERSION, joint_problem_fingerprint
            from .planning_tools import source_message_context, library_fingerprint
            valid_conflict = (retained_conflict.get('submission') == function_args
                and retained_conflict.get('requirementsId') == result['requirementsId']
                and retained_conflict.get('libraryFingerprint') == library_fingerprint(provided_equipment)
                and retained_conflict.get('historyFingerprint') == getattr(training_history, 'fingerprint', None)
                and retained_conflict.get('solvedPrescriptionHash') == prescription_fingerprint(function_args.get('workouts', []))
                and retained_conflict.get('sourceMessagesHash') == hashlib.sha256(json.dumps(source_message_context(requirement_sources(messages)), sort_keys=True).encode()).hexdigest()
                and retained_conflict.get('jointPlanning', {}).get('selectionPolicyVersion') == SELECTION_POLICY_VERSION
                and retained_conflict['jointPlanning'].get('problemFingerprint') == joint_problem_fingerprint(
                    function_args['workouts'], _latest_result(messages, 'set_workout_requirements')[1]['requirements'], provided_equipment,
                    training_history, messages, restriction_policy=_latest_result(messages, 'set_workout_requirements')[1].get('restrictionPolicy'),
                    allow_educated_load_guesses=allow_educated_load_guesses,
                    preserve_source_selection=True))
        else:
            valid_conflict = False
        from .joint_planning import JOINT_REPAIRABLE_AUDIT_ERRORS
        if valid_conflict:
            result['coordinatedJointPlanning'] = copy.deepcopy(retained_conflict['jointPlanning'])
            result['recipeQualification'] = copy.deepcopy(retained_conflict['recipeQualification'])
            result['jointPlanningStopped'] = True
        elif qualification and (result.get('passed') or (
                result.get('errors') and all(error.get('code') in JOINT_REPAIRABLE_AUDIT_ERRORS
                    for error in result['errors']))):
            _, requirements = _latest_result(messages, 'set_workout_requirements')
            from .allocation import reusable_joint_receipt
            reused = reusable_joint_receipt(prior_candidate, result['requirementsId'],
                result['submittedDraft']['workouts'], requirements['requirements'], provided_equipment or {},
                messages, training_history, requirements.get('restrictionPolicy'), allow_educated_load_guesses,
                preserve_source_selection=True)
            if reused:
                result['coordinatedJointPlanning'] = {**reused,
                    'reusedForValidatedCandidate': True,
                    'instruction': 'The current candidate passed the production audit and retains the prior validated prescription objectives; no new optimization claim was made.'}
            else:
                from .joint_planning import solve_prescribed_week, prescription_fingerprint
                if checkpoint:
                    pending = pending_review_checkpoint({**result, 'recipeQualification': qualification,
                        'coordinatedCandidatePending': True})
                    pending['errors'] = result.get('errors', []) + [{'code': 'coordinated_joint_pending', 'path': '/',
                        'message': 'Recipe contracts saved; joint planning and semantic review are unfinished.',
                        'repair': 'Resume the saved candidate; do not repeat qualification.'}]
                    checkpoint(pending)
                joint = solve_prescribed_week(result['submittedDraft']['workouts'], requirements['requirements'],
                    provided_equipment or {}, requirements.get('restrictionPolicy'),
                    allow_educated_load_guesses=allow_educated_load_guesses, training_history=training_history,
                    messages=messages, balance=True, preserve_source_selection=True)
                if joint['feasible']:
                    result = audit_workout_plan({'requirementsId': result['requirementsId'],
                        'name': result['submittedDraft']['name'], 'workouts': joint['sessions']},
                        provided_equipment or {}, messages, allow_educated_load_guesses, training_history)
                result['coordinatedJointPlanning'] = {key: value for key, value in joint.items() if key not in ('sessions', 'audit')}
                if retained_unresolved and not joint['feasible'] and joint.get('status') == 'unproven':
                    import hashlib
                    from .planning_tools import source_message_context, library_fingerprint, _fingerprint
                    unresolved_submission = result['submittedDraft']
                    result['jointUnresolvedCandidate'] = {
                        'requirementsId': result['requirementsId'],
                        'baseDraftId': result.get('currentDraftId'),
                        'submission': copy.deepcopy(unresolved_submission),
                        'submissionHash': _fingerprint(unresolved_submission),
                        'solvedPrescriptionHash': prescription_fingerprint(unresolved_submission['workouts']),
                        'libraryFingerprint': library_fingerprint(provided_equipment or {}),
                        'historyFingerprint': getattr(training_history, 'fingerprint', None),
                        'sourceMessagesHash': hashlib.sha256(json.dumps(source_message_context(
                            requirement_sources(messages)), sort_keys=True).encode()).hexdigest(),
                        'jointPlanning': copy.deepcopy(result['coordinatedJointPlanning']),
                        'recipeQualification': copy.deepcopy(qualification),
                    }
        elif not qualification:
            result = auto_allocate_workout(result, provided_equipment or {}, messages, allow_educated_load_guesses,
                                            training_history, logger, progress)
        if qualification:
            result['recipeQualification'] = qualification
        if training_history:
            if result.get('historyFingerprint') != training_history.fingerprint:
                result['cached'] = False
            result['historyFingerprint'] = training_history.fingerprint
            if result.get('preview'):
                result['preview'] = result['preview'].split('\n\nTraining history snapshot:', 1)[0]
                result['preview'] += f"\n\nTraining history snapshot: `{training_history.fingerprint[:12]}`. Comparable records reviewed where available; historical loads are not measured strength limits."
        if checkpoint and result.get('passed'):
            checkpoint(pending_review_checkpoint(result))
        result = review_draft(client, result, messages, provided_equipment or {}, training_history, logger, progress,
                              **({'on_checkpoint': checkpoint} if checkpoint else {}))
        if (result.get('coordinatedJointPlanning') or {}).get('status') == 'unproven':
            result['passed'] = False
            result['errors'] = [*result.get('errors', []), {'code': 'coordinated_joint_unresolved', 'path': '/',
                'message': 'The joint solver did not establish feasibility. Preserve the candidate and retry the unfinished solve; do not export it.'}]
            result.pop('preview', None)
            result.pop('planIndex', None)
        from .requirement_accounting import outcome
        result['planningOutcome'] = outcome(result)
        for error in result.get('errors', []):
            error.setdefault('owner', 'rendering' if is_metadata_error(error) else 'review' if error.get('code') == 'independent_review_finding' else 'candidate')
        if not result.get('passed'):
            result.pop('planIndex', None)
        return {"result": json.dumps(result, ensure_ascii=False), "draft_preview": None if result.get("cached") else result.get("preview"),
                "draft_id": result.get("draftId", result["requirementsId"]), "should_exit": False, "generation_result": None}

    if function_name == 'get_training_evidence':
        require_approved_requirements(messages)
        if training_history is None:
            raise ValueError('No history backup loaded; start with --history-backup-file')
        result = execute_lookup_batch([('history', function_name, function_args)], provided_equipment or {}, client,
                                      messages, training_history, logger)['history']
        return {'result': json.dumps(result),
                'should_exit': False, 'generation_result': None}

    if function_name == 'prepare_workout_sessions':
        active_messages = _sanitize_stale_history_receipts(messages,
            getattr(training_history, 'fingerprint', None), True)
        return {'result': json.dumps(prepare_workout_sessions(function_args, active_messages, provided_equipment or {})),
                'should_exit': False, 'generation_result': None}

    if function_name == 'prepare_workout_session':
        active_messages = _sanitize_stale_history_receipts(messages,
            getattr(training_history, 'fingerprint', None), True)
        return {'result': json.dumps(prepare_workout_session(function_args, active_messages, provided_equipment or {})),
                'should_exit': False, 'generation_result': None}

    if function_name == 'get_workout_draft':
        result = get_workout_draft(function_args, messages, provided_equipment or {})
        return {'result': json.dumps(result), 'should_exit': False, 'generation_result': None}

    if function_name == 'get_exercise_candidates':
        require_approved_requirements(messages)
        return {'result': json.dumps(get_exercise_candidates(function_args, provided_equipment or {}, messages)),
                'should_exit': False, 'generation_result': None}

    if function_name == 'allocate_workout_sets':
        result = allocate_workout_sets(function_args, provided_equipment or {}, messages,
                                      allow_educated_load_guesses=allow_educated_load_guesses, training_history=training_history)
        return {'result': json.dumps(result, ensure_ascii=False), 'should_exit': False, 'generation_result': None}

    if function_name in ("search_exercise_library", "select_exercises"):
        if (provided_equipment or {}).get('exerciseDefinitions'):
            require_approved_requirements(messages)
        return {
            "result": json.dumps(execute_library_tool(function_name, function_args, provided_equipment, client=client, messages=messages, **({'progress': progress} if progress else {})), ensure_ascii=False),
            "should_exit": False, "generation_result": None,
        }

    return {
        "result": f"Unknown function: {function_name}",
        "should_exit": False,
        "generation_result": None,
    }


def main(deps=None):
    deps = deps or resolve_shell_deps()
    _default_script_dir = deps.default_script_dir
    load_equipment_from_file = deps.load_equipment_from_file
    load_conversation_record = deps.load_conversation_record
    list_conversations = deps.list_conversations
    set_active_conversation = deps.set_active_conversation
    resolve_conversation_id = deps.resolve_conversation_id
    has_equipment_in_messages = deps.has_equipment_in_messages
    format_equipment_for_conversation = deps.format_equipment_for_conversation
    BASE_SYSTEM_PROMPT = deps.base_system_prompt
    get_log_dir = deps.get_log_dir
    ConversationLogger = deps.ConversationLogger
    chat_call_with_loading = deps.chat_call_with_loading
    GENERATE_WORKOUT_TOOL = deps.generate_workout_tool
    handle_function_call_dep = deps.handle_function_call
    execute_workout_generation = deps.execute_workout_generation
    save_conversation = deps.save_conversation
    list_available_progress = deps.list_available_progress
    delete_progress_file = deps.delete_progress_file
    OpenAI = deps.OpenAI
    httpx = deps.httpx

    parser = argparse.ArgumentParser(description="Workout Assistant & Generator")
    parser.add_argument(
        "--equipment-file",
        type=str,
        help="Path to JSON file containing available equipment (with 'equipments' and optionally 'accessoryEquipments' arrays)",
    )
    parser.add_argument(
        "--exercise-library-file",
        type=str,
        help="Path to a schema-v2 WorkoutStore or JSON object containing exerciseDefinitions",
    )
    parser.add_argument('--history-backup-file', help='AppBackup containing actual workout history; also supplies the exercise library when no --exercise-library-file is given')
    parser.add_argument('--max-repair-rounds', type=int, default=3,
        help='Maximum candidate-changing repair submissions in the current attempt (default: 3)')
    parser.add_argument('--repair-attempt-start-index', type=int, default=None,
        help='Message index marking the start of the current repair-budget attempt')
    reasoner_group = parser.add_mutually_exclusive_group()
    reasoner_group.add_argument(
        "--use-reasoner",
        action="store_true",
        help="Use reasoner model for plan index/emitting without interactive prompt",
    )
    reasoner_group.add_argument(
        "--no-reasoner",
        action="store_true",
        help="Use chat model for plan index/emitting without interactive prompt",
    )
    reasoner_group.add_argument(
        "--hybrid-fast",
        action="store_true",
        help="Use reasoner for plan index and chat model for emitters (faster overall)",
    )
    calibration_group = parser.add_mutually_exclusive_group()
    calibration_group.add_argument(
        "--allow-educated-load-guesses",
        dest="allow_educated_load_guesses",
        action="store_true",
        help="Use emitted starting loads when complete (default; retained for command compatibility)",
    )
    calibration_group.add_argument(
        "--require-load-calibration",
        dest="allow_educated_load_guesses",
        action="store_false",
        help="Require calibration for every weight-loaded exercise",
    )
    parser.set_defaults(allow_educated_load_guesses=True)
    args = parser.parse_args()
    if args.max_repair_rounds < 0 or (args.repair_attempt_start_index is not None and args.repair_attempt_start_index < 0):
        parser.error('--max-repair-rounds and --repair-attempt-start-index must be nonnegative')
    training_history = None
    if args.history_backup_file:
        try:
            with LoadingIndicator('Indexing workout history'):
                training_history = TrainingHistory.from_file(args.history_backup_file)
            print(f"Loaded training history: {training_history.context()['definitionsWithEvidence']} exercise definitions with evidence")
            if not args.exercise_library_file:
                args.exercise_library_file = args.history_backup_file
        except (OSError, ValueError, KeyError, TypeError) as error:
            parser.error(f'Cannot load history backup: {error}')
    force_use_reasoner = (
        "hybrid"
        if args.hybrid_fast
        else (True if args.use_reasoner else (False if args.no_reasoner else None))
    )

    try:
        script_dir = _default_script_dir()
    except (NameError, AttributeError):
        script_dir = os.getcwd()

    provided_equipment = None
    if args.equipment_file:
        try:
            provided_equipment = load_equipment_from_file(args.equipment_file)
            print(f"Loaded equipment from: {args.equipment_file}")
            print(f"  - {len(provided_equipment.get('equipments', []))} equipment item(s)")
            print(f"  - {len(provided_equipment.get('accessoryEquipments', []))} accessory item(s)")
            print()
        except Exception as e:
            print(f"Error loading equipment file: {e}", file=sys.stderr)
            sys.exit(1)

    exercise_definitions = None
    if args.exercise_library_file:
        try:
            library_payload = _load_exercise_library_payload(args.exercise_library_file)
            exercise_definitions = library_payload["exerciseDefinitions"]
            print(f"Loaded {len(exercise_definitions)} exercise definition(s) from: {args.exercise_library_file}")
        except Exception as e:
            print(f"Error loading exercise library file: {e}", file=sys.stderr)
            sys.exit(1)
        provided_equipment = dict(provided_equipment or {})
        provided_equipment["equipments"] = _merge_library_items(
            provided_equipment.get("equipments", []), library_payload["equipments"], "equipment"
        )
        provided_equipment["accessoryEquipments"] = _merge_library_items(
            provided_equipment.get("accessoryEquipments", []),
            library_payload["accessoryEquipments"],
            "accessory equipment",
        )
        provided_equipment["exerciseDefinitions"] = exercise_definitions
        provided_equipment["exerciseMovements"] = library_payload["exerciseMovements"]

    endpoint = resolve_llm_endpoint()
    timeout = httpx.Timeout(None, connect=60.0)
    http_client = httpx.Client(timeout=timeout)
    client = OpenAI(api_key=require_api_key(endpoint), base_url=endpoint.base_url,
                    http_client=http_client, max_retries=0)
    print(f"LLM model: {endpoint.model} @ {endpoint.base_url}")
    get_log_dir(script_dir)

    conversation_id = str(uuid.uuid4())
    messages = _build_initial_messages(
        BASE_SYSTEM_PROMPT,
        provided_equipment,
        format_equipment_for_conversation,
        exercise_definitions,
    )
    metadata = {}

    logger, log_path = _create_logger(ConversationLogger, script_dir, conversation_id)
    metadata.setdefault("log_filename", os.path.basename(log_path))

    state: Dict[str, Any] = {
        "conversation_id": conversation_id,
        "messages": messages,
        "logger": logger,
        "log_path": log_path,
        'pending_images': [],
    }

    def persist_current(metadata_update: Optional[Dict[str, Any]] = None) -> None:
        # Normalize a saved copy; placeholder responses for pending calls must not enter live state.
        saved_messages, _ = _ensure_tool_responses(state["messages"])
        has_non_system_turns = any(
            message.get("role") != "system" for message in state["messages"]
        )
        if not has_non_system_turns and not metadata_update:
            return
        current_record = load_conversation_record(state["conversation_id"], script_dir) or {}
        existing_metadata = current_record.get("metadata", {})
        merged_metadata = existing_metadata.copy()
        if metadata_update:
            merged_metadata.update(metadata_update)
        merged_metadata["log_filename"] = os.path.basename(state["log_path"])
        save_conversation(
            saved_messages,
            conversation_id=state["conversation_id"],
            script_dir=script_dir,
            metadata=merged_metadata,
        )
        if state.get('logger'):
            state['logger'].log(f"Conversation checkpoint saved: {len(saved_messages)} turns.")

    def close_logger() -> None:
        current_logger = state.get("logger")
        if current_logger:
            current_logger.close()
            state["logger"] = None

    def save_and_close() -> None:
        persist_current()
        close_logger()

    atexit.register(save_and_close)

    def switch_conversation(
        next_conversation_id: str,
        next_messages: List[Dict[str, Any]],
        *,
        announce: str,
    ) -> None:
        persist_current()
        next_logger, next_log_path = _create_logger(ConversationLogger, script_dir, next_conversation_id)
        close_logger()
        next_messages, _ = _ensure_tool_responses(next_messages)
        state["conversation_id"] = next_conversation_id
        state["messages"] = next_messages
        state['pending_images'] = []
        state["logger"] = next_logger
        state["log_path"] = next_log_path
        state["logger"].log_print(announce)
        state["logger"].log_print("")

    _print_welcome(state["logger"])

    def resume_generation_picker() -> bool:
        logger = state["logger"]
        logger.log("You> /resume-progress")
        if exercise_definitions and not requirements_approved(state['messages']):
            logger.log_print('Generation blocked: review and CONFIRM REQUIREMENTS before resuming library-backed generation.')
            return False
        progress_list = list_available_progress(script_dir)
        incomplete = [item for item in progress_list if item["status"] == "incomplete"]
        if not incomplete:
            logger.log_print("No incomplete generations found.")
            return False

        logger.log_print("")
        logger.log_print("Available incomplete generations:")
        logger.log_print("=" * 70)
        for index, progress in enumerate(incomplete, start=1):
            logger.log_print(
                f"{index}. Session: {progress['short_id']} | Step: {progress['current_step']} | "
                f"{_format_timestamp(progress.get('timestamp'))}"
            )
        logger.log_print("=" * 70)

        try:
            choice = input(f"\nSelect generation to resume (1-{len(incomplete)}) or 'c' to cancel: ").strip()
            logger.log("resume-progress choice: " + choice)
            if choice.lower() == "c":
                return False
            idx = int(choice) - 1
        except (ValueError, KeyboardInterrupt):
            logger.log_print("Cancelled.")
            return False

        if not (0 <= idx < len(incomplete)):
            logger.log_print("Invalid selection.")
            return False

        selected = incomplete[idx]
        logger.log_print(f"\nResuming generation session {selected['short_id']}...")
        result = execute_workout_generation(
            client,
            state["messages"],
            "",
            selected["session_id"],
            provided_equipment,
            logger,
            script_dir,
            force_use_reasoner=force_use_reasoner,
            allow_educated_load_guesses=args.allow_educated_load_guesses,
            training_history=training_history,
        )
        if result["success"]:
            for emitter_turn in result.get("emitter_conversations", []):
                state["messages"].append(
                    _message(
                        "emitter",
                        step=emitter_turn["step"],
                        item_id=emitter_turn["item_id"],
                        request_messages=emitter_turn["request_messages"],
                        response_content=emitter_turn["response_content"],
                    )
                )
            current_record = load_conversation_record(state["conversation_id"], script_dir) or {}
            persist_current(
                _metadata_for_generation_result(
                    result,
                    state["log_path"],
                    current_record.get("metadata", {}).get("generated_output_paths"),
                )
            )
            report_usage(logger)
            return True

        if result.get("error"):
            logger.log_print(f"Resume error: {result['error']}")
            persist_current(
                _metadata_for_generation_result(result, state["log_path"])
            )
            report_usage(logger)
        return False

    def resume_conversation_by_id(identifier: str) -> bool:
        logger = state["logger"]
        resolved_id = resolve_conversation_id(identifier, script_dir)
        if not resolved_id:
            logger.log_print(f"Could not resolve conversation id: {identifier}")
            return False
        record = load_conversation_record(resolved_id, script_dir)
        if not record:
            logger.log_print(f"Conversation not found: {identifier}")
            return False
        set_active_conversation(resolved_id, script_dir)
        switch_conversation(
            resolved_id,
            list(record["messages"]),
            announce=f"Resumed conversation {resolved_id[:8]}.",
        )
        _render_turns(state["messages"], state["logger"])
        return True

    def handle_image_command(text, text_offset=None):
        command = text.lower()
        if command == '/image' or command.startswith('/image '):
            logger = state['logger']
            path = text[len('/image'):].strip()
            if path.casefold() == 'clear':
                state['pending_images'].clear()
                logger.log_print('Queued images cleared.')
            elif not path:
                logger.log_print('Usage: /image "C:\\path to\\image.png". Then type your message, or use /ml.')
            else:
                if len(path) >= 2 and path[0] == path[-1] and path[0] in ('"', "'"):
                    path = path[1:-1]
                try:
                    attachment = save_image(path, script_dir)
                    if text_offset is not None:
                        attachment['textOffset'] = text_offset
                    if not any(image['sha256'] == attachment['sha256'] and image.get('textOffset') == text_offset
                               for image in state['pending_images']):
                        state['pending_images'].append(attachment)
                    logger.log_print(f'Image queued: {attachment["name"]}. Type your message to send it, or /image clear to discard.')
                except (OSError, ValueError) as error:
                    logger.log_print(f'Cannot attach image: {error}')
            return True
        return False

    while True:
        try:
            question = pending_question(state['messages']) if not state['pending_images'] else None
            if question:
                print_question(question, state['logger'])
            user_input = input("You> ").strip()
        except KeyboardInterrupt:
            state["logger"].log_print("\nCancelled. Use /exit to quit.")
            continue
        except EOFError:
            persist_current()
            report_usage(state['logger'])
            break
        if not user_input:
            continue
        command = user_input.lower()
        logger = state["logger"]
        user_interaction = None

        if handle_image_command(user_input):
            continue

        if command == "/exit":
            persist_current()
            report_usage(state['logger'])
            break

        if command == '/usage':
            report_usage(state['logger'])
            continue

        if command == "/view":
            previews = [message for message in state["messages"] if message.get("canonicalDraftPreview") and message.get("content")]
            replies = previews or [message for message in state["messages"] if message.get("role") == "assistant" and message.get("content")]
            if replies:
                try:
                    print_markdown(replies[-1]["content"], logger, paged=True)
                except KeyboardInterrupt:
                    logger.log_print("\nClosed Markdown viewer.")
            else:
                logger.log_print("No assistant response or workout preview to view yet.")
            continue

        if command == "/clear":
            logger.log("You> /clear")
            next_messages = _build_initial_messages(
                BASE_SYSTEM_PROMPT,
                provided_equipment,
                format_equipment_for_conversation,
                exercise_definitions,
            )
            next_conversation_id = str(uuid.uuid4())
            switch_conversation(
                next_conversation_id,
                next_messages,
                announce="Started a fresh conversation. Archived conversations remain available via /list-conversations.",
            )
            continue

        if command in ("/ml", "/multiline"):
            logger.log_print("Entering multi-line mode. Paste your message; type '/end' on a new line to finish.")
            logger.log_print("(Lines are sent as a single message. Use /image <path> to attach an image; /image clear to discard queued images.)")
            lines = []
            initial_images = list(state['pending_images'])
            while True:
                try:
                    line = input("ML> ")
                except KeyboardInterrupt:
                    logger.log_print("\nCancelled multi-line input. Returning to prompt...")
                    lines.clear()
                    state['pending_images'] = initial_images
                    break
                except EOFError:
                    break
                if line.strip() == "/end":
                    break
                if handle_image_command(line.strip(), text_offset=len('\n'.join(lines)) + bool(lines)):
                    continue
                lines.append(line)
            user_input = "\n".join(lines).rstrip("\n")
            state['pending_images'] = [{**image, **({'textOffset': min(image['textOffset'], len(user_input))}
                if 'textOffset' in image else {})} for image in state['pending_images']]
            if not user_input:
                continue
            command = user_input.lower()

        if exercise_definitions and user_input.startswith('/generate '):
            # Export instructions must enter the conversation before any approval gate.
            trimmed = user_input[len('/generate'):].lstrip()
            prefix_length = len(user_input) - len(trimmed)
            user_input = trimmed.rstrip()
            state['pending_images'] = [{**image, **({'textOffset': min(max(0, image['textOffset'] - prefix_length), len(user_input))}
                if 'textOffset' in image else {})} for image in state['pending_images']]
            command = user_input.lower()

        if state['pending_images'] and (user_input in ('CONFIRM REQUIREMENTS', EXACT_GENERATION_CONFIRMATION, '/continue')
                                       or user_input.startswith('/generate')):
            logger.log_print('Images are queued. Send a message about them first, or /image clear before approving a preview.')
            continue

        if question and not user_input.startswith('/') and not state['pending_images']:
            try:
                answer = answer_question(question, user_input)
            except ValueError as error:
                logger.log_print(str(error))
                continue
            user_interaction = {'question': question, 'input': user_input}
            user_input = answer
            command = user_input.lower()

        if user_input.startswith("/generate"):
            logger.log("You> " + user_input)
            custom = user_input[len("/generate"):].strip()
            if exercise_definitions and not requirements_approved(state['messages']):
                logger.log_print('Generation blocked: review and CONFIRM REQUIREMENTS before generating.')
                continue
            if exercise_definitions:
                try:
                    snapshot = confirmed_draft(state["messages"], provided_equipment, args.allow_educated_load_guesses, require_confirmation=True)
                    review_followup_instructions(client, snapshot, state['messages'], provided_equipment, training_history, logger)
                    if training_history and (snapshot.get('historyFingerprint') != training_history.fingerprint
                        or training_history.unreviewed(snapshot['planIndex'], state['messages'], provided_equipment)
                        or training_history.load_suitability_errors(snapshot['planIndex'], state['messages'], provided_equipment)):
                        raise ValueError('Review current training evidence and re-audit the preview first')
                except ValueError as error:
                    logger.log_print(f"Generation blocked: {error}")
                    persist_current()
                    continue
            result = execute_workout_generation(
                client,
                state["messages"],
                custom,
                None,
                provided_equipment,
                logger,
                script_dir,
                force_use_reasoner=force_use_reasoner,
                allow_educated_load_guesses=args.allow_educated_load_guesses,
                training_history=training_history,
            )
            if result["success"]:
                for emitter_turn in result.get("emitter_conversations", []):
                    state["messages"].append(
                        _message(
                            "emitter",
                            step=emitter_turn["step"],
                            item_id=emitter_turn["item_id"],
                            request_messages=emitter_turn["request_messages"],
                            response_content=emitter_turn["response_content"],
                        )
                    )
                current_record = load_conversation_record(state["conversation_id"], script_dir) or {}
                persist_current(
                    _metadata_for_generation_result(
                        result,
                        state["log_path"],
                        current_record.get("metadata", {}).get("generated_output_paths"),
                    )
                )
            elif result.get("error"):
                logger.log_print(f"Generation error: {result['error']}")
                persist_current(_metadata_for_generation_result(result, state["log_path"]))
            report_usage(logger)
            continue

        if command == "/resume-progress":
            resume_generation_picker()
            continue

        if command == "/resume":
            logger.log("You> /resume")
            conversations = list_conversations(script_dir)
            if not conversations:
                logger.log_print("No saved conversations found.")
                continue

            logger.log_print("")
            logger.log_print("Saved conversations:")
            logger.log_print("=" * 70)
            for index, conversation in enumerate(conversations, start=1):
                logger.log_print(
                    f"{index}. {conversation['conversation_id'][:8]} | {conversation['status']} | "
                    f"{_format_timestamp(conversation.get('updated_at'))} | "
                    f"{conversation['message_count']} turn(s)"
                )
            logger.log_print("=" * 70)

            try:
                choice = input(f"\nSelect conversation (1-{len(conversations)}) or 'c' to cancel: ").strip().lower()
            except KeyboardInterrupt:
                logger.log_print("\nCancelled. Returning to prompt...")
                continue
            logger.log("resume choice: " + choice)
            if choice == "c":
                continue
            try:
                idx = int(choice) - 1
            except ValueError:
                logger.log_print("Invalid selection.")
                continue
            if not (0 <= idx < len(conversations)):
                logger.log_print("Invalid selection.")
                continue
            selected = conversations[idx]
            set_active_conversation(selected["conversation_id"], script_dir)
            switch_conversation(
                selected["conversation_id"],
                list(selected["messages"]),
                announce=f"Resumed conversation {selected['conversation_id'][:8]}.",
            )
            _render_turns(state["messages"], state["logger"])
            continue

        if command == "/list-conversations":
            logger.log("You> /list-conversations")
            conversations = list_conversations(script_dir)
            if not conversations:
                logger.log_print("No saved conversations found.")
                continue
            logger.log_print("")
            logger.log_print("Saved conversations:")
            logger.log_print("=" * 70)
            for conversation in conversations:
                logger.log_print(
                    f"{conversation['conversation_id'][:8]} | {conversation['status']} | "
                    f"{_format_timestamp(conversation.get('updated_at'))} | "
                    f"{conversation['message_count']} turn(s)"
                )
            logger.log_print("=" * 70)
            continue

        if command.startswith("/resume-conversation"):
            logger.log("You> " + user_input)
            parts = user_input.split(maxsplit=1)
            if len(parts) < 2:
                logger.log_print("Usage: /resume-conversation <conversation_id>")
                continue
            resume_conversation_by_id(parts[1].strip())
            continue

        if command.startswith("/show-turns"):
            logger.log("You> " + user_input)
            parts = user_input.split(maxsplit=1)
            if len(parts) == 1:
                _render_turns(state["messages"], logger)
                continue
            resolved_id = resolve_conversation_id(parts[1].strip(), script_dir)
            if not resolved_id:
                logger.log_print(f"Could not resolve conversation id: {parts[1].strip()}")
                continue
            record = load_conversation_record(resolved_id, script_dir)
            if not record:
                logger.log_print(f"Conversation not found: {parts[1].strip()}")
                continue
            _render_turns(record["messages"], logger)
            continue

        if command == "/list-progress":
            logger.log("You> /list-progress")
            progress_list = list_available_progress(script_dir)
            if not progress_list:
                logger.log_print("No saved generation progress found.")
                continue
            logger.log_print("")
            logger.log_print("All saved generation progress:")
            logger.log_print("=" * 70)
            for progress in progress_list:
                status_icon = "✓" if progress["status"] == "complete" else "○"
                logger.log_print(
                    f"{status_icon} Session: {progress['short_id']} | Step: {progress['current_step']} | "
                    f"{_format_timestamp(progress.get('timestamp'))} | {progress['status']}"
                )
            logger.log_print("=" * 70)
            continue

        if command.startswith("/clear-progress"):
            logger.log("You> " + user_input)
            parts = user_input.split(maxsplit=1)
            if len(parts) < 2:
                logger.log_print("Usage: /clear-progress <session_id>")
                logger.log_print("Use /list-progress to see available session IDs")
                continue
            session_id = parts[1].strip()
            if delete_progress_file(session_id, script_dir):
                logger.log_print(f"Progress file for session {session_id[:8]} deleted.")
            else:
                logger.log_print(f"Could not find or delete progress file for session {session_id[:8]}")
            continue

        if command == "/clear-all-progress":
            logger.log("You> /clear-all-progress")
            progress_list = list_available_progress(script_dir)
            if not progress_list:
                logger.log_print("No saved generation progress found.")
                continue
            confirm = input(f"Are you sure you want to delete all {len(progress_list)} progress file(s)? (yes/no): ").strip().lower()
            logger.log("clear-all-progress confirm: " + confirm)
            if confirm == "yes":
                deleted_count = 0
                for progress in progress_list:
                    if delete_progress_file(progress["session_id"], script_dir):
                        deleted_count += 1
                logger.log_print(f"Deleted {deleted_count} progress file(s).")
            else:
                logger.log_print("Cancelled.")
            continue

        logger.log("You> " + user_input)
        state["messages"].append(_message("user", content=user_input,
            **({'userInteraction': user_interaction} if user_interaction else {}),
            **({'imageAttachments': list(state['pending_images'])} if state['pending_images'] else {})))
        state['pending_images'].clear()
        try:
            if command == '/continue' and provided_equipment:
                refreshed = revalidate_saved_preparation(state['messages'], provided_equipment)
                if refreshed:
                    arguments, result = refreshed
                    call_id = 'revalidate_' + uuid.uuid4().hex[:12]
                    state['messages'].append(_message('assistant', content=None, tool_calls=[{
                        'id': call_id, 'type': 'function', 'function': {
                            'name': 'prepare_workout_sessions', 'arguments': json.dumps(arguments)}}]))
                    state['messages'].append(_message('tool', tool_call_id=call_id, content=json.dumps(result)))
                    logger.log_print('Revalidated the saved movement proposal against the current allocator; discovery was reused.')
            if training_history:
                training_history.begin_turn()
            requirements_tool = workout_requirements_tool(provided_equipment, state['messages'])
            search_tool = exercise_library_search_tool(provided_equipment)
            tools = [GENERATE_WORKOUT_TOOL]
            if exercise_definitions:
                tools = [requirements_tool, RECORD_PLANNING_DECISIONS_TOOL]
                if requirements_approved(state['messages']):
                    tools.extend([GENERATE_WORKOUT_TOOL, search_tool, GET_EXERCISE_CANDIDATES_TOOL,
                                  AUDIT_WORKOUT_PLAN_TOOL, ALLOCATE_WORKOUT_SETS_TOOL, GET_WORKOUT_DRAFT_TOOL, PROPOSE_WORKOUT_ALTERNATIVES_TOOL, ACCEPT_WORKOUT_ALTERNATIVE_TOOL])
            if training_history and requirements_approved(state['messages']):
                tools.append(GET_TRAINING_EVIDENCE_TOOL)
            generation_metadata: Optional[Dict[str, Any]] = None
            preview_ready = False
            pending_user_question = None
            requires_plan_revision = False
            failed_draft_signatures = set()
            failed_tool_signatures = set()
            planning_pause = None
            tool_round = 0
            metadata_failures = 0
            repair_attempt_start_index = (args.repair_attempt_start_index if args.repair_attempt_start_index is not None
                                          else len(state['messages']))
            start_planning_budget()
            while True:
                persist_current()
                api_messages = _messages_for_api(state["messages"], bool(exercise_definitions), training_history, provided_equipment)
                planning_state = request_planning_state(api_messages)
                capability_pause = _repair_capability_pause(planning_state)
                if capability_pause:
                    planning_pause = capability_pause
                    break
                saved_reaudit = (planning_state.get('acceptedAlternativeSubmission') or planning_state.get('conflictCandidateSubmission')
                                 or (planning_state.get('unresolvedJointCandidate') or {}).get('submission')
                                 or pending_reaudit(planning_state, user_input))
                if planning_state.get('structuralRepairUnresolved') and not saved_reaudit:
                    planning_pause = planning_state['structuralRepairUnresolved'].get('reason',
                        'Exercise selection remains unresolved; the approved requirements are unchanged.')
                    break
                repair_task = planning_state.get('repairTask')
                construction_task = planning_state.get('constructionTask')
                menu_expansion_task = planning_state.get('candidateMenuExpansionTask')
                parallel_submission = planning_state.get('parallelSubmission')
                if planning_state.get('parallelSubmissionHistoryFingerprint') != (training_history.fingerprint if training_history else None):
                    parallel_submission = None
                if not saved_reaudit:
                    planning_pause = _repair_budget_pause(planning_state, state['messages'],
                        repair_attempt_start_index, args.max_repair_rounds, provided_equipment)
                    if planning_pause:
                        break
                conflict_diagnosis = (None if saved_reaudit or menu_expansion_task
                                       else planning_state.get('conflictDiagnosisTask'))
                evidence_needed = pending_evidence(planning_state, user_input) if training_history else []
                if menu_expansion_task and menu_expansion_task.get('proofScope') == 'exercise_selection_repair':
                    explicit_evidence_errors = {'training_evidence_required', 'training_load_suitability_unresolved'}
                    if not any(error.get('code') in explicit_evidence_errors
                            for error in (planning_state.get('lastAudit') or {}).get('errors', [])
                            if isinstance(error, dict)):
                        evidence_needed = []
                current_menu_tradeoff = (conflict_diagnosis or {}).get('allocationConflictFingerprint')
                if planning_state.get('menuExpansionUnresolved') and not current_menu_tradeoff and not saved_reaudit:
                    unresolved = planning_state['menuExpansionUnresolved']
                    planning_pause = (unresolved.get('instruction') if isinstance(unresolved, dict) else None) or (
                        'The available exercise menu could not be expanded with a validated candidate; requirements remain unchanged.')
                    break
                if planning_state.get('alternativeAssessmentRefreshUnresolved'):
                    planning_pause = planning_state['alternativeAssessmentRefreshUnresolved'].get('reason')
                    break
                omitted_references = [f'WORKOUT_{index}' for index, day in enumerate(
                    (planning_state.get('currentDraft') or {}).get('workouts', [])) if day.get('detailsOmitted')]
                request_tools = tools + [ASK_USER_TOOL]
                selection_tools_task = ({**menu_expansion_task, 'missingDraftReferences': omitted_references}
                    if menu_expansion_task else None)
                request_tools = _candidate_menu_expansion_tools(request_tools, selection_tools_task)
                if planning_state.get('preparationRepairTask'):
                    request_tools = [preparation_patch_tool(planning_state['preparationRepairTask']), ASK_USER_TOOL]
                if planning_state.get('metadataOnlyRepair'):
                    metadata_tool = planning_state.get('metadataRepairTool', 'audit_workout_plan')
                    request_tools = [tool for tool in request_tools + ([PREPARE_WORKOUT_SESSIONS_TOOL] if metadata_tool == 'prepare_workout_sessions' else [])
                                     if tool.get('function', {}).get('name') in (metadata_tool, 'ask_user')]
                if not omitted_references:
                    request_tools = [tool for tool in request_tools if tool.get('function', {}).get('name') != 'get_workout_draft']
                else:
                    request_tools = copy.deepcopy(request_tools)
                    for tool in request_tools:
                        if tool.get('function', {}).get('name') == 'get_workout_draft':
                            tool['function']['parameters']['properties']['workoutReferences']['items']['enum'] = omitted_references
                if construction_task:
                    request_tools.append(PREPARE_WORKOUT_SESSION_TOOL)
                    if (construction_task.get('remainingWeeklySessions') or 0) >= 2:
                        request_tools.append(PREPARE_WORKOUT_SESSIONS_TOOL)
                    request_tools = [tool for tool in request_tools if not construction_tool_failure(
                        tool.get('function', {}).get('name'), {}, planning_state)]
                blocked_discovery = set((planning_state.get('discoveryPaused') or {}).get('blockedTools', []))
                if blocked_discovery:
                    request_tools = [tool for tool in request_tools if tool.get('function', {}).get('name') not in blocked_discovery]
                    logger.log('Discovery returned no new information; reusing saved results for the pending draft task.')
                alternative_repair_task = planning_state.get('alternativeRepairTask')
                if alternative_repair_task:
                    request_tools = [repair_workout_alternative_tool(alternative_repair_task), ASK_USER_TOOL]
                if (planning_state.get('requirementsApproved') and not planning_state.get('planningDecisionNeeded')
                        and not planning_state.get('newInstructionPending')):
                    request_tools = [tool for tool in request_tools if tool.get('function', {}).get('name') != 'record_planning_decisions']
                if (not (repair_task or planning_state.get('editTask')) or (repair_task or {}).get('metadataFields')
                        or ((repair_task or {}).get('allocationNeedsStructuralChange')
                            and not (repair_task or {}).get('structuralAllocationAvailable'))):
                    request_tools = [tool for tool in request_tools if tool.get('function', {}).get('name') != 'allocate_workout_sets']
                if (repair_task or {}).get('structuralAllocationAvailable'):
                    request_tools = copy.deepcopy(request_tools)
                    for tool in request_tools:
                        if tool.get('function', {}).get('name') == 'allocate_workout_sets':
                            params = tool['function']['parameters']
                            params['properties'].pop('preferredSetsBySlot', None)
                            params['properties']['reallocateAcrossSessions'] = {'type': 'boolean', 'const': True}
                            params['required'].append('reallocateAcrossSessions')
                request_options = planner_response_profile(planning_state)
                if alternative_repair_task:
                    request_options.update(reasoning_effort=None, activity='Repairing reviewed workout alternative',
                        tool_choice={'type': 'function', 'function': {'name': 'repair_workout_alternative'}})
                if menu_expansion_task and menu_expansion_task.get('proofScope') == 'exercise_selection_repair':
                    request_options.update(reasoning_effort=None, activity='Repairing exercise selection',
                        tool_choice=('required' if menu_expansion_task.get('stage') != 'discover_candidates'
                            else {'type': 'function', 'function': {'name': 'search_exercise_library'}}))
                elif menu_expansion_task and any(tool.get('function', {}).get('name') == 'audit_workout_plan'
                                                 for tool in request_tools):
                    request_options.update(reasoning_effort=None, activity='Expanding candidate menu',
                        tool_choice={'type': 'function', 'function': {'name': 'audit_workout_plan'}})
                if construction_task:
                    request_tools = [construction_workout_tool(construction_task) if tool.get('function', {}).get('name') == 'audit_workout_plan' else tool
                                     for tool in request_tools]
                    logger.log(f"Construction task: {construction_task['action']}; stage={construction_task['stage']}; "
                               f"remaining sessions={construction_task.get('remainingWeeklySessions')}, effort=low")
                active_draft_edit_task = repair_task or planning_state.get('editTask')
                if active_draft_edit_task and not saved_reaudit:
                    request_tools = [REPAIR_WORKOUT_PLAN_TOOL if tool.get('function', {}).get('name') == 'audit_workout_plan' else tool
                                     for tool in request_tools]
                    from .planning_tools import coordinated_repair_tool
                    full_repair_draft, _ = latest_draft_submission(state['messages'], provided_equipment)
                    if active_draft_edit_task.get('rejectedSubmission'):
                        from .json_patching import apply_json_patch
                        full_repair_draft = apply_json_patch(full_repair_draft,
                            active_draft_edit_task['rejectedSubmission']['patch'])
                    schema_task = {**active_draft_edit_task,
                        'requirementsId': planning_state.get('requirementsId'),
                        'baseDraftId': planning_state.get('currentDraftId'),
                        'currentDraft': full_repair_draft}
                    request_tools = [coordinated_repair_tool(schema_task) if tool.get('function', {}).get('name') == 'audit_workout_plan'
                                     else tool for tool in request_tools]
                text_task = planning_state.get('preparationRepairTask') or repair_task or {}
                if not saved_reaudit and planning_state.get('preparationRepairTask') and text_task.get('metadataFields') and all(is_metadata_error(error) for error in text_task.get('errors', [])):
                    text_tool = 'prepare_workout_sessions'
                    request_tools = [metadata_patch_tool(tool, text_task['metadataFields'])
                                     if tool.get('function', {}).get('name') == text_tool else tool for tool in request_tools]
                if (repair_task or planning_state.get('editTask')) and not saved_reaudit:
                    if repair_task:
                        logger.log(f"Repair task: {repair_task['baseDraftId']}, {len(repair_task.get('findingIndexes', [0]))} related finding(s) "
                                         f"({repair_task['findingCode']}); targeted patch, effort=low")
                request_tools = [_bind_current_draft_id(tool, planning_state.get('currentDraftId'))
                                 for tool in request_tools]
                if tool_round == 0 and user_input == EXACT_GENERATION_CONFIRMATION:
                    logger.log_print('Checking the confirmed draft for export...')
                    content, reasoning_content = None, None
                    tool_calls = [SimpleNamespace(id='confirm_' + uuid.uuid4().hex[:12], type='function', function=SimpleNamespace(
                        name='generate_workout', arguments='{}'))]
                elif conflict_diagnosis:
                    logger.log_print('Refreshing the saved alternative assessment...' if conflict_diagnosis.get('staleAlternativeAssessment')
                                     else 'Diagnosing the saved menu conflict and validating negotiable alternatives...')
                    content, reasoning_content = None, None
                    tool_calls = [SimpleNamespace(id='diagnosis_' + uuid.uuid4().hex[:12], type='function', function=SimpleNamespace(
                        name='propose_workout_alternatives', arguments=json.dumps(conflict_diagnosis)))]
                elif parallel_submission:
                    logger.log_print('Auditing the combined session proposals...')
                    content, reasoning_content = None, None
                    tool_calls = [SimpleNamespace(id='combined_' + uuid.uuid4().hex[:12], type='function', function=SimpleNamespace(
                        name='audit_workout_plan', arguments=json.dumps(parallel_submission)))]
                elif evidence_needed:
                    logger.log_print(f'Retrieving missing evidence for {len(evidence_needed)} selected movements before further planning.')
                    content, reasoning_content = None, None
                    tool_calls = [SimpleNamespace(id='evidence_' + uuid.uuid4().hex[:12], type='function', function=SimpleNamespace(
                        name='get_training_evidence', arguments=json.dumps({'definition_ids': evidence_needed[start:start + 12]})))
                        for start in range(0, len(evidence_needed), 12)]
                elif saved_reaudit:
                    logger.log_print(f"Re-auditing saved draft {saved_reaudit.get('baseDraftId', 'proposal')} against the current requirements, decisions and validators.")
                    content, reasoning_content = None, None
                    saved_reaudit_action = (saved_reaudit.get('_internalAuditAction') or
                                            'saved_candidate_revalidation')
                    tool_calls = [SimpleNamespace(id='reaudit_' + uuid.uuid4().hex[:12], type='function', function=SimpleNamespace(
                        name='audit_workout_plan', arguments=json.dumps({key: value for key, value in saved_reaudit.items()
                            if key != '_internalAuditAction'})))]
                elif construction_task and construction_task.get('stage') == 'draft_sessions':
                    logger.log_print('Drafting prepared sessions concurrently...')
                    content, reasoning_content = None, None
                    tool_calls = [SimpleNamespace(id='sessions_' + uuid.uuid4().hex[:12], type='function', function=SimpleNamespace(
                        name='draft_workout_sessions', arguments=json.dumps({'preparationId': planning_state['parallelPreparation']['preparationId']})))]
                elif construction_task and construction_task.get('stage') == 'retrieve_evidence':
                    planning_pause = 'Required session evidence could not be retrieved. Completed lookups are saved; use /continue to retry the missing records.'
                    break
                else:
                    model_messages = (focus_alternative_repair_request(api_messages, planning_state)
                                      if alternative_repair_task else api_messages)
                    if exercise_definitions:
                        logger.log(f"Planner context: {len(state['messages'])} saved messages -> {len(api_messages)} request messages; "
                                   f"{len(json.dumps(model_messages, ensure_ascii=False))} serialized model characters")
                    with api_metrics_scope(logger, request_options.get('activity', 'Planning')):
                        content, tool_calls, reasoning_content = chat_call_with_loading(client, model_messages, request_tools, logger, **request_options)

                if content is None and tool_calls is None:
                    if tool_round == 0 and not state['messages'][-1].get('imageAttachments'):
                        state["messages"].pop()
                    logger.log_print("Cancelled. Returning to prompt...")
                    break

                has_content = content not in (None, "")
                has_tool_calls = bool(tool_calls)

                if not has_content and not has_tool_calls:
                    if tool_round == 0 and not state['messages'][-1].get('imageAttachments'):
                        state["messages"].pop()
                    logger.log_print(
                        "The model returned an empty response with no tool call. "
                        "Nothing was added to the conversation; please retry."
                    )
                    if menu_expansion_task:
                        planning_pause = 'Candidate-menu expansion did not produce an audited candidate; the approved requirements remain unchanged.'
                        attempt = _candidate_menu_expansion_attempt(menu_expansion_task)
                        state['messages'].append(_message('assistant', content=planning_pause,
                            **({'candidateMenuExpansionAttempt': attempt} if attempt else {})))
                        persist_current()
                    break

                if menu_expansion_task and not has_tool_calls:
                    planning_pause = 'Candidate-menu expansion did not produce an audited candidate; the approved requirements remain unchanged.'

                assistant_message: Dict[str, Any] = _message("assistant")
                if menu_expansion_task and not has_tool_calls:
                    attempt = _candidate_menu_expansion_attempt(menu_expansion_task)
                    if attempt:
                        assistant_message['candidateMenuExpansionAttempt'] = attempt
                if reasoning_content is not None:
                    assistant_message["reasoning_content"] = reasoning_content
                if has_content:
                    assistant_message["content"] = content
                if has_tool_calls:
                    assistant_message["tool_calls"] = [
                        {
                            "id": tool_call.id,
                            "type": tool_call.type,
                            "function": {
                                "name": tool_call.function.name,
                                "arguments": tool_call.function.arguments,
                            },
                        }
                        for tool_call in tool_calls
                    ]
                    if saved_reaudit:
                        assistant_message['_internalAuditActions'] = {
                            call.id: saved_reaudit_action for call in tool_calls
                            if call.function.name == 'audit_workout_plan'}
                state["messages"].append(assistant_message)

                pending_audit = _latest_result(state['messages'], 'audit_workout_plan')[1]
                proposing = any(call.function.name in ('audit_workout_plan', 'allocate_workout_sets', 'record_planning_decisions') for call in (tool_calls or []))
                if has_content and (proposing or pending_audit.get('passed') is False):
                    assistant_message['unvalidatedProposal'] = True
                if has_content and not proposing:
                    if assistant_message.get('unvalidatedProposal'):
                        logger.log_print('Draft discussion — prescriptions and repairs below have not passed validation.')
                    print_markdown(content, logger)
                persist_current()

                if has_tool_calls:
                    pending_preview = None
                    batch_blocked = None
                    search_calls = []
                    for call in tool_calls:
                        if (call.function.name == "search_exercise_library" and call.function.name not in blocked_discovery
                                and not construction_tool_failure(call.function.name, {}, planning_state)):
                            try:
                                arguments = json.loads(call.function.arguments)
                                queries = arguments.get("queries")
                                if isinstance(queries, list) and 1 <= len(queries) <= 6 and all(isinstance(q, str) and 0 < len(q.strip()) <= 200 for q in queries):
                                    search_calls.append((call.id, arguments))
                            except (ValueError, AttributeError):
                                pass
                    grouped_searches = {}
                    lookup_messages = {}

                    def prepare_lookup_messages(call_ids):
                        for call in tool_calls:
                            if call.id in call_ids:
                                message = _message('tool', tool_call_id=call.id,
                                    content='Tool call started but did not complete. Treat this as a failed tool result if execution is interrupted.')
                                lookup_messages[call.id] = message
                                state['messages'].append(message)
                        persist_current()

                    def checkpoint_lookup(call_id, payload):
                        message = lookup_messages[call_id]
                        message.update(content=json.dumps(payload, ensure_ascii=False), timestamp=_timestamp_now())
                        persist_current()

                    if len(search_calls) > 1 and all(call.function.name == 'search_exercise_library'
                                                     for call in tool_calls[:len(search_calls)]):
                        prepare_lookup_messages({key for key, _ in search_calls})
                        started = time.monotonic()
                        logger.log(f"Combined library search started: {len(search_calls)} calls")
                        logger.log_request("combined library queries", json.dumps(search_calls))
                        try:
                            require_approved_requirements(state['messages'])
                            with LoadingIndicator("Searching exercise library (combined queries)") as search_loading:
                                with api_metrics_scope(logger, 'search_exercise_library'):
                                    grouped_searches = execute_library_searches(search_calls, provided_equipment, client, state["messages"],
                                        progress=lambda done, total: search_loading.update(f"Exercise search: {done}/{total} batches, up to 3 workers"),
                                        on_result=checkpoint_lookup)
                        except Exception as search_error:
                            grouped_searches = {call_id: (planning_tool_failure('search_exercise_library', search_error) if isinstance(search_error, PlanningInputError) else {
                                'passed': False, 'errors': [{'code': 'library_search_failed', 'message': str(search_error)}],
                                'instruction': 'Report the failed lookup. Do not automatically repeat it, invent matches, or change workout requirements to hide the failure.',
                            }) for call_id, _ in search_calls}
                        finally:
                            logger.log(f"Combined library search finished ({time.monotonic() - started:.2f}s)")
                        logger.log_print(f"Exercise search finished ({len(search_calls)} grouped calls, {time.monotonic() - started:.1f}s).")
                    elif (len(tool_calls) > 1 and requirements_approved(state['messages'])
                          and all(call.function.name in LOOKUP_TOOLS and call.function.name not in blocked_discovery
                                  and not construction_tool_failure(call.function.name, call.function.arguments, planning_state)
                                  for call in tool_calls)):
                        try:
                            independent = [(call.id, call.function.name, json.loads(call.function.arguments)) for call in tool_calls]
                        except (ValueError, TypeError):
                            independent = []
                        if independent:
                            prepare_lookup_messages({key for key, _, _ in independent})
                            batch_started = time.monotonic()
                            logger.log(f'Independent lookup batch started: {len(independent)} calls')
                            with LoadingIndicator(f'Retrieving {len(independent)} independent lookups'):
                                grouped_searches = execute_lookup_batch(independent, provided_equipment, client,
                                    state['messages'], training_history, logger, on_result=checkpoint_lookup)
                            logger.log_print(f'Independent lookups finished ({len(independent)} calls, {time.monotonic() - batch_started:.1f}s).')
                    for tool_call in tool_calls:
                        function_name = tool_call.function.name
                        argument_error = None
                        try:
                            function_args = json.loads(tool_call.function.arguments)
                        except json.JSONDecodeError as error:
                            function_args = {}
                            argument_error = error
                        logger.log_section("tool_call " + function_name)
                        logger.log_request("tool " + function_name, json.dumps(function_args, ensure_ascii=False))

                        completed_lookup = function_name in LOOKUP_TOOLS and tool_call.id in grouped_searches
                        if (planning_pause or batch_blocked) and not completed_lookup:
                            reason = planning_pause or batch_blocked
                            skipped = _message('tool', tool_call_id=tool_call.id, content=json.dumps({
                                'passed': False, 'skipped': True, 'tool': function_name,
                                'errors': [{'code': 'tool_batch_blocked', 'message': reason}],
                                'instruction': 'This tool was not executed. Resolve the preceding result before submitting dependent work again.'}))
                            if tool_call.id in lookup_messages:
                                lookup_messages[tool_call.id].update(skipped)
                            else:
                                state['messages'].append(skipped)
                            logger.log_print(f'Skipped {function_name}: a preceding step needs attention.')
                            persist_current()
                            continue

                        tool_message = lookup_messages.get(tool_call.id)
                        if tool_message is None:
                            tool_message = _message(
                                "tool", tool_call_id=tool_call.id,
                                content="Tool call started but did not complete. Treat this as a failed tool result if execution is interrupted.",
                            )
                            state["messages"].append(tool_message)

                        loading_label = {
                            'set_workout_requirements': 'Resolving workout requirements',
                            'record_planning_decisions': 'Checking planning choices',
                            "search_exercise_library": "Searching exercise library",
                            "audit_workout_plan": "Auditing workout volume and duration",
                            'get_training_evidence': 'Retrieving training evidence',
                            'get_exercise_candidates': 'Retrieving exercise details',
                            'prepare_workout_session': 'Preparing next session',
                            'prepare_workout_sessions': 'Preparing shared weekly allocation',
                            'draft_workout_sessions': 'Drafting sessions in parallel',
                            'allocate_workout_sets': 'Allocating workout sets',
                        }.get(function_name)
                        loading = LoadingIndicator(loading_label) if loading_label and tool_call.id not in grouped_searches else None
                        if loading:
                            loading.start()
                        tool_started = time.monotonic()
                        latest_tool_checkpoint = None
                        coordinated_edit_submission = None
                        coordinated_repair_task = None
                        coordinated_repair_context = None
                        coordinated_base_draft = None
                        coordinated_qualification_required = False
                        coordinated_baseline_audit = copy.deepcopy(planning_state.get('lastAudit') or {})
                        try:
                            if isinstance(function_args, dict) and '_internalAuditAction' in function_args:
                                raise PlanningInputError('invalid_internal_audit_marker',
                                    'Internal audit markers are reserved for code-owned actions.', '/',
                                    'Remove the internal audit marker and submit a regular repair through the typed edit contract.')
                            if argument_error:
                                raise PlanningInputError('invalid_tool_json',
                                    f'Tool arguments are invalid JSON: {argument_error.msg} at character {argument_error.pos}.', '/',
                                    'Return one complete valid JSON object matching the tool schema. Preserve the intended fields; no arguments were executed.')
                            if construction_task and function_name == 'audit_workout_plan' and not saved_reaudit and not parallel_submission:
                                from .planning_tools import validate_construction_submission
                                validate_construction_submission(function_args, construction_task)
                            if (function_name == 'record_planning_decisions' and planning_state.get('requirementsApproved')
                                    and not planning_state.get('planningDecisionNeeded') and not planning_state.get('newInstructionPending')):
                                raise PlanningInputError('planning_decision_not_needed', 'No pending user authorization or requirement interpretation needs recording.', '/',
                                    'Apply ordinary exercise substitutions and prescriptions through a draft patch and audit. Ask about genuine new ambiguity instead of inventing a requirement decision.')
                            active_draft_edit_task = repair_task or planning_state.get('editTask')
                            if active_draft_edit_task and function_name == 'audit_workout_plan' and not saved_reaudit:
                                if not isinstance(function_args, dict) or 'edits' not in function_args:
                                    raise PlanningInputError('repair_edit_contract_required',
                                        'A saved-draft edit requires the current typed edit contract.', '/edits',
                                        'Submit stable WORKOUT_n and EXERCISE_n edits. For metadata-only repairs, change only explicitly permitted metadata fields. Do not send raw JSON Patch.')
                            if active_draft_edit_task and function_name == 'audit_workout_plan' and not saved_reaudit:
                                current_repair_draft, _ = latest_draft_submission(state['messages'], provided_equipment)
                                if isinstance(function_args, dict) and 'edits' in function_args:
                                    coordinated_edit_submission = copy.deepcopy(function_args)
                                    coordinated_edit_submission['attemptedEdits'] = copy.deepcopy(function_args.get('edits'))
                                    coordinated_qualification_required = _repair_requires_coordinated_qualification(
                                        function_args['edits'], current_repair_draft)
                                    coordinated_repair_task = copy.deepcopy(active_draft_edit_task)
                                    coordinated_repair_task['requirementsId'] = planning_state.get('requirementsId')
                                    coordinated_repair_task['baseDraftId'] = planning_state.get('currentDraftId')
                                    coordinated_base_draft = copy.deepcopy(current_repair_draft)
                                admission_task = {**active_draft_edit_task,
                                    'requirementsId': planning_state.get('requirementsId'),
                                    'baseDraftId': planning_state.get('currentDraftId')}
                                function_args, coordinated_repair_context = _admit_repair_scope(
                                    function_args, admission_task, current_repair_draft, state['messages'],
                                    repair_attempt_start_index, args.max_repair_rounds, provided_equipment,
                                    return_context=True, submission_context=coordinated_edit_submission)
                            discovery_failure = (construction_tool_failure(function_name, function_args, planning_state)
                                                 or discovery_tool_failure(function_name, planning_state)) if not saved_reaudit else None
                            if discovery_failure:
                                function_result = {'result': json.dumps(discovery_failure), 'should_exit': False, 'generation_result': None}
                            elif function_name == 'draft_workout_sessions':
                                def checkpoint_sessions(payload):
                                    tool_message['content'] = json.dumps(payload, ensure_ascii=False)
                                    persist_current()
                                payload = draft_workout_sessions(client, function_args, state['messages'], provided_equipment,
                                    {**planning_state, 'historyFingerprint': training_history.fingerprint if training_history else None},
                                    logger=logger, progress=(lambda text: loading.update(text)) if loading else None,
                                    checkpoint=checkpoint_sessions, training_history=training_history)
                                function_result = {'result': json.dumps(payload, ensure_ascii=False),
                                                   'should_exit': False, 'generation_result': None}
                            elif tool_call.id in grouped_searches:
                                function_result = {"result": json.dumps(grouped_searches[tool_call.id]), "should_exit": False, "generation_result": None}
                            else:
                                def checkpoint_review(payload):
                                    nonlocal latest_tool_checkpoint
                                    latest_tool_checkpoint = copy.deepcopy(payload)
                                    tool_message.update(content=json.dumps(payload, ensure_ascii=False), timestamp=_timestamp_now())
                                    persist_current()
                                with api_metrics_scope(logger, function_name):
                                    function_result = handle_function_call_dep(
                                        client,
                                        state["messages"],
                                        function_name,
                                        function_args,
                                        provided_equipment,
                                        logger,
                                        script_dir,
                                        force_use_reasoner=force_use_reasoner,
                                        allow_educated_load_guesses=args.allow_educated_load_guesses,
                                        training_history=training_history,
                                        progress=((lambda done, total: loading.update(f"Exercise search: {done}/{total} batches, up to 3 workers"))
                                                  if function_name == 'search_exercise_library' else (lambda stage: loading.update(stage))) if loading else None,
                                        **({'checkpoint': checkpoint_review} if function_name == 'audit_workout_plan' else {}),
                                        **({'coordinated_repair': coordinated_repair_context}
                                           if function_name == 'audit_workout_plan'
                                           and coordinated_qualification_required else {}),
                                        **({'alternative_repair_task': alternative_repair_task}
                                           if function_name == 'repair_workout_alternative' else {}),
                                    )
                        except Exception as tool_error:
                            failure = planning_tool_failure(function_name, tool_error, function_args)
                            if function_name == 'repair_workout_alternative' and isinstance(alternative_repair_task, dict):
                                failure.update(outcome='unresolved', attemptStatus='repair_failed',
                                    repairCandidateId=alternative_repair_task.get('repairCandidateId'),
                                    originalRequirementsId=alternative_repair_task.get('originalRequirementsId'),
                                    candidateSnapshot=copy.deepcopy(alternative_repair_task),
                                    reason='The bounded alternative repair failed; the exact candidate and review evidence remain saved. No alternative was approved or declared impossible.')
                            if coordinated_edit_submission is not None:
                                if not coordinated_edit_submission.get('proposalCompiled'):
                                    previous = ((coordinated_repair_task or {}).get('rejectedCoordinatedRepair') or {}).get('submittedEdits')
                                    coordinated_edit_submission['submittedEdits'] = copy.deepcopy(
                                        previous if isinstance(previous, dict) else coordinated_edit_submission.get('attemptedEdits', {}))
                                receipt = {
                                    'status': 'rejected_before_materialization',
                                    'baseDraftId': coordinated_edit_submission.get('baseDraftId'),
                                    'currentDraftId': coordinated_edit_submission.get('baseDraftId'),
                                    'requirementsId': coordinated_edit_submission.get('requirementsId'),
                                    'submittedEdits': copy.deepcopy(coordinated_edit_submission.get('submittedEdits', coordinated_edit_submission.get('edits'))),
                                    'findingsAssessment': copy.deepcopy((coordinated_repair_task or {}).get('findingsAssessment')),
                                    'reviewFindings': copy.deepcopy((coordinated_repair_task or {}).get('reviewFindings', [])),
                                    **_coordinated_repair_receipt_context(coordinated_repair_task, coordinated_baseline_audit),
                                }
                                if coordinated_edit_submission.get('attemptedEdits') != receipt['submittedEdits']:
                                    receipt['rejectedAttemptEdits'] = copy.deepcopy(coordinated_edit_submission.get('attemptedEdits'))
                                if coordinated_edit_submission.get('replacedSubmittedEdits') is not None:
                                    receipt['replacedSubmittedEdits'] = copy.deepcopy(coordinated_edit_submission['replacedSubmittedEdits'])
                                failure['coordinatedRepairReceipt'] = receipt
                                failure['findingsAssessment'] = copy.deepcopy(receipt['findingsAssessment'])
                                failure['reviewFindings'] = copy.deepcopy(receipt['reviewFindings'])
                                failure['requirementsId'] = receipt['requirementsId']
                                failure['currentDraftId'] = receipt['currentDraftId']
                                if coordinated_base_draft is not None:
                                    failure['currentDraft'] = copy.deepcopy(coordinated_base_draft)
                            if latest_tool_checkpoint is not None:
                                failure = _merge_completed_tool_checkpoint(failure, latest_tool_checkpoint)
                            function_result = {
                                "result": json.dumps(failure, ensure_ascii=False),
                                "should_exit": False,
                                "generation_result": None,
                            }
                        finally:
                            if loading:
                                loading.stop()
                            logger.log(f"Tool {function_name} finished ({time.monotonic() - tool_started:.2f}s)")

                        if training_history and function_name == 'search_exercise_library':
                            payload = json.loads(function_result.get('result', '{}'))
                            if 'results' in payload:
                                function_result['result'] = json.dumps(training_history.annotate_search(payload, provided_equipment))
                        if function_name == 'audit_workout_plan' and menu_expansion_task and function_result.get('result'):
                            try:
                                payload = json.loads(function_result['result'])
                            except (ValueError, TypeError):
                                payload = None
                            if isinstance(payload, dict):
                                marker = _candidate_menu_expansion_audit_marker(
                                    menu_expansion_task, payload, function_args)
                                if marker:
                                    payload['candidateMenuExpansion'] = marker
                                    function_result['result'] = json.dumps(payload, ensure_ascii=False)
                        if coordinated_edit_submission is not None and function_result.get('result'):
                            try:
                                payload = json.loads(function_result['result'])
                            except (ValueError, TypeError):
                                payload = None
                            if isinstance(payload, dict) and payload.get('passed') is False:
                                base_id = coordinated_edit_submission.get('baseDraftId')
                                submitted = payload.get('submittedDraft')
                                changed_candidate = (isinstance(submitted, dict) and coordinated_base_draft is not None
                                                     and submitted != coordinated_base_draft)
                                status = ('attempted_pending_validation'
                                          if payload.get('currentDraftId') != base_id or changed_candidate
                                          else 'rejected_before_materialization')
                                receipt = {
                                    'status': status,
                                    'baseDraftId': base_id,
                                    'currentDraftId': payload.get('currentDraftId', base_id),
                                    'requirementsId': coordinated_edit_submission.get('requirementsId'),
                                    'submittedEdits': copy.deepcopy(coordinated_edit_submission.get('submittedEdits', coordinated_edit_submission.get('edits'))),
                                    'findingsAssessment': copy.deepcopy((coordinated_repair_task or {}).get('findingsAssessment')),
                                    'reviewFindings': copy.deepcopy((coordinated_repair_task or {}).get('reviewFindings', [])),
                                    **_coordinated_repair_receipt_context(coordinated_repair_task, coordinated_baseline_audit),
                                }
                                if coordinated_edit_submission.get('attemptedEdits') != receipt['submittedEdits']:
                                    receipt['rejectedAttemptEdits'] = copy.deepcopy(coordinated_edit_submission.get('attemptedEdits'))
                                if coordinated_edit_submission.get('replacedSubmittedEdits') is not None:
                                    receipt['replacedSubmittedEdits'] = copy.deepcopy(coordinated_edit_submission['replacedSubmittedEdits'])
                                payload['coordinatedRepairReceipt'] = receipt
                                payload.setdefault('findingsAssessment', copy.deepcopy(receipt['findingsAssessment']))
                                payload.setdefault('reviewFindings', copy.deepcopy(receipt['reviewFindings']))
                                function_result['result'] = json.dumps(payload, ensure_ascii=False)
                        if loading:
                            payload = json.loads(function_result.get('result', '{}'))
                            needs_attention = payload.get('passed') is False or payload.get('errors') or any(item.get('error') for item in payload.get('results', []))
                            stage = {'set_workout_requirements': 'Requirements', 'record_planning_decisions': 'Planning choices', 'search_exercise_library': 'Exercise search', 'get_training_evidence': 'Training history',
                                     'audit_workout_plan': 'Programming audit', 'get_exercise_candidates': 'Exercise details',
                                     'prepare_workout_session': 'Session preparation',
                                     'prepare_workout_sessions': 'Week preparation', 'draft_workout_sessions': 'Parallel drafting',
                                     'allocate_workout_sets': 'Set allocation'}[function_name]
                            logger.log_print(f"{stage}: {'needs attention' if needs_attention else 'complete'} ({time.monotonic() - tool_started:.1f}s).")
                            if function_name == 'audit_workout_plan' and payload.get('reviewPending'):
                                logger.log_print('Full execution review deferred until programming and evidence checks pass.')
                        logger.log_response("tool result " + function_name, function_result.get("result", ""), truncate_at=8000)
                        tool_result_text = function_result.get("result", "")
                        if tool_result_text and function_name == "generate_workout":
                            if function_result.get("continue_planning"):
                                logger.log_print("The current draft needs validation. Returning to planning before asking for fresh confirmation.")
                            elif (function_result.get("generation_result") or {}).get("requires_plan_revision"):
                                logger.log_print("The programming audit found issues. Returning them to the conversation to revise the plan before asking for confirmation again.")
                            else:
                                logger.log_print(tool_result_text)
                        tool_message["content"] = function_result["result"]
                        tool_message["timestamp"] = _timestamp_now()
                        persist_current()
                        if function_result.get('waiting_for_user'):
                            preview_ready = True
                            pending_preview = None
                            pending_user_question = json.loads(function_result['result'])['userQuestion']
                            batch_blocked = 'Waiting for the user to answer the displayed question.'
                        if function_result.get('decision_preview'):
                            print_markdown(function_result['decision_preview'], logger)
                        try:
                            feedback = json.loads(function_result['result'])
                        except (ValueError, TypeError):
                            feedback = {}
                        if isinstance(feedback, dict):
                            if (function_name in ('record_planning_decisions', 'set_workout_requirements', 'audit_workout_plan')
                                    and feedback.get('passed') is False) or function_result.get('requirements_pending'):
                                batch_blocked = f'{function_name} must be resolved before dependent work can run.'
                            failures = feedback.get('errors') or [item['error'] for item in feedback.get('results', []) if item.get('error')]
                            if not failures:
                                metadata_failures = 0
                            if failures:
                                if not planning_pause:
                                    planning_pause = _repair_cap_pause(failures)
                                unchanged_repair_task = (repair_task if function_name == 'audit_workout_plan'
                                    else alternative_repair_task if function_name == 'repair_workout_alternative' else None)
                                if (not planning_pause and unchanged_repair_task
                                        and feedback.get('passed') is False):
                                    planning_pause = _unchanged_repair_failure_pause(
                                        unchanged_repair_task, feedback, state['messages'], repair_attempt_start_index)
                                if (function_name == 'repair_workout_alternative'
                                        and feedback.get('attemptStatus') == 'joint_repair_unresolved'
                                        and not planning_pause):
                                    planning_pause = (feedback.get('reason') or
                                        'The bounded joint repair solve did not establish feasibility or infeasibility.')
                                joint_status = (feedback.get('coordinatedJointPlanning') or feedback.get('automaticAllocation') or {}).get('status')
                                if feedback.get('jointPlanningStopped') and joint_status != 'infeasible' and not planning_pause:
                                    planning_pause = feedback.get('instruction', 'Joint planning stopped; the draft is preserved.')
                                if function_name == 'audit_workout_plan' and joint_status == 'unproven' and not planning_pause:
                                    planning_pause = (feedback.get('instruction') or
                                        'Joint feasibility remains unresolved. The candidate is saved; use /continue to retry the unfinished solve.')
                                if feedback.get('executionFailure') and not feedback.get('jointConflictCandidate') and function_name == 'draft_workout_sessions' and not planning_pause:
                                    planning_pause = feedback.get('instruction', 'Joint planning stopped; completed recipes are saved.')
                                review_failure = next((error for error in failures if isinstance(error, dict)
                                    and error.get('code') in ('review_execution_failed', 'requirements_review_failed', 'decision_review_failed')), None)
                                if review_failure and not planning_pause:
                                    review_stage = {'review_execution_failed': 'Independent review',
                                                    'requirements_review_failed': 'Requirements review',
                                                    'decision_review_failed': 'Planning choice review'}[review_failure['code']]
                                    planning_pause = review_stage + ' failed: ' + review_failure.get('message', review_failure['code'])
                                execution_failure = next((error for error in failures if isinstance(error, dict)
                                    and error.get('code') == 'tool_execution_failed'), None)
                                if execution_failure and not planning_pause:
                                    planning_pause = function_name + ' failed internally: ' + execution_failure.get('message', 'Tool execution failed.')
                                if feedback.get('validationFailure') and not planning_pause:
                                    planning_pause = 'Session validation repair needs another attempt; completed sessions and unfinished proposals are saved.'
                                signature = planning_failure_signature(function_name, function_args, feedback, state['messages'])
                                metadata_failures = metadata_failures + 1 if all(is_metadata_error(error) for error in failures) else 0
                                if metadata_failures >= 3 and not planning_pause:
                                    planning_pause = 'Text repair failed three times; the rejected proposal and validation feedback are saved.'
                                discovery_blocked = any(isinstance(error, dict) and error.get('code') == 'discovery_complete' for error in failures)
                                if discovery_blocked:
                                    audit_index, _ = _latest_result(state['messages'], 'audit_workout_plan')
                                    signature = json.dumps([function_name, 'discovery_complete', audit_index])
                                    tools = [tool for tool in tools if tool.get('function', {}).get('name') != 'search_exercise_library']
                                    logger.log('Search unavailable until the draft is revised and audited; rephrasing cannot reopen discovery.')
                                if signature in failed_tool_signatures and not planning_pause:
                                    planning_pause = ('Search is still blocked for the same draft; rewording queries made no progress.' if discovery_blocked
                                                      else 'The same tool request failed again without a change.')
                                failed_tool_signatures.add(signature)
                        if function_result.get("continue_planning"):
                            requires_plan_revision = True
                            tools = [search_tool, GET_EXERCISE_CANDIDATES_TOOL, requirements_tool,
                                     RECORD_PLANNING_DECISIONS_TOOL, AUDIT_WORKOUT_PLAN_TOOL, ALLOCATE_WORKOUT_SETS_TOOL, GET_WORKOUT_DRAFT_TOOL, PROPOSE_WORKOUT_ALTERNATIVES_TOOL, ACCEPT_WORKOUT_ALTERNATIVE_TOOL] if exercise_definitions else []
                            if training_history:
                                tools.append(GET_TRAINING_EVIDENCE_TOOL)

                        if function_result.get("requirements_preview"):
                            state['messages'].append(_message('assistant', content=function_result['requirements_preview'],
                                canonicalRequirementsPreview=function_result['requirements_id']))
                            print_markdown(function_result["requirements_preview"], logger)
                            persist_current()
                        if function_result.get('alternative_previews'):
                            for proposal in function_result['alternative_previews']:
                                state['messages'].append(_message('assistant', content=proposal['text'], canonicalAlternativePreview=proposal['id']))
                                print_markdown(proposal['text'], logger)
                            persist_current()
                            preview_ready = True
                        if function_result.get('requirements_pending'):
                            tools = [requirements_tool, RECORD_PLANNING_DECISIONS_TOOL]
                            preview_ready = True
                        if function_name == "audit_workout_plan":
                            pending_preview = function_result if function_result.get("draft_preview") else None
                            if pending_preview and saved_reaudit and planning_state.get('pendingPreviewFollowup'):
                                pending_preview = None
                                logger.log_print('Review refreshed; returning to your pending request before showing a new preview.')
                            feedback = json.loads(function_result['result'])
                            errors = feedback.get('errors', [])
                            lookup_needed = errors and all(error.get('code') == 'training_evidence_required' for error in errors)
                            if feedback.get('passed') is False and not lookup_needed:
                                signature = planning_failure_signature(function_name, function_args, feedback, state['messages'])
                                if signature in failed_draft_signatures:
                                    planning_pause = 'The same unchanged draft failed again.'
                                failed_draft_signatures.add(signature)
                                if requirements_approved(state['messages']) and search_tool not in tools:
                                    tools.append(search_tool)

                        generation_result = function_result.get("generation_result")
                        if generation_result is not None:
                            if generation_result.get("requires_plan_revision"):
                                requires_plan_revision = True
                                tools = [search_tool, GET_EXERCISE_CANDIDATES_TOOL, requirements_tool,
                                         RECORD_PLANNING_DECISIONS_TOOL, AUDIT_WORKOUT_PLAN_TOOL, ALLOCATE_WORKOUT_SETS_TOOL, GET_WORKOUT_DRAFT_TOOL, PROPOSE_WORKOUT_ALTERNATIVES_TOOL, ACCEPT_WORKOUT_ALTERNATIVE_TOOL] if exercise_definitions else []
                                if training_history:
                                    tools.append(GET_TRAINING_EVIDENCE_TOOL)
                            current_record = load_conversation_record(state["conversation_id"], script_dir) or {}
                            generation_metadata = _metadata_for_generation_result(
                                generation_result,
                                state["log_path"],
                                current_record.get("metadata", {}).get("generated_output_paths"),
                            )
                    if pending_user_question:
                        state['messages'].append(_message('assistant', content=format_question(pending_user_question)))
                        persist_current()
                    if pending_preview:
                        preview = pending_preview["draft_preview"]
                        state["messages"].append(_message("assistant", content=preview,
                            canonicalDraftPreview=pending_preview["draft_id"]))
                        print_markdown(preview, logger)
                        persist_current()
                        preview_ready = True
                if planning_pause or preview_ready or not has_tool_calls or (not requires_plan_revision and any(call.function.name == "generate_workout" for call in tool_calls)):
                    break
                tool_round += 1
                if tool_round >= 40:
                    planning_pause = 'Planning reached its 40-round work budget; completed work and pending repairs are saved.'
                    break

            if planning_pause:
                logger.log_print(f"Planning paused: {planning_pause} Draft, lookups and audit feedback are saved. Type /continue to resume; you do not need to rewrite your requirements. Generation still requires a passing preview and fresh CONFIRM GENERATE.")

            persist_current(generation_metadata)
            if generation_metadata or planning_pause:
                report_usage(logger)

        except KeyboardInterrupt:
            logger.log_print("\nCancelled. Returning to prompt...")
            for message in state["messages"]:
                if message.get("role") == "tool" and str(message.get("content", "")).startswith("Tool call started"):
                    message["content"] = "Tool execution cancelled by the user. Do not treat this as a successful result."
            state["messages"] = normalize_conversation_messages(state["messages"])
            persist_current()
            report_usage(logger)
            continue
        except Exception as e:
            logger.log_print(f"Error: {e}")
            state["messages"] = normalize_conversation_messages(state["messages"])
            persist_current()
            report_usage(logger)
