"""Source-backed planning choices stored in the existing conversation tool results."""
import copy
import json

from jsonschema import validate

from .planning_tools import PlanningInputError, requirement_sources, source_message_context, _fingerprint, _latest_result


RECORD_PLANNING_DECISIONS_TOOL = {'type': 'function', 'function': {
    'name': 'record_planning_decisions',
    'description': 'Record a user decision or delegated interpretation of requirements. Ordinary exercise substitutions, load calibration and prescriptions within approved requirements belong in audit_workout_plan, not this tool. Cite SOURCE_n references from sourceMessages. This does not change numerical goals or restrictions. Reuse existing DECISION_n records instead of asking again. To replace a settled choice, supply supersedes and a concrete reason backed by the user instructions or a newly found conflict. Python checks authorization before saving the choices.',
    'parameters': {'type': 'object', 'properties': {
        'decisions': {'type': 'array', 'minItems': 1, 'items': {
            'type': 'object', 'properties': {
                'topic': {'type': 'string', 'minLength': 1, 'maxLength': 200},
                'choice': {'type': 'string', 'minLength': 1, 'maxLength': 1200},
                'sourceReferences': {'type': 'array', 'minItems': 1, 'uniqueItems': True,
                                     'items': {'type': 'string', 'pattern': '^SOURCE_[0-9]+$'}},
                'supersedes': {'type': ['string', 'null'], 'pattern': '^DECISION_[0-9]+$'},
                'reason': {'type': 'string', 'minLength': 1, 'maxLength': 1200},
            }, 'required': ['topic', 'choice', 'sourceReferences'], 'additionalProperties': False}}},
        'required': ['decisions'], 'additionalProperties': False}}}


def latest_decision_receipt(messages):
    calls = {call['id']: call['function']['name'] for m in messages for call in m.get('tool_calls', [])
             if call['function']['name'] in ('record_planning_decisions', 'set_workout_requirements')}
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if message.get('role') != 'tool' or message.get('tool_call_id') not in calls:
            continue
        try:
            payload = json.loads(message.get('content') or '{}')
        except (ValueError, TypeError):
            continue
        if not isinstance(payload, dict) or not payload.get('passed'):
            continue
        if calls[message['tool_call_id']] == 'record_planning_decisions':
            if payload.get('decisionReview', {}).get('passed'):
                return index, copy.deepcopy(payload)
        elif (payload.get('sourceReview', {}).get('passed')
              and payload.get('jointDecisionReview', {}).get('passed')):
            return index, copy.deepcopy(payload)
    return -1, {}


def saved_decisions(messages):
    return latest_decision_receipt(messages)[1].get('decisions', {})


def resolved_decisions(messages):
    return {key: value for key, value in saved_decisions(messages).items() if not value.get('supersededBy')}


def propose_decisions(arguments, messages):
    validate(arguments, RECORD_PLANNING_DECISIONS_TOOL['function']['parameters'])
    sources = source_message_context(requirement_sources(messages))
    source_hash = _fingerprint([{key: source[key] for key in ('content', 'images') if key in source} if source.get('images') else source['content']
                                for source in sources.values() if source['role'] == 'user'])
    decisions = saved_decisions(messages)
    proposed = []
    for item in arguments['decisions']:
        refs = item['sourceReferences']
        if any(ref not in sources for ref in refs) or not any(sources[ref]['role'] == 'user' for ref in refs):
            raise PlanningInputError('invalid_decision_source', 'A choice must cite existing source references including a user statement.',
                '/decisions', 'Copy actual SOURCE_n references. Cite the user choice or delegation, with its question if needed; do not invent authorization.')
        active = {key: value for key, value in decisions.items() if not value.get('supersededBy')}
        same = next((key for key, value in active.items() if value['topic'].strip().casefold() == item['topic'].strip().casefold()), None)
        normalize = lambda text: ' '.join(text.split()).casefold()
        identical = next((key for key, value in active.items()
                          if normalize(value['choice']) == normalize(item['choice'])
                          and set(value['sourceReferences']) == set(refs)
                          and (normalize(value['topic']) == normalize(item['topic']) or item.get('supersedes') == key)
                          and item.get('supersedes') in (None, key)), None)
        if identical:
            same = identical
            if active[same].get('authorizationSourceHash') != source_hash:
                decisions[same]['authorizationSourceHash'] = source_hash
                proposed.append(same)
            continue
        previous = item.get('supersedes')
        if (same and previous != same) or (previous and (previous not in active or not item.get('reason'))):
            raise PlanningInputError('settled_decision', 'The existing choice cannot be silently replaced.', '/decisions',
                'Reuse the settled choice. To replace it, copy its DECISION_n into supersedes and explain the new instruction or concrete conflict in reason.')
        if previous and active[previous].get('authorizationSourceHash') == source_hash:
            decision_index, _ = latest_decision_receipt(messages)
            audit_index, audit = _latest_result(messages, 'audit_workout_plan')
            conflict = audit_index > decision_index and any(
                finding.get('decisionId') == previous and finding.get('action') == 'clarify'
                and finding.get('newConflictEvidencePaths')
                for finding in audit.get('review', {}).get('findings', []))
            if not conflict:
                raise PlanningInputError('decision_already_recorded', 'This choice already has current user authorization; no new reviewed conflict permits replacing it.', '/decisions',
                    f'Reuse {previous}. Refresh an audit that predates this decision, then repair the workout. A changed topic, paraphrase or stale review does not create new authorization.')
        identifier = f'DECISION_{len(decisions)}'
        decisions[identifier] = copy.deepcopy(item)
        decisions[identifier]['sourceCountAtResolution'] = len(sources)
        decisions[identifier]['authorizationSourceHash'] = source_hash
        if previous:
            decisions[previous]['supersededBy'] = identifier
        proposed.append(identifier)
    return {'decisions': decisions, 'newDecisionIds': proposed, 'sourceMessages': sources}


def render_decisions(decisions):
    return '\n'.join(f"- **{item['topic']}**: {item['choice']}" for item in decisions.values() if not item.get('supersededBy'))
