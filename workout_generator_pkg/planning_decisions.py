"""Source-backed planning choices stored in the existing conversation tool results."""
import copy
import json

from jsonschema import ValidationError, validate

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


def _current_reviewed_audit(messages):
    """Find the review receipt for the exact candidate still held by the latest audit attempt."""
    _, latest = _latest_result(messages, 'audit_workout_plan')
    current_draft = latest.get('currentDraft') or latest.get('submittedDraft')
    if not isinstance(current_draft, dict) or not isinstance(current_draft.get('workouts'), list):
        return -1, {}

    workout_fingerprint = _fingerprint(current_draft['workouts'])
    current_draft_id = latest.get('currentDraftId')
    requirements_id = latest.get('requirementsId')
    calls = {call.get('id'): call.get('function', {}).get('name')
             for message in messages for call in message.get('tool_calls', [])}
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if message.get('role') != 'tool' or calls.get(message.get('tool_call_id')) != 'audit_workout_plan':
            continue
        try:
            result = json.loads(message.get('content') or '{}')
        except (ValueError, TypeError):
            continue
        reviewed_draft = result.get('submittedDraft') if isinstance(result, dict) else None
        if (not isinstance(result, dict) or not isinstance(result.get('review'), dict)
                or not isinstance(reviewed_draft, dict)
                or not isinstance(reviewed_draft.get('workouts'), list)
                or _fingerprint(reviewed_draft['workouts']) != workout_fingerprint):
            continue
        if current_draft_id and result.get('currentDraftId') != current_draft_id:
            continue
        if requirements_id and result.get('requirementsId') != requirements_id:
            continue
        if (latest.get('libraryFingerprint') is not None
                and result.get('libraryFingerprint') != latest['libraryFingerprint']):
            continue
        if ('historyFingerprint' in latest
                and result.get('historyFingerprint') != latest.get('historyFingerprint')):
            continue
        return index, result
    return -1, {}


def reviewable_concern_ids(messages):
    """Return current concerns whose uncertainty can be explicitly adjudicated."""
    _, result = _current_reviewed_audit(messages)
    review = result.get('review', {}) if isinstance(result, dict) else {}
    findings = review.get('findings', []) if isinstance(review, dict) else []
    if not findings and isinstance(review, dict) and review.get('failure'):
        # A failed semantic response has no parsed findings. Prefer obligations
        # already attached to this exact audit receipt; reconstruct only when the
        # receipt predates that projection, using its authority-checked ledger.
        checklist = result.get('reviewChecklist')
        carried = checklist.get('findings', {}) if isinstance(checklist, dict) else {}
        if not isinstance(carried, dict):
            carried = {}
        if not carried:
            from .plan_review import _review_checklist
            ledger = _review_checklist(result, messages)
            carried = ledger.get('findings', {}) if isinstance(ledger, dict) else {}
        findings = [entry.get('finding', {}) for entry in carried.values()
                    if isinstance(entry, dict) and isinstance(entry.get('finding'), dict)]
    ids = set()
    for finding in findings:
        concern_id = finding.get('concernGroupId') if isinstance(finding, dict) else None
        basis = finding.get('basis') if isinstance(finding, dict) else None
        severity = finding.get('severity') if isinstance(finding, dict) else None
        adjudicable = ((basis in ('soft_tradeoff', 'uncertainty') and severity == 'warning')
                       or (basis == 'material_uncertainty' and severity == 'blocking'))
        if isinstance(concern_id, str) and concern_id and adjudicable:
            ids.add(concern_id)
    return sorted(ids)


def record_planning_decisions_tool(messages):
    """Offer only code-indexed concern identities from the latest reviewed plan."""
    tool = copy.deepcopy(RECORD_PLANNING_DECISIONS_TOOL)
    active_ids = sorted(resolved_decisions(messages))
    tool['function']['parameters']['properties']['decisions']['items']['properties']['supersedes']['enum'] = [
        None, *active_ids]
    concern_ids = reviewable_concern_ids(messages)
    if concern_ids:
        tool['function']['parameters']['properties']['decisions']['items']['properties']['acceptedConcernGroupId'] = {
            'type': 'string', 'enum': concern_ids,
            'description': 'Explicitly accept this concern for this candidate; acceptance does not verify unknowns or waive hard requirements.'}
    return tool


def saved_decisions(messages):
    return latest_decision_receipt(messages)[1].get('decisions', {})


def resolved_decisions(messages):
    return {key: value for key, value in saved_decisions(messages).items() if not value.get('supersededBy')}


def _decision_source_hash(sources):
    return _fingerprint([{key: source[key] for key in ('content', 'images') if key in source}
                         if source.get('images') else source['content']
                         for source in sources.values() if source['role'] == 'user'])


def _pending_proposed_decisions(messages):
    """Return the latest rejected proposal only while its source/candidate is still current."""
    approved_index, _ = latest_decision_receipt(messages)
    source_hash = _decision_source_hash(source_message_context(requirement_sources(messages)))
    calls = {call.get('id'): call.get('function', {}).get('name')
             for message in messages for call in message.get('tool_calls', [])}
    from .planning_tools import latest_requirement_candidate
    candidate_index, _ = latest_requirement_candidate(messages)
    for index in range(len(messages) - 1, approved_index, -1):
        message = messages[index]
        if (message.get('role') != 'tool'
                or calls.get(message.get('tool_call_id')) not in ('record_planning_decisions', 'set_workout_requirements')):
            continue
        payload = _tool_payload(message)
        proposals = payload.get('proposedDecisions')
        if payload.get('passed') is not False or not isinstance(proposals, dict) or not proposals:
            continue
        if candidate_index > index:
            return {}
        prior_sources = payload.get('sourceMessages')
        if not isinstance(prior_sources, list):
            prior_sources = requirement_sources(messages[:index])
        if _decision_source_hash(source_message_context(prior_sources)) != source_hash:
            return {}
        return {key: value for key, value in proposals.items()
                if isinstance(key, str) and key.startswith('DECISION_') and key[9:].isdigit()
                and isinstance(value, dict)}
    return {}


def _remap_source_references(value, source_ids):
    """Translate SOURCE_n references after omitted menu/approval turns are filtered."""
    if isinstance(value, dict):
        return {key: _remap_source_references(item, source_ids) for key, item in value.items()}
    if isinstance(value, list):
        return [_remap_source_references(item, source_ids) for item in value
            if not (isinstance(item, str) and item.startswith('SOURCE_') and item not in source_ids)]
    if isinstance(value, str) and value.startswith('SOURCE_'):
        return source_ids.get(value, value)
    return value


def _active_reusable_decision_state(decisions):
    """Ignore candidate-scoped acceptances and receipt bookkeeping when comparing policy choices."""
    state = {}
    scoped_ids = {identifier for identifier, decision in (decisions or {}).items()
        if isinstance(decision, dict) and (decision.get('acceptedConcernGroupId')
            or decision.get('acceptedCandidateScope'))}
    for identifier, decision in (decisions or {}).items():
        if (not isinstance(decision, dict) or decision.get('acceptedConcernGroupId')
                or decision.get('acceptedCandidateScope')):
            continue
        state[identifier] = {key: decision[key] for key in (
            'topic', 'choice', 'sourceReferences', 'supersedes', 'supersededBy') if key in decision
            and not (key == 'supersededBy' and decision[key] in scoped_ids)}
    return state


def _later_reusable_decision_change(messages, approved):
    """Detect newer approved choices absent from the requirements approval snapshot."""
    calls = {call.get('id'): call.get('function', {}).get('name')
        for message in messages for call in message.get('tool_calls', [])}
    approved_index = next((index for index in range(len(messages) - 1, -1, -1)
        if messages[index].get('role') == 'tool' and calls.get(messages[index].get('tool_call_id'))
        in ('set_workout_requirements', 'accept_workout_alternative')
        and _tool_payload(messages[index]) == approved), -1)
    approved_state = _active_reusable_decision_state(approved.get('resolvedDecisions'))
    later_states = []
    for index in range(approved_index + 1, len(messages)):
        message = messages[index]
        if message.get('role') != 'tool' or calls.get(message.get('tool_call_id')) != 'record_planning_decisions':
            continue
        payload = _tool_payload(message)
        if (payload.get('passed') and payload.get('decisionReview', {}).get('passed')):
            later_states.append(_active_reusable_decision_state(payload.get('decisions')))
    return bool(later_states and later_states[-1] != approved_state)


def _tool_payload(message):
    try:
        payload = json.loads(message.get('content') or '{}')
    except (ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def seed_approved_policy_context(messages, initial_messages, equipment):
    """Start a plan-only conversation from the active approved requirements snapshot."""
    from .generation_audit import available_muscle_targets, validate_family_set_bounds
    from .planning_tools import (REQUIREMENTS_CONFIRMATION, approved_requirement_base,
        library_fingerprint, requirement_sources, requirements_approved)

    approved = approved_requirement_base(messages)
    if (not approved or not requirements_approved(messages, approved)
            or not isinstance(approved.get('requirements'), dict)):
        return None
    if _later_reusable_decision_change(messages, approved):
        return {'blockedReason': ('A newer independently reviewed programming choice is not included in the approved '
            'requirements snapshot. Refresh and approve the current requirements in this conversation before using '
            '`/clear keep-requirements`; the fresh conversation was not started.')}

    requirements = approved['requirements']
    decisions = copy.deepcopy(approved.get('resolvedDecisions') or {})
    candidate_scoped = any(decision.get('acceptedConcernGroupId') or decision.get('acceptedCandidateScope')
        for decision in decisions.values() if isinstance(decision, dict))
    reusable_decisions = {key: decision for key, decision in decisions.items()
        if isinstance(decision, dict) and not decision.get('acceptedConcernGroupId')
        and not decision.get('acceptedCandidateScope')}
    sources = approved.get('sourceMessages')
    if (not isinstance(sources, list) or any(not isinstance(source, dict)
            or source.get('role') not in ('user', 'assistant')
            or not isinstance(source.get('content'), str) for source in sources)):
        return None

    same_library = (not candidate_scoped and not approved.get('approvedAlternativeId')
        and approved.get('libraryFingerprint') == library_fingerprint(equipment or {}))
    alternative_id = approved.get('approvedAlternativeId')
    # Alternative previews and approval turns are candidate-scoped conversation
    # state. Exclude them from the fresh transcript and remap all source IDs.
    transient_indexes = {index for index, message in enumerate(messages)
        if message.get('canonicalAlternativePreview')}
    if alternative_id:
        transient_indexes.update(index for index, message in enumerate(messages)
            if message.get('role') == 'user' and not message.get('imageAttachments')
            and (message.get('content') or '').strip() == 'APPROVE ALTERNATIVE ' + alternative_id)
    original_source_ids = {source['messageIndex']: f'SOURCE_{index}' for index, source in enumerate(sources)
        if 'messageIndex' in source}
    filtered_sources = [source for source in sources if source.get('messageIndex') not in transient_indexes]
    new_source_ids = {source['messageIndex']: f'SOURCE_{index}' for index, source in enumerate(filtered_sources)
        if 'messageIndex' in source}
    source_id_map = {original_source_ids[index]: new_source_ids[index]
        for index in original_source_ids.keys() & new_source_ids.keys()}
    old_to_new = {old: new for old, new in source_id_map.items()}
    same_library = same_library and len(filtered_sources) == len(sources)
    requirements = _remap_source_references(copy.deepcopy(requirements), old_to_new)
    reusable_decisions = _remap_source_references(reusable_decisions, old_to_new)
    supported = available_muscle_targets(equipment or {})
    requested = {muscle for field in ('weeklyEffectiveSets', 'perSessionEffectiveSets')
        for muscle, bounds in requirements.get('auditTargets', {}).get(field, {}).items()
        if bounds.get('minimum', 0) > 0 or (bounds.get('maximum') or 0) > 0}
    if requested - supported.keys():
        same_library = False
    if requirements.get('familySetBounds'):
        from .recipe_contracts import reviewed_exercise_family_evidence
        if validate_family_set_bounds(requirements,
                reviewed_exercise_family_evidence(equipment or {})['familyByReference']):
            same_library = False

    seeded = copy.deepcopy(initial_messages)
    seeded.extend({key: copy.deepcopy(source[key]) for key in ('role', 'content', 'imageAttachments') if key in source}
        for source in filtered_sources)

    result = copy.deepcopy(approved)
    result['requirements'] = requirements
    result['resolvedDecisions'] = reusable_decisions
    result['sourceMessages'] = filtered_sources
    if not same_library:
        # A library change invalidates capability review and approval, but not the
        # user's source text or the requirements values they had approved.
        result.update(sourceReview={}, jointDecisionReview={}, resolvedDecisions=reusable_decisions, passed=False)
        result.pop('approvedAlternativeId', None)
        result.pop('proposedAlternative', None)
        if alternative_id:
            from .planning_tools import REQUIREMENTS_VERSION, render_requirements
            sources_context = source_message_context(filtered_sources)
            result['requirementsId'] = 'REQUIREMENTS_' + _fingerprint({
                'version': REQUIREMENTS_VERSION, 'requirements': requirements,
                'sources': sources_context, 'restrictionPolicy': result.get('restrictionPolicy')})[:16]
            result['requirementsPreview'] = render_requirements(
                requirements, result.get('restrictionPolicy'), confirmation=True)
        result['libraryFingerprint'] = library_fingerprint(equipment or {})

    call_id = 'carry_requirements'
    seeded.extend([
        {'role': 'assistant', 'tool_calls': [{'id': call_id, 'type': 'function',
            'function': {'name': 'set_workout_requirements', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': call_id, 'content': json.dumps(result, ensure_ascii=False)},
    ])
    if same_library:
        seeded.append({'role': 'assistant', 'content': result['requirementsPreview'],
            'canonicalRequirementsPreview': result['requirementsId']})
        if not alternative_id:
            seeded.append({'role': 'user', 'content': REQUIREMENTS_CONFIRMATION})
    else:
        seeded.append({'role': 'system', 'content': (
            'Approved requirements were carried from an archived conversation, but the exercise library changed, '
            'the old library identity is unavailable, or a candidate-specific alternative context was removed. '
            'Revalidate the same requirements against the current library, show a new requirements preview, '
            'and wait for explicit approval before planning.')})
    return {'messages': seeded, 'requirementsId': result['requirementsId'],
        'requiresReapproval': not same_library,
        'sourceReferenceCount': len(requirement_sources(seeded))}


def candidate_acceptance_scope(audit):
    """Fingerprint the exact validated candidate and its library/history context."""
    if not isinstance(audit, dict) or not isinstance(audit.get('audit'), dict):
        return None
    numerical_audit = audit['audit']
    if (not isinstance(numerical_audit.get('issues'), list) or numerical_audit['issues']
            or not isinstance(numerical_audit.get('errors'), list) or numerical_audit['errors']):
        return None
    draft = audit.get('submittedDraft')
    if (not isinstance(draft, dict) or not isinstance(draft.get('workouts'), list)
            or not draft['workouts']
            or not isinstance(audit.get('requirementsId'), str)
            or draft.get('requirementsId') != audit.get('requirementsId')
            or not isinstance(audit.get('libraryFingerprint'), str)
            or 'historyFingerprint' not in audit
            or (audit.get('historyFingerprint') is not None
                and not isinstance(audit.get('historyFingerprint'), str))):
        return None
    from .planning_tools import _DRAFT_SCHEMA
    try:
        validate(draft, _DRAFT_SCHEMA)
    except ValidationError:
        return None
    return {
        'workoutsFingerprint': _fingerprint(draft['workouts']),
        'libraryFingerprint': audit['libraryFingerprint'],
        'historyFingerprint': audit['historyFingerprint'],
    }


def propose_decisions(arguments, messages):
    arguments = copy.deepcopy(arguments)
    active_decisions = resolved_decisions(messages)
    active_ids = set(active_decisions)
    pending_decisions = _pending_proposed_decisions(messages)
    pending_ids = set(pending_decisions) - active_ids
    if isinstance(arguments, dict) and isinstance(arguments.get('decisions'), list):
        for index, item in enumerate(arguments['decisions']):
            if not isinstance(item, dict):
                continue
            reference = item.get('supersedes')
            if reference is None or not isinstance(reference, str) or reference in active_ids:
                continue
            if reference in pending_ids:
                # This names rejected draft intent, not an approved decision. Re-review
                # the corrected choice without creating or superseding a decision lineage.
                prior_target = pending_decisions[reference].get('supersedes')
                if prior_target in active_ids:
                    item['supersedes'] = prior_target
                else:
                    item.pop('supersedes', None)
                continue
            available = ', '.join(sorted(active_ids)) or '(none)'
            raise PlanningInputError('unknown_decision_reference',
                f'{reference} is not an active approved decision or a current rejected proposal.',
                f'/decisions/{index}/supersedes',
                f'Omit supersedes for a new choice. To replace an approved choice, use one of: {available}; '
                'a rejected proposal is not settled and must be submitted for review as a corrected choice.')
    concern_ids = reviewable_concern_ids(messages)
    tool = record_planning_decisions_tool(messages)
    validate(arguments, tool['function']['parameters'])
    sources = source_message_context(requirement_sources(messages))
    source_hash = _decision_source_hash(sources)
    decisions = saved_decisions(messages)
    acceptance_scope = None
    if any(item.get('acceptedConcernGroupId') for item in arguments['decisions']):
        _, latest_audit = _current_reviewed_audit(messages)
        acceptance_scope = candidate_acceptance_scope(latest_audit)
        if acceptance_scope is None:
            raise PlanningInputError('accepted_candidate_unavailable',
                'A scoped acceptance requires a current candidate with a clean numerical audit.',
                '/decisions/acceptedConcernGroupId',
                'Audit the current submitted workout successfully before accepting a concern for this candidate.')
    proposed = []
    for item in arguments['decisions']:
        concern_id = item.get('acceptedConcernGroupId')
        if concern_id is not None and concern_id not in concern_ids:
            raise PlanningInputError('invalid_decision_concern',
                'A decision can accept only a current reviewable uncertainty or preference.',
                '/decisions/acceptedConcernGroupId', 'Select one of the current review concern choices or omit the field.')
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
                          and value.get('acceptedConcernGroupId') == concern_id
                          and (normalize(value['topic']) == normalize(item['topic']) or item.get('supersedes') == key)
                          and item.get('supersedes') in (None, key)), None)
        if identical:
            same = identical
            if concern_id and active[same].get('acceptedCandidateScope') != acceptance_scope:
                raise PlanningInputError('accepted_candidate_changed',
                    'The existing acceptance belongs to a different candidate or evidence scope.',
                    '/decisions/acceptedConcernGroupId',
                    'Record a new source-backed acceptance for the current candidate; do not reuse the prior scope.')
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
        identifier_index = len(decisions)
        while f'DECISION_{identifier_index}' in decisions:
            identifier_index += 1
        identifier = f'DECISION_{identifier_index}'
        decisions[identifier] = copy.deepcopy(item)
        if concern_id:
            decisions[identifier]['acceptedCandidateScope'] = copy.deepcopy(acceptance_scope)
        decisions[identifier]['sourceCountAtResolution'] = len(sources)
        decisions[identifier]['authorizationSourceHash'] = source_hash
        if previous:
            decisions[previous]['supersededBy'] = identifier
        proposed.append(identifier)
    return {'decisions': decisions, 'newDecisionIds': proposed, 'sourceMessages': sources}


def render_decisions(decisions):
    return '\n'.join(f"- **{item['topic']}**: {item['choice']}" for item in decisions.values() if not item.get('supersededBy'))
