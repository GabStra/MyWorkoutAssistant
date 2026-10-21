"""Run independent read-only lookups together; commit their results in the shell."""
import threading
import copy
import json
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextvars import copy_context
from queue import Empty, SimpleQueue
from jsonschema import validate, ValidationError

from .api_metrics import api_metrics_scope
from .cancellation import run_cancellable
from .exercise_library_tools import execute_library_searches, get_exercise_candidates
from .planning_tools import require_approved_requirements, planning_tool_failure, library_fingerprint
from .training_history import GET_TRAINING_EVIDENCE_TOOL


LOOKUP_TOOLS = frozenset(('search_exercise_library', 'get_training_evidence', 'get_exercise_candidates'))


def _history_results(calls, equipment, client, history, on_result=None, messages=()):
    references = list(dict.fromkeys(ref for _, args in calls for ref in args['definition_ids']))
    common, by_reference, load_options, errors_by_reference = {}, {}, {}, {}
    results = {}
    functions = {call['id']: call['function'] for message in messages for call in message.get('tool_calls', [])}
    page = (calls[0][1].get('session_offset', 0), calls[0][1].get('session_limit', 1))
    fingerprint = library_fingerprint(equipment)
    last_user = max((index for index, message in enumerate(messages) if message.get('role') == 'user'), default=-1)
    for index, message in enumerate(messages):
        function = functions.get(message.get('tool_call_id'), {})
        if function.get('name') != 'get_training_evidence' or not getattr(history, 'fingerprint', None):
            continue
        try:
            args = json.loads(function.get('arguments', '{}'))
            payload = json.loads(message.get('content', '{}'))
        except (ValueError, TypeError):
            continue
        if (not isinstance(args, dict) or not isinstance(payload, dict) or payload.get('historyFingerprint') != history.fingerprint
                or payload.get('libraryFingerprint') != fingerprint
                or (args.get('session_offset', 0), args.get('session_limit', 1)) != page):
            continue
        for item in payload.get('exercises', []):
            if item.get('relatedHistoryStatus') == 'checked_local_unconfirmed' and index < last_user:
                continue
            if item.get('reference') in references:
                by_reference[item['reference']] = copy.deepcopy(item)
        load_options.update(copy.deepcopy(payload.get('equipmentLoadOptions', {})))
        common.update({key: payload[key] for key in ('historyFingerprint', 'libraryFingerprint', 'evidenceFormat') if key in payload})

    def finish_ready():
        for key, args in calls:
            requested = list(dict.fromkeys(args['definition_ids']))
            if key in results:
                continue
            supplied = [by_reference[ref] for ref in requested if ref in by_reference]
            pending = [ref for ref in requested if ref not in by_reference and ref not in errors_by_reference]
            if pending:
                if supplied and on_result:
                    on_result(key, {**common, 'exercises': supplied, 'equipmentLoadOptions': dict(load_options),
                                    'inProgress': True, 'pendingDefinitionIds': pending})
                continue
            failed = next((errors_by_reference[ref] for ref in requested if ref in errors_by_reference), None)
            results[key] = ({**planning_tool_failure('get_training_evidence', failed), **common,
                            'exercises': supplied, 'equipmentLoadOptions': dict(load_options)} if failed else
                {**common, 'exercises': [by_reference[ref] for ref in requested],
                 'equipmentLoadOptions': dict(load_options)})
            if on_result:
                on_result(key, results[key])

    finish_ready()
    missing = [ref for ref in references if ref not in by_reference]
    for start in range(0, len(missing), 12):
        chunk = missing[start:start + 12]
        try:
            if history is None:
                raise ValueError('No history backup is loaded.')
            arguments = {**calls[0][1], 'definition_ids': chunk}
            result = history.evidence(arguments, equipment, client=client)
            common = {key: value for key, value in result.items() if key not in ('exercises', 'equipmentLoadOptions')}
            by_reference.update((item['reference'], item) for item in result.get('exercises', []))
            load_options.update(result.get('equipmentLoadOptions', {}))
            for ref in chunk:
                if ref not in by_reference:
                    errors_by_reference[ref] = RuntimeError(f'History lookup returned no result for {ref}.')
        except Exception as error:
            errors_by_reference.update((ref, error) for ref in chunk)
        finish_ready()
    return results


def execute_lookup_batch(calls, equipment, client, messages, history=None, logger=None, on_result=None):
    """Only already-independent lookups may enter this batch; mutations stay sequential."""
    require_approved_requirements(messages)
    if not calls:
        raise ValueError('A lookup batch must contain at least one lookup.')
    if any(name not in LOOKUP_TOOLS for _, name, _ in calls):
        raise ValueError('A lookup batch cannot contain mutations or generation.')
    searches = [(key, args) for key, name, args in calls if name == 'search_exercise_library']
    completed = SimpleQueue()
    jobs = []
    if searches:
        jobs.append(('search_exercise_library', [key for key, _ in searches],
                     lambda: execute_library_searches(searches, equipment, client, messages,
                                                      on_result=lambda key, payload: completed.put((key, payload)))))
    history_groups, results = {}, {}
    definitions = sorted((equipment or {}).get('exerciseDefinitions') or [], key=lambda item: item['id'])
    known_references = {f'LIBRARY_{index}' for index in range(len(definitions))}
    for key, name, args in calls:
        if name == 'get_training_evidence':
            try:
                validate(args, GET_TRAINING_EVIDENCE_TOOL['function']['parameters'])
            except ValidationError as error:
                results[key] = planning_tool_failure(name, error)
                continue
            unknown = sorted(set(args['definition_ids']) - known_references)
            if unknown:
                results[key] = planning_tool_failure(name, ValueError(f'Unknown exercise library references: {unknown}'))
                continue
            page = (args.get('session_offset', 0), args.get('session_limit', 1))
            history_groups.setdefault(page, []).append((key, args))
        elif name == 'get_exercise_candidates':
            jobs.append((name, [key], lambda key=key, args=args: {
                key: get_exercise_candidates(args, equipment, messages)}))
    for group in history_groups.values():
        jobs.append(('get_training_evidence', [key for key, _ in group],
                     lambda group=group: _history_results(group, equipment, client, history, messages=messages,
                         on_result=lambda key, payload: completed.put((key, payload)))))
    if on_result:
        for key, payload in results.items():
            on_result(key, payload)
    if not jobs:
        return results
    cancelled = threading.Event()
    pool = ThreadPoolExecutor(max_workers=min(3, len(jobs)))
    checkpointed = {}
    def run(name, keys, function):
        with api_metrics_scope(logger, name):
            try:
                outcome = run_cancellable(function, cancel_event=cancelled)
            except Exception as error:
                outcome = {key: planning_tool_failure(name, error) for key in keys}
            for key, payload in outcome.items():
                completed.put((key, payload))

    def checkpoint_completed():
        while True:
            try:
                key, payload = completed.get_nowait()
            except Empty:
                return
            if checkpointed.get(key) != payload:
                checkpointed[key] = payload
                if not payload.get('inProgress'):
                    results[key] = payload
                if on_result:
                    on_result(key, payload)

    try:
        pending = {pool.submit(copy_context().run, run, *job) for job in jobs}
        while pending:
            done, pending = wait(pending, timeout=0.1, return_when=FIRST_COMPLETED)
            checkpoint_completed()
            for future in done:
                future.result()
            checkpoint_completed()
    except BaseException:
        cancelled.set()
        checkpoint_completed()
        raise
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return results
