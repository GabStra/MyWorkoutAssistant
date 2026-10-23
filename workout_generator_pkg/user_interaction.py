"""Structured terminal questions; approval actions stay owned by the backend."""

import json

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
    'description': 'After a current-bound joint allocation conflict, request validated alternatives within explicitly negotiable numerical bounds. Structural exercise-selection repair should be attempted first; if it remains unresolved, proposals are still useful but must be labeled as scoped to the supplied exercise menu, with exact original-target shortfalls and no global-best or impossibility claim. Preserve equipment, explicit safety restrictions, mandatory requirements and preferences. Never silently relax requirements. Supply all workout sessions and the current requirementsId/draftId. Proposals remain hypothetical until the user explicitly approves one.',
    'parameters': {'type': 'object', 'properties': {
        'requirementsId': {'type': 'string', 'minLength': 1},
        'baseDraftId': {'type': 'string', 'minLength': 1},
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
                return {**validated, 'messageIndex': index}
    return None


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
