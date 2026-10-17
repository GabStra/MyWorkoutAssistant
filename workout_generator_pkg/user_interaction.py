"""Structured terminal questions; approval actions stay owned by the backend."""

import json

from jsonschema import ValidationError, validate

from .constants import EXACT_GENERATION_CONFIRMATION
from .planning_tools import REQUIREMENTS_CONFIRMATION, _latest_result, requirements_approved


ASK_USER_TOOL = {
    'type': 'function',
    'function': {
        'name': 'ask_user',
        'description': 'Ask one genuine clarification question and wait for the user. Supply optional concise choices; free text is always accepted. Use this instead of burying questions in prose. Do not request requirements or export approval: Python shows those questions after reviewed previews.',
        'parameters': {
            'type': 'object',
            'properties': {
                'question': {'type': 'string', 'minLength': 1, 'maxLength': 2000},
                'options': {'type': 'array', 'items': {'type': 'string', 'minLength': 1, 'maxLength': 500}, 'uniqueItems': True},
            },
            'required': ['question'], 'additionalProperties': False,
        },
    },
}


def clarification_question(arguments):
    validate(arguments, ASK_USER_TOOL['function']['parameters'])
    if not arguments['question'].strip() or any(not option.strip() for option in arguments.get('options', [])):
        raise ValueError('Questions and choices must contain text.')
    return {'kind': 'clarification', 'question': arguments['question'], 'options': arguments.get('options', [])}


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
            interaction = message.get('userInteraction') or {}
            if (interaction.get('input', '').strip().casefold() in ('2', 'no', 'cancel', 'revise requirements', 'revise workout')):
                closed_approvals.add(interaction.get('question', {}).get('kind'))
            continue
        if message.get('role') == 'assistant':
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
                    validated = clarification_question({key: question[key] for key in ('question', 'options')})
                except (ValueError, KeyError, TypeError, ValidationError):
                    continue
                return {**validated, 'messageIndex': index}
    return None


def answer_question(question, text):
    """Translate an explicit choice; Enter and commands never imply consent."""
    if text.startswith('/') or text in (REQUIREMENTS_CONFIRMATION, EXACT_GENERATION_CONFIRMATION):
        return text
    answer = text
    if text.isdecimal() and question['options']:
        index = int(text) - 1
        if not 0 <= index < len(question['options']):
            raise ValueError('Choose a listed number or type your answer.')
        answer = question['options'][index]
        if index == 0 and question['kind'] in ('requirements', 'generation'):
            return REQUIREMENTS_CONFIRMATION if question['kind'] == 'requirements' else EXACT_GENERATION_CONFIRMATION
        if question['kind'] in ('requirements', 'generation'):
            return 'I want to revise the ' + ('requirements' if question['kind'] == 'requirements' else 'workout') + '. Ask what I want changed before applying edits.'
    if question['kind'] == 'clarification':
        return f"My answer: {answer}"
    return answer
