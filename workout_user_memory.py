"""Explicit user-confirmed workout facts, kept outside individual conversations."""
import argparse
import copy
import json
import os
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from workout_generator_pkg.json_io import write_json_atomic


KINDS = ('shared_station', 'setup_access', 'standing_restriction', 'standing_preference')
_DEFINITION_PROPERTIES = ('exerciseType', 'equipmentId', 'requiredAccessoryEquipmentIds')


def memory_root(root=None):
    if root is not None:
        return Path(root).expanduser().resolve()
    configured = os.environ.get('MYWORKOUT_USER_MEMORY_DIR')
    if configured:
        return Path(configured).expanduser().resolve()
    if sys.platform == 'win32':
        base = Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local')
    elif sys.platform == 'darwin':
        base = Path.home() / 'Library' / 'Application Support'
    else:
        base = Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local' / 'share')
    return base / 'MyWorkoutAssistant' / 'user_memory'


def _uuid(value):
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError('Expected a canonical UUID.')
    return value


def _text(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('Expected nonempty text.')
    return value


def _ids(value, minimum=0):
    if (not isinstance(value, list) or len(value) < minimum
            or any(not isinstance(item, str) or not item.strip() for item in value)
            or len(value) != len(set(value))):
        raise ValueError('Expected unique nonempty stable IDs.')
    return value


def _timestamp(value):
    if not isinstance(value, str) or datetime.fromisoformat(value).utcoffset() is None:
        raise ValueError('Expected a timezone-aware timestamp.')


def _now():
    return datetime.now(timezone.utc).isoformat()


def _read(path):
    try:
        with Path(path).open(encoding='utf-8') as stream:
            return json.load(stream)
    except (json.JSONDecodeError, UnicodeError) as error:
        raise ValueError(f'Corrupt user memory: {path}') from error


@contextmanager
def _writing(root):
    root.mkdir(parents=True, exist_ok=True)
    lock = root / '.write.lock'
    try:
        handle = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as error:
        raise RuntimeError(f'User memory is busy; if no writer is running, remove {lock}.') from error
    try:
        yield
    finally:
        os.close(handle)
        lock.unlink()


def _profile_path(profile_id, root):
    return memory_root(root) / 'profiles' / f'{_uuid(profile_id)}.json'


def _source(source):
    if not isinstance(source, dict) or source.get('role') != 'user':
        raise ValueError('Memory requires an explicit user source.')
    _text(source.get('statement'))
    if set(source) - {'role', 'statement', 'conversationId', 'sourceReferences', 'context'}:
        raise ValueError('Unknown user-source fields.')
    if 'conversationId' in source:
        _text(source['conversationId'])
    if 'sourceReferences' in source:
        _ids(source['sourceReferences'])
    if 'context' in source:
        if not isinstance(source['context'], list):
            raise ValueError('Source context must contain original conversation messages.')
        for message in source['context']:
            if (not isinstance(message, dict) or set(message) != {'role', 'content'}
                    or message['role'] not in ('user', 'assistant')):
                raise ValueError('Invalid source context message.')
            _text(message['content'])


def _value(kind, value):
    if kind == 'shared_station':
        _ids(value, 2)
    elif kind == 'setup_access':
        if not isinstance(value, dict) or set(value) != {'independentDefinitionIds', 'retainedResourceIds'}:
            raise ValueError('Setup access requires independentDefinitionIds and retainedResourceIds.')
        _ids(value['independentDefinitionIds'], 1)
        _ids(value['retainedResourceIds'], 1)
    elif kind in ('standing_restriction', 'standing_preference'):
        _text(value)
    else:
        raise ValueError(f'Unsupported memory kind: {kind}')


def _scope(scope):
    if not isinstance(scope, dict) or set(scope) != {'resources', 'definitions'}:
        raise ValueError('Invalid memory dependency scope.')
    for key in ('resources', 'definitions'):
        if not isinstance(scope[key], list):
            raise ValueError('Invalid memory dependency scope.')
        seen = set()
        for item in scope[key]:
            required = {'id', 'properties', 'collection'} if key == 'resources' else {'id', 'properties'}
            if not isinstance(item, dict) or set(item) != required or not isinstance(item['properties'], dict):
                raise ValueError('Invalid memory dependency snapshot.')
            _text(item['id'])
            if item['id'] in seen:
                raise ValueError('Duplicate memory dependency.')
            seen.add(item['id'])
            if key == 'resources' and item['collection'] not in ('equipments', 'accessoryEquipments'):
                raise ValueError('Invalid resource collection.')


def _fact(fact):
    if not isinstance(fact, dict):
        raise ValueError('Invalid memory fact.')
    _uuid(fact.get('factId'))
    if fact.get('status') == 'forgotten':
        if set(fact) != {'factId', 'status', 'forgottenAt'}:
            raise ValueError('Invalid forgotten fact.')
        _timestamp(fact['forgottenAt'])
        return
    if fact.get('status') not in ('active', 'superseded'):
        raise ValueError('Invalid memory fact status.')
    _value(fact.get('kind'), fact.get('value'))
    _source(fact.get('source'))
    _timestamp(fact.get('confirmedAt'))
    if fact.get('scope') is not None:
        _scope(fact['scope'])
    if fact['kind'] in ('shared_station', 'setup_access'):
        if fact.get('scope') is None:
            raise ValueError('Physical facts require dependency snapshots.')
        resources = {item['id'] for item in fact['scope']['resources']}
        definitions = {item['id'] for item in fact['scope']['definitions']}
        value = fact['value']
        if fact['kind'] == 'shared_station':
            covered = set(value) <= resources
        else:
            covered = (set(value['retainedResourceIds']) <= resources
                       and set(value['independentDefinitionIds']) <= definitions)
        if not covered:
            raise ValueError('Memory scope does not cover its fact.')
    if 'supersedes' in fact:
        _uuid(fact['supersedes'])
    if fact['status'] == 'superseded':
        _uuid(fact.get('supersededBy'))


def create_profile(name, root=None):
    _text(name)
    profile = {'profileId': str(uuid4()), 'name': name, 'facts': []}
    with _writing(memory_root(root)):
        write_json_atomic(_profile_path(profile['profileId'], root), profile)
    return profile


def load_profile(profile_id, root=None):
    profile = _read(_profile_path(profile_id, root))
    if (not isinstance(profile, dict) or profile.get('profileId') != profile_id
            or not isinstance(profile.get('facts'), list)):
        raise ValueError('Invalid user memory profile.')
    _text(profile.get('name'))
    identifiers = set()
    for fact in profile['facts']:
        _fact(fact)
        if fact['factId'] in identifiers:
            raise ValueError('Duplicate memory fact ID.')
        identifiers.add(fact['factId'])
    for fact in profile['facts']:
        if any(fact[key] not in identifiers for key in ('supersedes', 'supersededBy') if key in fact):
            raise ValueError('Broken memory supersession reference.')
    return profile


def _catalog(equipment, collection):
    entries = (equipment or {}).get(collection, [])
    if not isinstance(entries, list) or any(not isinstance(item, dict) for item in entries):
        raise ValueError(f'Invalid library collection: {collection}')
    result = {}
    for item in entries:
        identifier = _text(item.get('id'))
        if identifier in result:
            raise ValueError(f'Duplicate library ID: {identifier}')
        result[identifier] = item
    return result


def _library(value):
    if isinstance(value, dict) and 'WorkoutStore' in value:
        value = value['WorkoutStore']
    if not isinstance(value, dict):
        raise ValueError('Expected an exercise library or AppBackup with WorkoutStore.')
    return value


def _definition_properties(definition):
    properties = {key: copy.deepcopy(definition[key]) for key in _DEFINITION_PROPERTIES if key in definition}
    if 'requiredAccessoryEquipmentIds' in properties:
        properties['requiredAccessoryEquipmentIds'] = sorted(properties['requiredAccessoryEquipmentIds'] or [])
    execution = definition.get('reviewedExecution') or {}
    if not isinstance(execution, dict):
        raise ValueError('Invalid definition execution configuration.')
    setup = execution.get('setupConfiguration')
    if setup is not None:
        if (not isinstance(setup, list) or any(not isinstance(item, dict)
                or not isinstance(item.get('resourceId'), str) or not isinstance(item.get('state'), dict)
                for item in setup)):
            raise ValueError('Invalid definition setup configuration.')
        properties['setupConfiguration'] = sorted([
            {'resourceId': item['resourceId'], 'state': copy.deepcopy(item['state'])} for item in setup],
            key=lambda item: item['resourceId'])
    return properties


def capture_scope(equipment, resource_ids=(), definition_ids=()):
    """Capture only dependencies of this fact; display names never define identity."""
    equipment = _library(equipment)
    resources = {}
    for collection in ('equipments', 'accessoryEquipments'):
        for identifier, item in _catalog(equipment, collection).items():
            if identifier in resources:
                raise ValueError(f'Ambiguous library resource ID: {identifier}')
            resources[identifier] = (collection, item)
    definitions = _catalog(equipment, 'exerciseDefinitions')
    selected_resources = set(_ids(list(resource_ids)))
    selected_definitions = set(_ids(list(definition_ids)))
    for identifier in selected_definitions:
        if identifier not in definitions:
            raise ValueError(f'Missing definition: {identifier}')
        definition = definitions[identifier]
        if definition.get('equipmentId'):
            selected_resources.add(definition['equipmentId'])
        selected_resources.update(definition.get('requiredAccessoryEquipmentIds') or [])
    scope = {'resources': [], 'definitions': []}
    for identifier in sorted(selected_resources):
        if identifier not in resources:
            raise ValueError(f'Missing resource: {identifier}')
        collection, item = resources[identifier]
        scope['resources'].append({'id': identifier, 'collection': collection,
            'properties': {'type': item['type']} if 'type' in item else {}})
    for identifier in sorted(selected_definitions):
        scope['definitions'].append({'id': identifier, 'properties': _definition_properties(definitions[identifier])})
    return scope


def record_fact(profile_id, *, kind, value, source, scope=None, supersedes=None, root=None):
    fact = {'factId': str(uuid4()), 'kind': kind, 'value': copy.deepcopy(value),
            'source': copy.deepcopy(source), 'confirmedAt': _now(), 'status': 'active',
            'scope': copy.deepcopy(scope)}
    if supersedes is not None:
        fact['supersedes'] = supersedes
    _fact(fact)
    with _writing(memory_root(root)):
        profile = load_profile(profile_id, root)
        if supersedes is not None:
            previous = next((item for item in profile['facts'] if item['factId'] == supersedes), None)
            if previous is None or previous['status'] != 'active' or previous['kind'] != kind:
                raise ValueError('Supersedes must identify an active fact of the same kind in this profile.')
            previous.update(status='superseded', supersededBy=fact['factId'])
        else:
            duplicate = next((item for item in profile['facts'] if item['status'] == 'active'
                and item['kind'] == kind and item['value'] == value and item.get('scope') == scope), None)
            if duplicate:
                return duplicate
        profile['facts'].append(fact)
        write_json_atomic(_profile_path(profile_id, root), profile)
    return fact


def forget_fact(profile_id, fact_id, root=None):
    _uuid(fact_id)
    with _writing(memory_root(root)):
        profile = load_profile(profile_id, root)
        fact = next((item for item in profile['facts'] if item['factId'] == fact_id), None)
        if fact is None:
            raise ValueError('Unknown fact in this user profile.')
        fact.clear()
        fact.update(factId=fact_id, status='forgotten', forgottenAt=_now())
        write_json_atomic(_profile_path(profile_id, root), profile)


def facts_for(profile_id, equipment=None, root=None):
    result = {'profileId': profile_id, 'facts': [], 'unavailableFacts': []}
    for fact in load_profile(profile_id, root)['facts']:
        if fact['status'] != 'active':
            continue
        scope = fact.get('scope')
        reason = None
        if scope is not None and (scope['resources'] or scope['definitions']):
            if equipment is None:
                reason = 'Current library is required to verify this fact.'
            else:
                try:
                    current = capture_scope(equipment, [item['id'] for item in scope['resources']],
                                            [item['id'] for item in scope['definitions']])
                    if current != scope:
                        reason = 'Referenced resource or definition configuration changed.'
                except ValueError as error:
                    reason = str(error)
        if reason:
            result['unavailableFacts'].append({**fact, 'reason': reason})
        else:
            result['facts'].append(fact)
    return result


def _history_path(path):
    return os.path.normcase(str(Path(path).expanduser().resolve()))


def _bindings(root):
    path = memory_root(root) / 'history_bindings.json'
    bindings = _read(path) if path.exists() else {}
    if not isinstance(bindings, dict):
        raise ValueError('Invalid history-profile bindings.')
    for key, value in bindings.items():
        if key != _history_path(key):
            raise ValueError('Invalid canonical history path.')
        _uuid(value)
    return bindings


def bind_history(profile_id, path, root=None):
    with _writing(memory_root(root)):
        load_profile(profile_id, root)
        bindings = _bindings(root)
        canonical = _history_path(path)
        if canonical in bindings and bindings[canonical] != profile_id:
            raise ValueError('This history file is already bound to another user profile.')
        bindings[canonical] = profile_id
        write_json_atomic(memory_root(root) / 'history_bindings.json', bindings)


def profile_for_history(path, root=None):
    identifier = _bindings(root).get(_history_path(path))
    if identifier is not None:
        load_profile(identifier, root)
    return identifier


def resolve_profile(profile_id=None, history_path=None, root=None):
    """Resolve explicit identity or a user-created history binding, never infer a user."""
    configured = profile_id if profile_id is not None else os.environ.get('MYWORKOUT_PROFILE_ID')
    bound = profile_for_history(history_path, root) if history_path is not None else None
    if configured is not None:
        load_profile(configured, root)
        if bound is not None and configured != bound:
            raise ValueError('Configured user profile conflicts with this history file binding.')
    return configured or bound


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', help='Override local user-memory directory.')
    commands = parser.add_subparsers(dest='command', required=True)
    create = commands.add_parser('create')
    create.add_argument('name')
    show = commands.add_parser('show')
    show.add_argument('profile')
    show.add_argument('--library')
    confirm = commands.add_parser('confirm')
    confirm.add_argument('--profile', required=True)
    confirm.add_argument('--kind', choices=KINDS, required=True)
    confirm.add_argument('--value', required=True, help='JSON value with stable library IDs.')
    confirm.add_argument('--source', required=True, help='The explicit original user statement.')
    confirm.add_argument('--conversation-id')
    confirm.add_argument('--library')
    confirm.add_argument('--supersedes')
    forget = commands.add_parser('forget')
    forget.add_argument('profile')
    forget.add_argument('fact')
    bind = commands.add_parser('bind-history')
    bind.add_argument('profile')
    bind.add_argument('path')
    args = parser.parse_args(argv)
    try:
        if args.command == 'create':
            result = create_profile(args.name, args.root)
        elif args.command == 'show':
            result = facts_for(args.profile, _read(args.library) if args.library else None, args.root)
        elif args.command == 'confirm':
            value = json.loads(args.value)
            _value(args.kind, value)
            scope = None
            if args.library:
                resources = value if args.kind == 'shared_station' else (
                    value['retainedResourceIds'] if args.kind == 'setup_access' else [])
                definitions = value['independentDefinitionIds'] if args.kind == 'setup_access' else []
                scope = capture_scope(_read(args.library), resources, definitions)
            source = {'role': 'user', 'statement': args.source}
            if args.conversation_id:
                source['conversationId'] = args.conversation_id
            result = record_fact(args.profile, kind=args.kind, value=value, source=source,
                                 scope=scope, supersedes=args.supersedes, root=args.root)
        elif args.command == 'forget':
            forget_fact(args.profile, args.fact, args.root)
            result = {'forgotten': args.fact}
        else:
            bind_history(args.profile, args.path, args.root)
            result = {'profileId': args.profile, 'historyPath': _history_path(args.path)}
    except (ValueError, OSError, RuntimeError, KeyError, TypeError) as error:
        parser.exit(2, f'User memory error: {error}\n')
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
