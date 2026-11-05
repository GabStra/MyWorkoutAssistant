import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import validate, ValidationError

from workout_generator_pkg import api_client
from workout_generator_pkg.api_metrics import api_metrics_scope


def stream_client(create, options):
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    client.with_options = lambda **kwargs: options.append(kwargs) or client
    return client


def chunk(content, finish='stop', usage=None):
    return SimpleNamespace(model='configured-model', usage=usage,
        choices=[SimpleNamespace(finish_reason=finish, delta=SimpleNamespace(content=content))])


@pytest.mark.parametrize('delivery', ['json', 'tool_arguments'])
def test_json_mode_marker_normalization_preserves_contracts_and_semantic_nested_type(delivery):
    contracts = [{'definition_id': 'LIBRARY_182', 'satisfiesCoverage': ['transverse_plane', 'unilateral'],
        'type': 'coverage_contract'}, {'definition_id': 'LIBRARY_193', 'satisfiesCoverage': ['calves']}]
    schema = {'type': 'object', 'properties': {'contracts': {'type': 'array', 'items': {'type': 'object'}}},
        'required': ['contracts'], 'additionalProperties': False}
    original = {'type': 'json_object', 'contracts': contracts}
    raw = json.dumps(original)
    if delivery == 'json':
        content, result, syntax_repaired = api_client._decode_json_with_terminal_closer_repair(raw, schema)
        assert not syntax_repaired and json.loads(content) == result
    else:
        result = json.loads(api_client._normalize_strict_tool_arguments(raw, schema))
    validate(result, schema)
    assert result == {'contracts': contracts}
    assert original == {'type': 'json_object', 'contracts': contracts}


@pytest.mark.parametrize('payload', [
    {'type': 'other_format', 'contracts': []},
    {'type': 'json_object', 'contracts': [], 'unexpected': 'not transport metadata'},
])
def test_transport_normalization_does_not_accept_arbitrary_extra_fields(payload):
    schema = {'type': 'object', 'properties': {'contracts': {'type': 'array'}},
        'required': ['contracts'], 'additionalProperties': False}
    _, result, _ = api_client._decode_json_with_terminal_closer_repair(json.dumps(payload), schema)
    with pytest.raises(ValidationError):
        validate(result, schema)


@pytest.mark.parametrize('declared_type', ['json_object', 'coverage_contract'])
def test_transport_normalization_preserves_declared_semantic_type(declared_type):
    schema = {'type': 'object', 'properties': {'type': {'enum': ['json_object', 'coverage_contract']}},
        'required': ['type'], 'additionalProperties': False}
    raw = json.dumps({'type': declared_type})
    content, result, _ = api_client._decode_json_with_terminal_closer_repair(raw, schema)
    assert result == {'type': declared_type} and content == raw
    assert json.loads(api_client._normalize_strict_tool_arguments(raw, schema)) == result
    validate(result, schema)


def test_stream_preserves_whitespace_budget_context_usage_and_closes(monkeypatch):
    requests, options, rows, closed = [], [], [], []

    class Stream:
        def __iter__(self):
            yield chunk(' \n{', None)
            yield chunk('"ok": true}\n ', usage={'prompt_tokens': 7, 'completion_tokens': 4})

        def close(self):
            closed.append(True)

    client = stream_client(lambda **kwargs: requests.append(kwargs) or Stream(), options)
    monkeypatch.setattr(api_client.LoadingIndicator, 'start', lambda self: None)
    monkeypatch.setattr(api_client.LoadingIndicator, 'stop', lambda self: None)
    with api_metrics_scope(SimpleNamespace(log=rows.append), 'bounded_json', submission_id='submission'):
        assert api_client.json_call_with_loading(client, [], max_tokens=123) == ' \n{"ok": true}\n '
    assert requests[0]['max_tokens'] == 123
    assert requests[0]['timeout'] is None
    assert options == [{'max_retries': 0}] and closed == [True]
    metric = json.loads(rows[-1].split(' ', 1)[1])
    assert metric['stage'] == 'bounded_json' and metric['completionTokens'] == 4
    assert metric['contextSizes']['messagesCharacters'] > 0


@pytest.mark.parametrize('name,expected', [
    ('chat_call_with_loading', (None, None, None)),
    ('json_call_with_loading', None), ('json_call_chat_max_with_loading', None),
    ('json_call_large_with_loading', None), ('json_call_reasoner_only_with_loading', None),
])
def test_loading_presets_cancel_once_and_clean_up(monkeypatch, name, expected):
    events = []
    monkeypatch.setattr(api_client.LoadingIndicator, 'start', lambda self: events.append('start'))
    monkeypatch.setattr(api_client.LoadingIndicator, 'stop', lambda self: events.append('stop'))

    def cancel(**kwargs):
        events.append('request')
        raise KeyboardInterrupt

    client = stream_client(cancel, [])
    assert getattr(api_client, name)(client, []) == expected
    assert events == ['start', 'request', 'stop']


@pytest.mark.parametrize('finish,content', [('length', '{'), ('stop', '{')])
def test_json_rejection_never_escalates_budget_or_thinking(monkeypatch, finish, content):
    requests, options = [], []
    monkeypatch.setattr(api_client.LoadingIndicator, 'start', lambda self: None)
    monkeypatch.setattr(api_client.LoadingIndicator, 'stop', lambda self: None)
    client = stream_client(lambda **kwargs: requests.append(kwargs) or iter([chunk(content, finish)]), options)
    with pytest.raises(ValueError, match='truncated|complete JSON'):
        api_client.json_call_with_loading(client, [], max_tokens=37)
    assert len(requests) == 1 and requests[0]['max_tokens'] == 37
    assert 'reasoning_effort' not in requests[0]


def test_connection_recovery_and_reasoning_recovery_share_one_attempt_cap(monkeypatch):
    attempts = []

    class ProviderConnectionError(Exception):
        pass

    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
        content=None, reasoning_content='thinking', tool_calls=None))],
        usage={'completion_tokens': 11, 'completion_tokens_details': {'reasoning_tokens': 11}})
    truncated = api_client.TruncatedResponseError(response, 11, 'low')

    def call(*args, **kwargs):
        attempts.append((kwargs['reasoning_effort'], kwargs['max_tokens']))
        if len(attempts) == 1:
            raise ProviderConnectionError('offline')
        raise truncated

    monkeypatch.setattr(api_client, '_chat_call_once', call)
    monkeypatch.setattr(api_client, '_log_connection_error', lambda *args: None)
    monkeypatch.setattr(api_client.time, 'sleep', lambda _: None)
    with pytest.raises(api_client.TruncatedResponseError) as caught:
        api_client.call_model(None, [], reasoning_effort='low', max_tokens=11)
    assert caught.value.diagnostics['cause'] == 'reasoning_budget_exhausted'
    assert attempts == [('low', 11), ('low', 11)]


def test_http_error_is_preserved_without_connection_retry(monkeypatch):
    import httpx
    from openai import BadRequestError

    requests, options, rows = [], [], []
    error = BadRequestError('invalid request', response=httpx.Response(400,
        request=httpx.Request('POST', 'http://localhost/v1/chat/completions')), body={'error': 'bad schema'})

    def fail(**kwargs):
        requests.append(kwargs)
        raise error

    with api_metrics_scope(SimpleNamespace(log=rows.append), 'http_rejection'):
        with pytest.raises(BadRequestError) as caught:
            api_client.json_call(stream_client(fail, options), [], max_tokens=19)
    assert caught.value is error and len(requests) == 1
    assert json.loads(rows[-1].split(' ', 1)[1])['errorType'] == 'BadRequestError'


def test_stream_deadline_records_failure_before_network_finishes():
    release = threading.Event()
    completed = threading.Event()
    rows, requests, options = [], [], []

    def create(**kwargs):
        requests.append(kwargs)
        release.wait(2)
        completed.set()
        return iter([chunk('{}')])

    try:
        with api_metrics_scope(SimpleNamespace(log=rows.append), 'deadline'):
            with pytest.raises(TimeoutError, match='No automatic retry'):
                api_client.call_model(stream_client(create, options), [], json_mode=True,
                    reasoning_effort=None, max_tokens=12, timeout=0.01)
        metric = json.loads(rows[-1].split(' ', 1)[1])
        assert not completed.is_set()
        assert metric['outcome'] == 'failure' and metric['errorType'] == 'TimeoutError'
        assert metric['timeoutSeconds'] == requests[0]['timeout'] == 0.01
        assert len(requests) == 1
    finally:
        release.set()
        assert completed.wait(1)


def test_connection_diagnostics_exclude_authorization_headers(tmp_path):
    import httpx

    error = ConnectionError('offline')
    error.request = httpx.Request('POST', 'http://localhost/v1/chat/completions',
        headers={'authorization': 'Bearer private-key', 'content-type': 'application/json'})
    path = api_client._log_connection_error(error, 1, 2, script_dir=str(tmp_path))
    payload = json.loads(Path(path).read_text(encoding='utf-8'))
    assert payload['request_info']['headers'] == {'content-type': 'application/json'}
    assert 'private-key' not in json.dumps(payload)
