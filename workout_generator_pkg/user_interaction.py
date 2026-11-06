"""Structured terminal questions; approval actions stay owned by the backend."""

import copy
import json
import re

from jsonschema import ValidationError, validate

from .constants import EXACT_GENERATION_CONFIRMATION
from .planning_tools import REQUIREMENTS_CONFIRMATION, _latest_result, requirements_approved


ASK_USER_TOOL = {
    'type': 'function',
    'function': {
        'name': 'ask_user',
        'description': 'Ask one genuine clarification question and wait for the user. Supply concise choices when useful; free text is always accepted. When goals, constraints and available evidence support a preference, include recommendation with the option number and a short reason explaining its main tradeoff. Do not guess personal facts or recommend without evidence; explain uncertainty in the question when no preference is justified. Reuse existing answers and delegation: choose and disclose an authorized decision rather than asking again. Never recommend silently relaxing approved requirements. Use this instead of burying questions in prose. Do not request requirements or export approval: Python shows those questions after reviewed previews.',
        'parameters': {
            'type': 'object',
            'properties': {
                'question': {'type': 'string', 'minLength': 1, 'maxLength': 2000},
                'options': {'type': 'array', 'items': {'type': 'string', 'minLength': 1, 'maxLength': 500}, 'uniqueItems': True},
                'recommendation': {'type': 'object', 'properties': {
                    'option': {'type': 'integer', 'minimum': 1, 'description': 'One-based number of an option in options; no automatic selection.'},
                    'reason': {'type': 'string', 'minLength': 1, 'maxLength': 600},
                }, 'required': ['option', 'reason'], 'additionalProperties': False},
            },
            'required': ['question'], 'additionalProperties': False,
        },
    },
}


PROPOSE_WORKOUT_ALTERNATIVES_TOOL = {'type': 'function', 'function': {
    'name': 'propose_workout_alternatives',
    'description': 'Compare alternatives for a current allocation conflict or selected preferences. Python explores authorized numerical changes and separately reports non-exportable diagnostics of hypothetical priority orders over the verified recipe pool, or the selected menu when that pool is unavailable. The current plan, hard requirements and approved priority order remain active. Proposals require explicit approval; a comparison does not declare the baseline invalid.',
    'parameters': {'type': 'object', 'properties': {
        'requirementsId': {'type': 'string', 'minLength': 1},
        'baseDraftId': {'type': 'string', 'minLength': 1},
        'comparisonPriorities': {'type': 'array', 'minItems': 1, 'uniqueItems': True,
            'items': {'type': 'string', 'minLength': 1},
            'description': 'Select existing approved objectiveOrder names for diagnostic comparisons of their precedence. Python owns the scenario orders and quantities; diagnostics do not approve a policy change.'},
        'comparisonConcernIds': {'type': 'array', 'items': {'type': 'string', 'minLength': 1},
            'uniqueItems': True,
            'description': 'Optional current review concernGroupId values selected for preference comparison. Python accepts only source-backed, unresolved user preferences; omit when no specific reviewed preference should be compared.'},
        'workouts': {'type': 'array', 'minItems': 1, 'items': {'type': 'object'},
                     'description': 'Optional only when baseDraftId identifies the current saved audited draft; Python then loads its submitted workouts.'},
    }, 'required': ['requirementsId', 'baseDraftId'], 'additionalProperties': False},
}}

ACCEPT_WORKOUT_ALTERNATIVE_TOOL = {'type': 'function', 'function': {
    'name': 'accept_workout_alternative',
    'description': 'Apply an already displayed and independently validated alternative only after the user explicitly types APPROVE ALTERNATIVE <proposalId>. This creates a new requirements revision linked to the original; never accept by inference, numbered choice, model recommendation or tool call alone.',
    'parameters': {'type': 'object', 'properties': {
        'proposalId': {'type': 'string', 'minLength': 1},
    }, 'required': ['proposalId'], 'additionalProperties': False},
}}


def repair_workout_alternative_tool(task):
    """Build a one-candidate edit contract for an unapproved, saved alternative."""
    from .planning_tools import coordinated_repair_tool
    from .alternative_repair import _alternative_compiler_task

    task = _alternative_compiler_task(task)
    candidate_id = task['repairCandidateId']
    original_requirements_id = task['originalRequirementsId']
    tool = coordinated_repair_tool(task)
    parameters = tool['function']['parameters']
    properties = parameters['properties']
    properties.pop('requirementsId', None)
    properties.pop('baseDraftId', None)
    properties['repairCandidateId'] = {'type': 'string', 'enum': [candidate_id]}
    properties['originalRequirementsId'] = {'type': 'string', 'enum': [original_requirements_id]}
    parameters['required'] = ['repairCandidateId', 'originalRequirementsId', *[
        field for field in parameters['required'] if field not in ('requirementsId', 'baseDraftId')]]
    tool['function']['name'] = 'repair_workout_alternative'
    tool['function']['description'] = (
        'Repair the exact saved hypothetical workout alternative identified by repairCandidateId, using originalRequirementsId and every actionable addressedFindingIndexes. '
        'Submit one atomic repair using the structured fields in the supplied schema. '
        'The numerical relaxation is fixed and hypothetical; do not change it, any mandatory requirement, equipment, safety restriction, or the active workout draft. '
        'Python applies edits only to the saved alternative, re-runs its full numerical audit, then a fresh independent review. '
        'This does not approve the alternative. The user must separately approve its exact reviewed proposal ID. '
        + tool['function']['description'])
    return {'type': 'function', 'function': tool['function']}


def preference_comparison_priorities(audit, requirements, selected_priorities):
    """Select approved solver preferences without inventing a failure threshold."""
    if (not isinstance(selected_priorities, list) or not selected_priorities
            or any(not isinstance(name, str) for name in selected_priorities)
            or len(set(selected_priorities)) != len(selected_priorities)):
        raise ValueError('Select unique approved priority names for comparison.')
    approved = requirements.get('objectiveOrder') or []
    joint = audit.get('coordinatedJointPlanning') or audit.get('automaticAllocation') or {}
    rows = (joint.get('priorityExecution') or {}).get('approvedPriorities', [])
    evidence = {row.get('priority'): row for row in rows if isinstance(row, dict)}
    if any(name not in approved or name not in evidence for name in selected_priorities):
        raise ValueError('Preference comparisons require approved priorities with current execution evidence.')
    return [{'priority': name, 'execution': copy.deepcopy(evidence[name]),
             'approvedObjectiveOrder': list(approved), 'basis': 'requested_comparison'}
            for name in approved if name in selected_priorities]


def preference_comparison_concerns(audit, requirements, selected_ids=None, *, review_checklist=None):
    """Resolve explicit concern keys to current, source-backed soft preferences."""
    review = audit.get('review') if isinstance(audit, dict) else None
    assessment = review.get('assessment') if isinstance(review, dict) else None
    if not isinstance(review, dict) or not isinstance(assessment, dict):
        raise ValueError('A current semantic review is required to select preference comparisons.')

    checklist = review_checklist or (audit.get('reviewChecklist') if isinstance(audit, dict) else {}) or {}
    accepted = checklist.get('acceptedSoftTradeoffs', {}) if isinstance(checklist, dict) else {}
    accepted_ids = set(accepted) if isinstance(accepted, dict) else set()
    accounting = requirements.get('requirementAccounting', []) if isinstance(requirements, dict) else []
    preferences_by_source = {}
    for item in accounting:
        if not isinstance(item, dict) or item.get('priority') != 'preference':
            continue
        for source in item.get('sourceReferences', []):
            preferences_by_source.setdefault(source, []).append(item)

    source_assessments = review.get('requirementAssessments', {})
    findings = review.get('findings', [])
    eligible = []
    for group in assessment.get('groups', []):
        indexes = group.get('findingIndexes', [])
        if group.get('disposition') != 'advisory' or not indexes:
            continue
        group_findings = [findings[index] for index in indexes
            if type(index) is int and 0 <= index < len(findings)]
        if len(group_findings) != len(indexes) or any(
                finding.get('basis') not in ('uncertainty', 'soft_tradeoff')
                or finding.get('action') != 'advisory' or finding.get('decisionId')
                for finding in group_findings):
            continue
        concern_ids = {finding.get('concernGroupId') for finding in group_findings}
        if len(concern_ids) != 1:
            continue
        concern_id = next(iter(concern_ids))
        if not isinstance(concern_id, str) or not concern_id or concern_id in accepted_ids:
            continue

        cited_sources = set()
        for finding in group_findings:
            for path in finding.get('evidencePaths', []):
                match = re.match(r'^/sourceMessages/(SOURCE_[0-9]+)(?:/|$)', path)
                if match:
                    cited_sources.add(match.group(1))
        for source, check in source_assessments.items():
            if any(index in check.get('findingIndexes', []) for index in indexes):
                cited_sources.add(source)
        linked_preferences = [copy.deepcopy(item) for source in sorted(cited_sources)
            for item in preferences_by_source.get(source, [])]
        if not linked_preferences:
            continue
        eligible.append({'concernGroupId': concern_id, 'disposition': group['disposition'],
            'groupReason': group.get('reason', ''), 'findingIndexes': list(indexes),
            'findings': [copy.deepcopy(finding) for finding in group_findings],
            'preferenceRequirements': linked_preferences})

    if selected_ids is None:
        return eligible
    if (not isinstance(selected_ids, list) or not selected_ids
            or any(not isinstance(identifier, str) or not identifier for identifier in selected_ids)
            or len(selected_ids) != len(set(selected_ids))):
        raise ValueError('Select one or more unique reviewed preference concern IDs.')
    by_id = {entry['concernGroupId']: entry for entry in eligible}
    if any(identifier not in by_id for identifier in selected_ids):
        raise ValueError('A selected concern is not an unresolved, source-backed preference in the current review.')
    return [by_id[identifier] for identifier in selected_ids]


def clarification_question(arguments):
    validate(arguments, ASK_USER_TOOL['function']['parameters'])
    if not arguments['question'].strip() or any(not option.strip() for option in arguments.get('options', [])):
        raise ValueError('Questions and choices must contain text.')
    recommendation = arguments.get('recommendation')
    if recommendation and (recommendation['option'] > len(arguments.get('options', []))
                           or not recommendation['reason'].strip()):
        raise ValueError('Recommendations must name a listed option and explain why.')
    return {'kind': 'clarification', 'question': arguments['question'], 'options': arguments.get('options', []),
            **({'recommendation': recommendation} if recommendation else {})}


def pending_question(messages):
    """Only an unanswered, displayed question can interpret numbered choices."""
    closed_approvals = set()
    user_replied = False
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if message.get('role') == 'user':
            user_replied = True
            content = (message.get('content') or '').strip()
            if content == REQUIREMENTS_CONFIRMATION:
                closed_approvals.add('requirements')
            elif content == EXACT_GENERATION_CONFIRMATION:
                closed_approvals.add('generation')
            elif content.startswith('APPROVE ALTERNATIVE '):
                closed_approvals.add('alternative:' + content.removeprefix('APPROVE ALTERNATIVE ').strip())
            interaction = message.get('userInteraction') or {}
            if (interaction.get('input', '').strip().casefold() in ('2', 'no', 'cancel', 'revise requirements', 'revise workout')):
                answered = interaction.get('question', {})
                closed_approvals.add(answered.get('kind'))
                if answered.get('kind') == 'alternative':
                    closed_approvals.add('alternative:' + answered.get('reference', ''))
            continue
        if message.get('role') == 'assistant':
            if message.get('canonicalAlternativePreview'):
                proposal_id = message['canonicalAlternativePreview']
                if 'alternative:' + proposal_id not in closed_approvals:
                    from .conflict_resolution import render_alternative_preview
                    repair_index, repair_result = _latest_result(messages, 'repair_workout_alternative')
                    proposal_index, _ = _latest_result(messages, 'propose_workout_alternatives')
                    proposal = None
                    result_index = -1
                    if (repair_index > proposal_index and repair_result.get('outcome') == 'alternatives_ready'
                            and repair_result.get('repairStatus') == 'repaired_and_reviewed'
                            and repair_result.get('passed') is True):
                        candidate = repair_result.get('proposal')
                        _, source_requirements = _latest_result(messages, 'set_workout_requirements')
                        if (isinstance(candidate, dict) and candidate.get('proposalId') == proposal_id
                                and candidate.get('originalRequirementsId') == source_requirements.get('requirementsId')
                                and candidate.get('independentReview', {}).get('passed') is True):
                            proposal = candidate
                            result_index = repair_index
                    if proposal is None:
                        result_index, result = _latest_result(messages, 'propose_workout_alternatives')
                        proposal = next((item for item in result.get('proposals', [])
                                         if item.get('proposalId') == proposal_id), None)
                    try:
                        expected_preview = render_alternative_preview(proposal) if proposal else None
                    except (ValueError, KeyError, TypeError):
                        expected_preview = None
                    if (result_index < index and proposal
                            and message.get('content') == expected_preview):
                        return {'kind': 'alternative', 'question': 'Accept this reviewed workout alternative?',
                            'options': ['Approve this alternative', 'Keep the current requirements'],
                            'messageIndex': index, 'reference': proposal_id}
            for field, tool, kind, title, options in (
                ('canonicalRequirementsPreview', 'set_workout_requirements', 'requirements',
                 'Approve these requirements and start planning?', ['Approve requirements', 'Revise requirements']),
                ('canonicalDraftPreview', 'audit_workout_plan', 'generation',
                 'Generate the workout file from this reviewed plan?', ['Generate workout file', 'Revise workout']),
            ):
                if kind in closed_approvals or not message.get(field):
                    continue
                result_index, result = _latest_result(messages, tool)
                if kind == 'generation':
                    _, requirements = _latest_result(messages, 'set_workout_requirements')
                    if (result.get('requirementsId') != requirements.get('requirementsId')
                            or not requirements_approved(messages, requirements)):
                        continue
                    joint_receipt = result.get('coordinatedJointPlanning') or result.get('automaticAllocation') or {}
                    priority_execution = joint_receipt.get('priorityExecution') or {}
                    priorities = priority_execution.get('approvedPriorities', [])
                    development = priority_execution.get('developmentEmphasis') or {}
                    development_requested = bool(development.get('roleKeys'))
                    incomplete_priorities = any(entry.get('owner') == 'joint_solver'
                            and entry.get('status') in ('feasible', 'unproven', 'unavailable_evidence', 'not_run', 'not_run_after_solver_stop')
                            for entry in priorities)
                    incomplete_development = (development_requested
                        and development.get('status') not in ('optimal', 'optimal_zero_lower_bound'))
                    if incomplete_priorities or development_requested:
                        from .generation_audit import render_optimization_disclosure
                        disclosure = render_optimization_disclosure(priority_execution)
                        if disclosure:
                            title += '\n\n' + disclosure
                        if incomplete_priorities or incomplete_development:
                            options = ['Accept the disclosed priority limitations and generate', 'Revise workout']
                elif result.get('approvedAlternativeId') and requirements_approved(messages, result):
                    continue
                reference = result.get('requirementsId' if kind == 'requirements' else 'draftId')
                preview = result.get('requirementsPreview' if kind == 'requirements' else 'preview')
                if (result_index < index and message[field] == reference and message.get('content') == preview
                        and (result.get('passed') if kind == 'generation' else result.get('sourceReview', {}).get('passed'))):
                    return {'kind': kind, 'question': title, 'options': options, 'messageIndex': index, 'reference': reference}
        if message.get('role') == 'tool' and not user_replied:
            try:
                payload = json.loads(message.get('content', ''))
            except (ValueError, TypeError):
                continue
            if isinstance(payload, dict) and payload.get('userQuestion'):
                question = payload['userQuestion']
                try:
                    validated = clarification_question({key: question[key] for key in ('question', 'options', 'recommendation') if key in question})
                except (ValueError, KeyError, TypeError, ValidationError):
                    continue
                return {**validated, 'messageIndex': index,
                    **({'executionChoices': copy.deepcopy(question['executionChoices'])}
                       if question.get('executionChoices') else {}),
                    **({'programmingChoices': copy.deepcopy(payload['programmingDecisionChoices'])}
                       if payload.get('programmingDecisionChoices') else {})}
    return None


def answered_programming_decision(messages, equipment, history_fingerprint=None):
    """Compile an exact answer to the current code-owned artifact comparison."""
    from .planning_decisions import _current_programming_decision_choices
    from .planning_tools import library_fingerprint, requirement_sources

    user_index = max((index for index, message in enumerate(messages)
                      if message.get('role') == 'user'), default=-1)
    if user_index < 0:
        return None
    interaction = messages[user_index].get('userInteraction') or {}
    question = interaction.get('question') or {}
    if not question or question != pending_question(messages[:user_index]):
        return None
    result_index, _ = max((_latest_result(messages, name) for name in
        ('audit_workout_plan', 'draft_workout_sessions')), key=lambda item: item[0])
    result, choices = _current_programming_decision_choices(messages)
    if (result_index != question.get('messageIndex') or not choices
            or not requirements_approved(messages)
            or result.get('libraryFingerprint') != library_fingerprint(equipment)
            or result.get('historyFingerprint') != history_fingerprint
            or question.get('programmingChoices') != choices
            or question.get('options') != [choice['label'] for choice in choices.values()]):
        return None
    answer = interaction.get('input')
    if isinstance(answer, str) and answer.isdecimal():
        option = int(answer) - 1
        answer = question['options'][option] if 0 <= option < len(choices) else None
    selected = next(((identifier, choice) for identifier, choice in choices.items()
                     if answer == choice['label']), None)
    if selected is None or messages[user_index].get('content') != answer_question(question, interaction['input']):
        return None
    identifier, choice = selected
    references = [f'SOURCE_{index}' for index, source in enumerate(requirement_sources(messages))
                  if source['messageIndex'] == user_index]
    return {'decisions': [{'topic': 'Displayed programming choice', 'choice': choice['label'],
        'sourceReferences': references, 'acceptedConcernGroupId': identifier}]}


def answered_execution_decision(messages, equipment, history_fingerprint=None):
    """Compile only an explicit numbered answer to a current backend counting choice."""
    from .planning_tools import library_fingerprint, requirement_sources

    user_index = max((index for index, message in enumerate(messages)
                      if message.get('role') == 'user'), default=-1)
    if user_index < 0:
        return None
    interaction = messages[user_index].get('userInteraction') or {}
    question = interaction.get('question') or {}
    modes = {'One complete sequence; reps/time are total': 'single_sequence',
             'Repeat prescribed reps/time on each side or direction': 'paired_sides'}
    if (interaction.get('input') not in ('1', '2') or question.get('options') != list(modes)
            or question != pending_question(messages[:user_index])):
        return None
    choices = question.get('executionChoices') or []
    if not isinstance(choices, list) or not choices or any(not isinstance(choice, dict) for choice in choices):
        return None
    origin = messages[question['messageIndex']]
    function = next((call.get('function', {}).get('name') for message in messages[:question['messageIndex']]
                     for call in message.get('tool_calls', []) if call.get('id') == origin.get('tool_call_id')), None)
    if function not in ('prepare_workout_sessions', 'draft_workout_sessions', 'audit_workout_plan'):
        return None
    payload = json.loads(origin['content'])
    _, requirements = _latest_result(messages, 'set_workout_requirements')
    if (not requirements_approved(messages, requirements)
            or payload.get('requirementsId') != requirements.get('requirementsId')
            or payload.get('libraryFingerprint') != library_fingerprint(equipment)
            or payload.get('historyFingerprint') != history_fingerprint):
        return None
    definitions = sorted(equipment.get('exerciseDefinitions', []), key=lambda item: item['id'])
    by_reference = {f'LIBRARY_{index}': definition for index, definition in enumerate(definitions)}
    references = [choice.get('definition_id') for choice in choices]
    execution_errors = [error for error in payload.get('errors', [])
                        if error.get('code') == 'execution_semantics_unresolved']
    if (any(not isinstance(reference, str) for reference in references)
            or len(set(references)) != len(references)
            or set(references) != {error.get('definition_id') for error in execution_errors}):
        return None
    from .planning_decisions import _selection_ids_by_name
    names = {identity: name for name, identity in _selection_ids_by_name(definitions).items()}
    selected_names = []
    for choice in choices:
        definition = by_reference.get(choice['definition_id'])
        if (not definition or choice.get('canonicalDefinitionId') != definition['id']
                or definition['id'] not in names
                or any(error.get('canonicalDefinitionId', definition['id']) != definition['id']
                       for error in execution_errors if error.get('definition_id') == choice['definition_id'])):
            return None
        selected_names.append(names[definition['id']])
    if len(set(selected_names)) != len(selected_names):
        return None
    answer = question['options'][int(interaction['input']) - 1]
    sources = requirement_sources(messages)
    references = [f'SOURCE_{index}' for index, source in enumerate(sources)
                  if source['messageIndex'] == user_index or (source['role'] == 'assistant'
                      and question['messageIndex'] < source['messageIndex'] < user_index)]
    return {'decisions': [{'topic': name + ' rep/time counting', 'choice': answer,
        'sourceReferences': references,
        'executionPrescription': {'exercise': name, 'setMode': modes[answer]}}
        for name in selected_names]}


def execution_preparation_arguments(messages, equipment, history_fingerprint=None):
    """Reuse the exact menu whose counting-only answer passed independent review."""
    from .planning_tools import latest_draft_submission

    if answered_execution_decision(messages, equipment, history_fingerprint) is None:
        return None
    user = next(message for message in reversed(messages) if message.get('role') == 'user')
    gate_index = user['userInteraction']['question']['messageIndex']
    gate = json.loads(messages[gate_index]['content'])
    index, prepared = _latest_result(messages[:gate_index], 'prepare_workout_sessions')
    if (index < 0 or not gate.get('preparationId') or prepared.get('preparationId') != gate['preparationId']
            or prepared.get('requirementsId') != gate.get('requirementsId')
            or prepared.get('libraryFingerprint') != gate.get('libraryFingerprint')
            or prepared.get('historyFingerprint') != history_fingerprint
            or prepared.get('baseDraftId') != latest_draft_submission(messages, equipment)[1]
            or not prepared.get('setAllocation', {}).get('feasible') or prepared.get('errors')):
        return None
    call_id = messages[index].get('tool_call_id')
    function = next((call['function'] for message in messages[:index] for call in message.get('tool_calls', [])
                     if call.get('id') == call_id), None)
    try:
        arguments = copy.deepcopy(prepared.get('preparationArguments'))
        if arguments is None:
            arguments = json.loads(function.get('arguments', '{}')) if function else None
        if isinstance(arguments, dict) and ('patch' in arguments or 'sessionBlocks' in arguments):
            from .session_drafting import resolve_preparation_patch
            arguments = resolve_preparation_patch(arguments, messages[:index], equipment)
    except (ValueError, TypeError):
        return None
    if (not isinstance(arguments, dict) or arguments.get('requirementsId') != prepared['requirementsId']
            or arguments.get('baseDraftId') != prepared.get('baseDraftId')):
        return None
    return arguments


def answer_question(question, text):
    """Translate an explicit choice; Enter and commands never imply consent."""
    if text.startswith('/') or text.startswith('APPROVE ALTERNATIVE ') or text in (REQUIREMENTS_CONFIRMATION, EXACT_GENERATION_CONFIRMATION):
        return text
    answer = text
    if text.isdecimal() and question['options']:
        index = int(text) - 1
        if not 0 <= index < len(question['options']):
            raise ValueError('Choose a listed number or type your answer.')
        answer = question['options'][index]
        if index == 0 and question['kind'] in ('requirements', 'generation'):
            return REQUIREMENTS_CONFIRMATION if question['kind'] == 'requirements' else EXACT_GENERATION_CONFIRMATION
        if question['kind'] == 'alternative':
            if index == 0:
                return f"APPROVE ALTERNATIVE {question['reference']}"
            return 'Keep the current requirements; do not accept an alternative.'
        if question['kind'] in ('requirements', 'generation'):
            return 'I want to revise the ' + ('requirements' if question['kind'] == 'requirements' else 'workout') + '. Ask what I want changed before applying edits.'
    if question['kind'] == 'clarification':
        return f"My answer: {answer}"
    return answer
