import copy
import threading
from types import SimpleNamespace

import pytest

from test_workout_generator_planning_tools import planning_case, requirement_messages
from workout_generator_pkg.lookup_batch import execute_lookup_batch


def test_invalid_history_reference_does_not_poison_valid_request():
    gear, _, stored, _ = planning_case()
    calls = []

    def evidence(arguments, equipment, client=None):
        calls.append(arguments['definition_ids'])
        return {'exercises': [{'reference': ref} for ref in arguments['definition_ids']]}

    requests = [
        ('valid', 'get_training_evidence', {'definition_ids': ['LIBRARY_0']}),
        ('invalid', 'get_training_evidence', {'definition_ids': ['LIBRARY_999']}),
    ]
    results = execute_lookup_batch(requests, gear, None, requirement_messages(stored),
                                   SimpleNamespace(evidence=evidence))

    assert calls == [['LIBRARY_0']]
    assert results['valid']['exercises'] == [{'reference': 'LIBRARY_0'}]
    assert results['invalid']['passed'] is False
    assert results['invalid']['errors']
    assert 'call get_training_evidence again' in results['invalid']['errors'][0]['repair']


def test_later_history_chunk_failure_preserves_completed_unaffected_request():
    gear, _, stored, _ = planning_case()
    definitions = copy.deepcopy(gear['exerciseDefinitions'])
    while len(definitions) < 13:
        definition = copy.deepcopy(definitions[0])
        definition['id'] = f'zzzz-test-{len(definitions)}'
        definitions.append(definition)
    gear['exerciseDefinitions'] = definitions
    calls = []

    def evidence(arguments, equipment, client=None):
        refs = arguments['definition_ids']
        calls.append(refs)
        if 'LIBRARY_12' in refs:
            raise RuntimeError('history store unavailable for this chunk')
        return {'exercises': [{'reference': ref} for ref in refs]}

    requests = [
        ('first_chunk', 'get_training_evidence', {'definition_ids': [f'LIBRARY_{i}' for i in range(12)]}),
        ('later_chunk', 'get_training_evidence', {'definition_ids': ['LIBRARY_12']}),
    ]
    results = execute_lookup_batch(requests, gear, None, requirement_messages(stored),
                                   SimpleNamespace(evidence=evidence))

    assert calls == [[f'LIBRARY_{i}' for i in range(12)], ['LIBRARY_12']]
    assert len(results['first_chunk']['exercises']) == 12
    assert results['later_chunk']['passed'] is False
    assert results['later_chunk']['errors']


def test_history_chunk_is_checkpointed_before_a_later_chunk_is_cancelled():
    gear, _, stored, _ = planning_case()
    gear['exerciseDefinitions'] = [{**copy.deepcopy(gear['exerciseDefinitions'][0]), 'id': f'exercise-{i:02d}'}
                                   for i in range(13)]
    checkpointed = threading.Event()
    saved = {}
    owner_thread = threading.get_ident()

    def evidence(arguments, equipment, client=None):
        if 'LIBRARY_12' in arguments['definition_ids']:
            assert checkpointed.wait(3), 'The first completed request must be saved before waiting for later work.'
            raise KeyboardInterrupt
        return {'exercises': [{'reference': ref} for ref in arguments['definition_ids']]}

    def checkpoint(key, payload):
        assert threading.get_ident() == owner_thread
        saved[key] = payload
        checkpointed.set()

    requests = [('completed', 'get_training_evidence', {'definition_ids': [f'LIBRARY_{i}' for i in range(12)]}),
                ('cancelled', 'get_training_evidence', {'definition_ids': ['LIBRARY_12']})]
    with pytest.raises(KeyboardInterrupt):
        execute_lookup_batch(requests, gear, None, requirement_messages(stored),
                             SimpleNamespace(evidence=evidence), on_result=checkpoint)
    assert len(saved['completed']['exercises']) == 12
    assert 'cancelled' not in saved


def test_missing_history_output_is_an_internal_error():
    gear, _, stored, _ = planning_case()
    results = execute_lookup_batch([('missing', 'get_training_evidence', {'definition_ids': ['LIBRARY_0']})],
        gear, None, requirement_messages(stored), SimpleNamespace(evidence=lambda *a, **k: {'exercises': []}))
    assert results['missing']['executionFailure']
    assert results['missing']['errors'][0]['code'] == 'tool_execution_failed'
