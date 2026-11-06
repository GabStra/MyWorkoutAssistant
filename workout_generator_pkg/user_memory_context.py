"""Bind confirmed profile facts without manufacturing conversation turns or approvals."""
import copy
import json

import workout_user_memory as memory_store


_PHYSICAL_KINDS = {'shared_station', 'setup_access'}


def memory_context(messages):
    contexts = [message['userMemory'] for message in messages
        if message.get('role') == 'system' and 'userMemory' in message]
    if len(contexts) > 1:
        raise ValueError('A conversation must have exactly one user-memory binding.')
    return contexts[0] if contexts else {}


def memory_sources(messages):
    sources = copy.deepcopy(memory_context(messages).get('sources', []))
    return [{'messageIndex': index - len(sources), **source} for index, source in enumerate(sources)]


def _display_value(fact, equipment):
    names = {item['id']: item.get('name') or item['id']
        for collection in ('equipments', 'accessoryEquipments', 'exerciseDefinitions')
        for item in (equipment or {}).get(collection, [])}
    value = fact['value']
    if fact['kind'] == 'shared_station':
        return [names.get(identifier, identifier) for identifier in value]
    if fact['kind'] == 'setup_access':
        return {'independentExercises': [names.get(identifier, identifier)
                    for identifier in value['independentDefinitionIds']],
                'retainedResources': [names.get(identifier, identifier)
                    for identifier in value['retainedResourceIds']]}
    return copy.deepcopy(value)


def _fact_source(profile_id, fact, *, available, equipment=None):
    value = _display_value(fact, equipment)
    content = ('Previously confirmed physical setup fact: ' + json.dumps(
        {'kind': fact['kind'], 'value': value}, sort_keys=True)
        if fact['kind'] in _PHYSICAL_KINDS else
        f"Previously confirmed {fact['kind']}: {fact['value']}")
    return {'role': 'user', 'content': content,
        'origin': 'user_memory', 'profileId': profile_id, 'factId': fact['factId'],
        'sourceProvenance': copy.deepcopy(fact['source']),
        'confirmedFact': {'kind': fact['kind'], 'value': value,
            'available': available, 'confirmedAt': fact['confirmedAt'],
            **({'reason': fact['reason']} if not available else {})}}


def _render(context, equipment=None):
    summary = {'profileId': context['profileId'], **{key: [
        {**{field: copy.deepcopy(fact[field]) for field in
            ('factId', 'kind', 'confirmedAt', 'reason') if field in fact},
         'value': _display_value(fact, equipment)}
        for fact in context[key]] for key in ('facts', 'unavailableFacts')}}
    return ('Confirmed user profile facts (backend data, not conversation turns or run approvals). '
        'Typed physical facts apply directly through shared setup binding. Unavailable physical facts '
        'require clarification before using the affected setup. Original user statements and their '
        'typed confirmed interpretation are preserved in source provenance. Current instructions may '
        'correct facts, but a contradiction needs explicit supersession; it is not permission to assume '
        'independent access.\n' + json.dumps(summary, ensure_ascii=False, sort_keys=True))


def bind_user_memory(messages, profile_id, equipment=None, *, root=None):
    previous = memory_context(messages)
    if previous and previous.get('profileId') != profile_id:
        raise ValueError('This conversation is bound to a different user profile.')
    if not profile_id:
        return {}
    context = memory_store.facts_for(profile_id, equipment, root=root)
    context['sources'] = [_fact_source(profile_id, fact, available=available, equipment=equipment)
        for available, facts in ((True, context['facts']), (False, context['unavailableFacts']))
        for fact in facts]
    context['factSourceReferences'] = {source['factId']: [f'SOURCE_{index}']
        for index, source in enumerate(context['sources'])}
    message = {'role': 'system', 'content': _render(context, equipment), 'userMemory': context}
    if previous:
        index = next(index for index, item in enumerate(messages)
            if item.get('role') == 'system' and 'userMemory' in item)
        messages[index] = message
    else:
        messages.insert(next((index for index, item in enumerate(messages)
            if item.get('role') != 'system'), len(messages)), message)
    return context


def _confirmation(fact, references):
    return {**({'confirmedSharedStation': copy.deepcopy(fact['value'])}
               if fact['kind'] == 'shared_station' else copy.deepcopy(fact['value'])),
        'sourceReferences': list(references)}


def _physical_ids(fact):
    value = fact['value']
    if fact['kind'] == 'shared_station':
        return set(value)
    return set(value['independentDefinitionIds']) | set(value['retainedResourceIds'])


def memory_setup_confirmations(messages, equipment):
    from .planning_tools import PlanningInputError
    context = memory_context(messages)
    available_ids = {item['id'] for key in ('equipments', 'accessoryEquipments', 'exerciseDefinitions')
        for item in equipment.get(key, [])}
    for fact in context.get('unavailableFacts', []):
        if fact['kind'] in _PHYSICAL_KINDS and _physical_ids(fact) & available_ids:
            raise PlanningInputError('user_memory_setup_unavailable',
                f"Stored physical fact {fact['factId']} needs clarification: {fact['reason']}",
                '/userMemory/unavailableFacts',
                'Confirm the changed physical setup and explicitly supersede or forget the old fact before using it.')
    for fact in context.get('facts', []):
        if fact['kind'] not in _PHYSICAL_KINDS:
            continue
        scope = fact['scope']
        try:
            current_scope = memory_store.capture_scope(equipment,
                [item['id'] for item in scope['resources']],
                [item['id'] for item in scope['definitions']])
        except ValueError:
            current_scope = None
        if current_scope != scope and _physical_ids(fact) & available_ids:
            raise PlanningInputError('user_memory_setup_unavailable',
                f"Stored physical fact {fact['factId']} no longer matches the current library.",
                '/userMemory/facts', 'Reload memory and clarify the changed setup before using it.')
    references = context.get('factSourceReferences', {})
    return [_confirmation(fact, references[fact['factId']])
        for fact in context.get('facts', [])
        if fact['kind'] in _PHYSICAL_KINDS and _physical_ids(fact) & available_ids]


def validate_setup_conflicts(requirements, equipment, confirmations):
    """A shared station must never quietly downgrade a claimed independent setup to unknown."""
    from .planning_tools import PlanningInputError
    from .programming_guidelines import equipment_setup_resources, shared_superset_station_group
    shared_requirements = copy.deepcopy(requirements)
    rules = shared_requirements.setdefault('executionRules', [])
    # Conflict detection also applies when the current program has no superset rule yet.
    rules.append({'kind': 'supersetNoReconfiguration', 'sharedResourceGroups': [
        confirmation['confirmedSharedStation'] for confirmation in confirmations
        if confirmation.get('confirmedSharedStation')]})
    definitions = {item['id']: item for item in equipment.get('exerciseDefinitions', [])}
    for confirmation in confirmations:
        for identifier in confirmation.get('independentDefinitionIds', []):
            first = definitions.get(identifier)
            if not first:
                continue
            retained = {'requiredAccessoryEquipmentIds': confirmation['retainedResourceIds']}
            if (equipment_setup_resources([first]) & set(confirmation['retainedResourceIds'])
                    or shared_superset_station_group(first, retained, shared_requirements)):
                raise PlanningInputError('conflicting_user_setup_facts',
                    'Confirmed independent access conflicts with a shared physical station.',
                    '/userMemory/facts',
                    'Clarify the physical setup and explicitly supersede the conflicting stored fact; do not assume independent access.')


def persist_reviewed_setup_facts(messages, result, equipment, *, root=None):
    """Persist only newly reviewed typed physical assertions, never model policy or approval."""
    from .planning_decisions import saved_decisions
    from .planning_tools import requirement_sources
    context = memory_context(messages)
    if not context or not result.get('passed'):
        return []
    joint = result.get('jointDecisionReview', {})
    if not (result.get('decisionReview', {}).get('passed') or
            joint.get('passed') and result.get('sourceReview', {}).get('passed')):
        return []
    decisions = result.get('decisions', result.get('resolvedDecisions', {}))
    new_ids = joint.get('newDecisionIds', result.get('newDecisionIds'))
    if new_ids is None:
        new_ids = [identifier for identifier in decisions if identifier not in saved_decisions(messages)]
    sources = {f'SOURCE_{index}': source for index, source in enumerate(requirement_sources(messages))}
    pending = []
    for identifier in new_ids:
        decision = decisions.get(identifier, {})
        if decision.get('supersededBy') or not (
                decision.get('confirmedSharedStation') or decision.get('confirmedSetupAccess')):
            continue
        references = decision.get('sourceReferences', [])
        cited = [sources[reference] for reference in references if reference in sources]
        user_sources = [source for source in cited if source.get('role') == 'user']
        if not user_sources or len(cited) != len(references):
            raise ValueError('Reviewed physical facts require original explicit user provenance.')
        source = {'role': 'user', 'statement': '\n\n'.join(
            item.get('sourceProvenance', {}).get('statement', item['content']) for item in user_sources),
            'sourceReferences': references}
        source_context = [{'role': item['role'], 'content': item['content']} for item in cited
            if item.get('role') == 'assistant']
        source_context.extend(context_item for item in user_sources
            for context_item in item.get('sourceProvenance', {}).get('context', []))
        for item in user_sources:
            index = item.get('messageIndex', -1)
            if index < 0:
                continue
            interaction = messages[index].get('userInteraction', {})
            if interaction.get('question'):
                source_context.append({'role': 'assistant', 'content': json.dumps(
                    interaction['question'], ensure_ascii=False, sort_keys=True)})
                if interaction.get('input'):
                    source_context.append({'role': 'user', 'content': interaction['input']})
            else:
                previous = next((message for message in reversed(messages[:index])
                    if message.get('role') in ('user', 'assistant') and message.get('content')), {})
                if previous.get('role') == 'assistant':
                    source_context.append({'role': 'assistant', 'content': previous['content']})
        source_context = list({(item['role'], item['content']): item for item in source_context}.values())
        if source_context:
            source['context'] = source_context
        for field, kind in (('confirmedSharedStation', 'shared_station'),
                            ('confirmedSetupAccess', 'setup_access')):
            if not decision.get(field):
                continue
            value = copy.deepcopy(decision[field])
            resource_ids = value if kind == 'shared_station' else value['retainedResourceIds']
            definition_ids = () if kind == 'shared_station' else value['independentDefinitionIds']
            scope = memory_store.capture_scope(equipment, resource_ids, definition_ids)
            pending.append({'kind': kind, 'value': value, 'source': source, 'scope': scope,
                'references': references})
    if not pending:
        return []
    current = memory_store.facts_for(context['profileId'], equipment, root=root)
    for old_fact in current['unavailableFacts']:
        if old_fact['kind'] in _PHYSICAL_KINDS and any(
                _physical_ids(old_fact) & _physical_ids(fact) for fact in pending):
            from .planning_tools import PlanningInputError
            raise PlanningInputError('user_memory_setup_unavailable',
                f"Stored physical fact {old_fact['factId']} needs explicit supersession.",
                '/userMemory/unavailableFacts',
                'Confirm the changed setup and explicitly supersede or forget the old fact before saving a replacement.')
    confirmations = [_confirmation(fact, ['reviewed_source']) for fact in current['facts']
        if fact['kind'] in _PHYSICAL_KINDS]
    confirmations.extend(_confirmation(fact, fact['references']) for fact in pending)
    validate_setup_conflicts({}, equipment, confirmations)
    saved = []
    for fact in pending:
        references = fact.pop('references')
        stored = memory_store.record_fact(context['profileId'], **fact, root=root)
        fact_id = stored['factId']
        context.setdefault('factSourceReferences', {}).setdefault(fact_id, list(references))
        saved.append(fact_id)
    refreshed = memory_store.facts_for(context['profileId'], equipment, root=root)
    context.update({key: refreshed[key] for key in ('facts', 'unavailableFacts')})
    for message in messages:
        if message.get('role') == 'system' and 'userMemory' in message:
            message['content'] = _render(context, equipment)
    return saved
