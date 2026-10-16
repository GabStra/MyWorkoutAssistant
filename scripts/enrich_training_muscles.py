"""Add reviewed training-muscle roles without changing exercise IDs, histories or body-map tags."""
import argparse
import copy
import hashlib
import json
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from exercise_library_generator_pkg.generator import _review_muscle_semantics_batch
from workout_generator_pkg.api_client import chat_call
from workout_generator_pkg.interactive_shell import _resolve_api_key
from workout_generator_pkg.json_io import write_json_atomic
from workout_generator_pkg.muscle_roles import TRAINING_MUSCLES, validate_training_muscles
from workout_generator_pkg.cancellation import run_cancellable


def apply_roles(payload, roles_by_id):
    result = copy.deepcopy(payload)
    def visit(node):
        if isinstance(node, list):
            for item in node:
                visit(item)
        elif isinstance(node, dict):
            identifier = node.get('exerciseDefinitionId') if node.get('type') == 'Exercise' else node.get('id')
            if identifier in roles_by_id:
                node['trainingMuscles'] = copy.deepcopy(roles_by_id[identifier])
            for key, value in list(node.items()):
                if key != 'trainingMuscles':
                    visit(value)
    visit(result)
    return result


def _load_roles(library, checkpoint):
    store = library.get('WorkoutStore', library)
    definitions = store['exerciseDefinitions']
    if len({item['id'] for item in definitions}) != len(definitions):
        raise ValueError('Library definition IDs must be unique.')
    fingerprint = hashlib.sha256(json.dumps({'version': 1, 'muscles': TRAINING_MUSCLES, 'library': library},
        sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    saved = json.loads(checkpoint.read_text(encoding='utf-8')) if checkpoint.exists() else {}
    if saved and saved.get('fingerprint') != fingerprint:
        raise ValueError('Checkpoint belongs to a different library or muscle policy; use another checkpoint file.')
    roles = saved.get('roles', {})
    if not isinstance(roles, dict) or set(roles) - {item['id'] for item in definitions}:
        raise ValueError('Checkpoint contains unknown definition IDs.')
    for value in roles.values():
        if not isinstance(value, dict):
            raise ValueError('Checkpoint is missing explicit training-muscle roles.')
        validate_training_muscles({'trainingMuscles': value})
    return fingerprint, roles


def enrich_library(client, library, checkpoint, progress=lambda message: None, *, batch_size=32, workers=3):
    store = library.get('WorkoutStore', library)
    definitions = store['exerciseDefinitions']
    fingerprint, roles = _load_roles(library, checkpoint)
    pending = [item for item in definitions if item['id'] not in roles]
    progress(f'Reviewing {len(pending)} remaining definitions in batches of {batch_size}, with up to {workers} workers.')
    def review(batch):
        def caller(client, messages, *args, **kwargs):
            return chat_call(client, messages, reasoning_effort='low', max_tokens=16384,
                             response_format={'type': 'json_object'})[0]
        return _review_muscle_semantics_batch(client, batch, store, caller)
    pool = ThreadPoolExecutor(max_workers=workers)
    cancelled = threading.Event()
    try:
        futures = [pool.submit(run_cancellable, review, pending[i:i+batch_size], cancel_event=cancelled)
                   for i in range(0, len(pending), batch_size)]
        for future in as_completed(futures):
            for definition in future.result():
                roles[definition['id']] = definition['trainingMuscles']
            write_json_atomic(checkpoint, {'fingerprint': fingerprint, 'roles': roles})
            progress(f'Training muscles: {len(roles)}/{len(definitions)} reviewed and saved.')
    finally:
        cancelled.set()
        pool.shutdown(wait=True, cancel_futures=True)
    return apply_roles(library, roles), roles


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--library-file', type=Path, required=True)
    parser.add_argument('--output-file', type=Path, required=True)
    parser.add_argument('--backup-file', type=Path)
    parser.add_argument('--backup-output-file', type=Path)
    parser.add_argument('--checkpoint-file', type=Path)
    args = parser.parse_args()
    if bool(args.backup_file) != bool(args.backup_output_file):
        parser.error('--backup-file and --backup-output-file must be provided together.')
    sources = {path.resolve() for path in (args.library_file, args.backup_file) if path}
    outputs = [path for path in (args.output_file, args.backup_output_file) if path]
    checkpoint = args.checkpoint_file or args.output_file.with_suffix('.progress.json')
    if len({path.resolve() for path in outputs + [checkpoint]}) != len(outputs) + 1:
        parser.error('Output and checkpoint paths must be distinct.')
    for path in outputs + [checkpoint]:
        if path.resolve() in sources or (path.exists() and not path.is_file()):
            parser.error(f'Refusing to overwrite an input or non-file destination: {path}')
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryFile(dir=path.parent):
                pass
        except OSError as error:
            parser.error(f'Cannot write destination {path}: {error}')
    library = json.loads(args.library_file.read_text(encoding='utf-8'))
    backup = json.loads(args.backup_file.read_text(encoding='utf-8')) if args.backup_file else None
    _, saved_roles = _load_roles(library, checkpoint)
    complete = set(saved_roles) == {item['id'] for item in library.get('WorkoutStore', library)['exerciseDefinitions']}
    payloads = [(args.output_file, library)] + ([(args.backup_output_file, backup)] if backup is not None else [])
    for path, payload in payloads:
        if path.exists() and (not complete or json.loads(path.read_text(encoding='utf-8')) != apply_roles(payload, saved_roles)):
            parser.error(f'Refusing to overwrite an output that does not match the completed checkpoint: {path}')
    if complete:
        enriched, roles = apply_roles(library, saved_roles), saved_roles
    else:
        from openai import OpenAI
        with OpenAI(api_key=_resolve_api_key(), base_url='https://api.deepseek.com', max_retries=0) as client:
            enriched, roles = enrich_library(client, library, checkpoint, lambda message: print(message, flush=True))
    payloads = [(args.output_file, enriched)] + ([(args.backup_output_file, apply_roles(backup, roles))] if backup is not None else [])
    for path, payload in payloads:
        if path.exists() and json.loads(path.read_text(encoding='utf-8')) != payload:
            parser.error(f'Refusing to overwrite a changed output: {path}')
    for path, payload in payloads:
        if not path.exists():
            write_json_atomic(path, payload)
    if args.backup_output_file:
        print(f'Backup saved: {args.backup_output_file}')
    print(f'Library saved: {args.output_file}')


if __name__ == '__main__':
    main()
