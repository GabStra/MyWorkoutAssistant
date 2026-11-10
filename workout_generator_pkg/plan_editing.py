"""Open saved generator plans as independent editing conversations."""

import copy
import json
from pathlib import Path

from .conversation_store import list_conversations, load_conversation_record, resolve_conversation_id
from .planning_tools import _latest_result, library_fingerprint


def _plan_source(record, messages_path):
    messages = record['messages']
    end = len(messages)
    while end:
        index, snapshot = _latest_result(messages[:end], 'audit_workout_plan')
        if index < 0:
            break
        if (snapshot.get('passed') and not snapshot.get('errors')
                and not snapshot.get('audit', {}).get('errors')
                and snapshot.get('submittedDraft', {}).get('workouts')
                and snapshot.get('planIndex', {}).get('workouts')):
            _, requirements = _latest_result(messages[:index + 1], 'set_workout_requirements')
            if requirements.get('requirementsId') == snapshot.get('requirementsId'):
                return {'messages': copy.deepcopy(messages[:index + 1]),
                    'metadata': copy.deepcopy(record.get('metadata', {})), 'snapshot': snapshot,
                    'messagesPath': str(Path(messages_path).resolve())}
        end = index
    raise ValueError('No complete audited plan is saved here. Resume this conversation to finish it first.')


def _source_from_messages(path):
    messages = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(messages, list) or any(not isinstance(message, dict) for message in messages):
        raise ValueError('Expected a saved generator messages.json file.')
    meta_path = path.with_name('meta.json')
    metadata = json.loads(meta_path.read_text(encoding='utf-8-sig')) if meta_path.exists() else {}
    if not isinstance(metadata, dict):
        raise ValueError('The saved conversation metadata must be an object.')
    return _plan_source({'messages': messages, 'metadata': metadata}, path)


def select_plan_for_edit(target, script_dir, current_record=None):
    """Resolve a conversation, its messages file, or an export linked to its saved context."""
    target = (target or 'latest').strip().strip('"')
    path = Path(target).expanduser()
    if path.is_file():
        if path.name == 'messages.json':
            return _source_from_messages(path)
        # Exports need their generator context: requirements and library IDs are not inferred.
        roots = dict.fromkeys((str(Path(script_dir).resolve()), str(path.resolve().parent.parent)))
        for root in roots:
            for record in list_conversations(root):
                outputs = record['metadata'].get('generated_output_paths', [])
                output = (record['metadata'].get('last_generation_result') or {}).get('filepath')
                if any(Path(value).resolve() == path.resolve() for value in [*outputs, output] if value):
                    source_path = Path(root) / 'workouts/conversation_sessions' / record['conversation_id'] / 'messages.json'
                    source = _plan_source(record, source_path)
                    _check_export_matches_source(path, source['snapshot'])
                    return source
        raise ValueError('This export has no saved generator context. Select its original messages.json or conversation ID.')
    if target == 'latest':
        records = ([current_record] if current_record else []) + list_conversations(script_dir)
        for record in records:
            try:
                source_path = Path(script_dir) / 'workouts/conversation_sessions' / record['conversation_id'] / 'messages.json'
                return _plan_source(record, source_path)
            except ValueError:
                continue
        raise ValueError('No complete saved plan was found. Generate a plan or select its messages.json first.')
    identifier = resolve_conversation_id(target, script_dir)
    if not identifier:
        raise ValueError('Plan not found. Use latest, a saved conversation ID, messages.json, or its exported JSON path.')
    record = load_conversation_record(identifier, script_dir)
    return _plan_source(record, Path(script_dir) / 'workouts/conversation_sessions' / identifier / 'messages.json')


def _check_export_matches_source(path, snapshot):
    from .domain_ops import reviewable_workout_artifact, general_warmup_exercises

    payload = json.loads(path.read_text(encoding='utf-8-sig'))
    expected = reviewable_workout_artifact(snapshot['planIndex'], '')
    actual = reviewable_workout_artifact(snapshot['planIndex'], '', payload)
    mapping = {}
    definitions = {item['id']: item.get('libraryDefinitionId') for item in snapshot['planIndex']['exercises']}
    warmups = general_warmup_exercises(snapshot['planIndex'])
    definitions.update({warmups[day['id']]['id']: day['generalWarmupDefinition']['id']
        for day in snapshot['planIndex']['workouts'] if warmups.get(day['id'])})
    exported = {item['id']: item.get('exerciseDefinitionId') for day in payload['workouts']
        for component in day['workoutComponents']
        for item in (component.get('exercises', []) if component['type'] == 'Superset' else
            [component] if component['type'] == 'Exercise' else [])}
    for before, after in zip(expected['workouts'], actual['workouts'], strict=True):
        mapping[before['id']] = after['id']
        for left, right in zip(before['components'], after['components'], strict=True):
            if left['type'] != right['type']:
                raise ValueError('The export differs from its saved generator plan.')
            if left['type'] == 'Exercise':
                mapping[left['id']] = right['id']
            elif left['type'] == 'Superset':
                for first, second in zip(left['exercises'], right['exercises'], strict=True):
                    mapping[first['id']] = second['id']
    if reviewable_workout_artifact(snapshot['planIndex'], '', payload, mapping) != expected:
        raise ValueError('The export was modified outside the generator. Select messages.json to edit the original saved plan.')
    if any(definition is not None and exported.get(mapping.get(identifier)) != definition
            for identifier, definition in definitions.items()):
        raise ValueError('The exported exercise definitions differ from the saved plan.')


def editing_messages(source, equipment):
    """Copy the complete base without inheriting an incumbent gate or export consent."""
    snapshot = source['snapshot']
    if not equipment.get('exerciseDefinitions'):
        raise ValueError('Editing needs the full exercise library. Start with --exercise-library-file or --history-backup-file.')
    if snapshot.get('libraryFingerprint') != library_fingerprint(equipment):
        raise ValueError('Load the same full library and equipment used by this plan before editing; saved LIBRARY references must match.')
    messages = copy.deepcopy(source['messages'])
    owner = next((message for message in messages if message.get('role') == 'system'), None)
    if owner is None:
        raise ValueError('The saved generator context is missing its system message.')
    owner.pop('incumbentPlan', None)
    owner['planningIntent'] = 'edit'
    if snapshot.get('preview'):
        messages.append({'role': 'assistant', 'content': snapshot['preview'],
            'canonicalDraftPreview': snapshot['draftId']})
    return messages
