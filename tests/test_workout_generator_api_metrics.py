import json
import threading
from types import SimpleNamespace

from workout_generator_pkg import api_client
from workout_generator_pkg.api_metrics import api_metrics_scope
from workout_generator_pkg.cancellation import run_cancellable


def test_chat_call_records_safe_actual_usage_and_context_stage():
    rows = []
    logger = SimpleNamespace(log=rows.append)
    response = SimpleNamespace(
        model='deepseek-flash-actual',
        choices=[SimpleNamespace(finish_reason='stop', message=SimpleNamespace(content='secret response', tool_calls=None, reasoning_content='secret reasoning'))],
        usage=SimpleNamespace(model_dump=lambda: {
            'prompt_tokens': 1200, 'completion_tokens': 300,
            'completion_tokens_details': {'reasoning_tokens': 140},
            'prompt_tokens_details': {'cached_tokens': 800},
        }),
    )
    client = SimpleNamespace(
        with_options=lambda **_: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **__: response)))
    )
    with api_metrics_scope(logger, 'draft_repair'):
        assert api_client.chat_call(client, [{'role': 'user', 'content': 'secret prompt'}])[0] == 'secret response'
    metric = json.loads(rows[0].split(' ', 1)[1])
    assert metric['model'] == 'deepseek-flash-actual'
    assert metric['stage'] == 'draft_repair' and metric['outcome'] == 'success'
    assert metric['promptTokens'] == 1200 and metric['completionTokens'] == 300
    assert metric['reasoningTokens'] == 140 and metric['cacheHitTokens'] == 800
    assert 'secret' not in rows[0]


def test_metrics_context_survives_cancellable_worker_thread():
    rows = []
    logger = SimpleNamespace(log=rows.append)
    with api_metrics_scope(logger, 'semantic_search'):
        run_cancellable(lambda: api_client.record_api_metric({'event': 'check'}))
    metric = json.loads(rows[0].split(' ', 1)[1])
    assert metric['stage'] == 'semantic_search'


def test_failed_call_records_failure_without_prompt_content():
    rows = []
    client = SimpleNamespace(with_options=lambda **_: SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **__: (_ for _ in ()).throw(TimeoutError('late'))))))
    with api_metrics_scope(SimpleNamespace(log=rows.append), 'independent_review'):
        try:
            api_client.chat_call(client, [{'role': 'user', 'content': 'private'}])
        except TimeoutError:
            pass
        else:
            raise AssertionError('expected request failure')
    metric = json.loads(rows[0].split(' ', 1)[1])
    assert metric['outcome'] == 'failure' and metric['errorType'] == 'TimeoutError'
    assert 'private' not in rows[0]


def test_streaming_generation_records_provider_usage_and_actual_model():
    rows, requests = [], []
    usage = SimpleNamespace(model_dump=lambda: {
        'prompt_tokens': 900, 'completion_tokens': 240,
        'completion_tokens_details': {'reasoning_tokens': 100},
        'prompt_cache_hit_tokens': 700, 'prompt_cache_miss_tokens': 200,
    })
    chunks = [
        SimpleNamespace(model='deepseek-flash-actual', choices=[SimpleNamespace(
            finish_reason=None, delta=SimpleNamespace(content='{"ok":'))], usage=None),
        SimpleNamespace(model='deepseek-flash-actual', choices=[SimpleNamespace(
            finish_reason='stop', delta=SimpleNamespace(content='true}'))], usage=None),
        SimpleNamespace(model='deepseek-flash-actual', choices=[], usage=usage),
    ]

    def create(**kwargs):
        requests.append(kwargs)
        return iter(chunks)

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    with api_metrics_scope(SimpleNamespace(log=rows.append), 'exercise_emission'):
        content, finish = api_client.json_call_reasoner_only(client, [])
    metric = json.loads(rows[0].split(' ', 1)[1])
    assert content == '{"ok":true}' and finish == 'stop'
    assert requests[0]['stream_options'] == {'include_usage': True}
    assert metric['model'] == 'deepseek-flash-actual' and metric['stage'] == 'exercise_emission'
    assert metric['thinking'] == 'enabled' and metric['reasoningEffort'] == 'high'
    assert (metric['promptTokens'], metric['completionTokens'], metric['reasoningTokens']) == (900, 240, 100)
    assert metric['cacheHitTokens'] == 700 and metric['cacheMissTokens'] == 200


def test_each_stream_retry_attempt_gets_its_own_metric(monkeypatch):
    rows, calls = [], []

    class ProviderConnectionError(Exception):
        pass

    def create(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise ProviderConnectionError('connection lost')
        return iter([SimpleNamespace(model='deepseek-flash', choices=[SimpleNamespace(
            finish_reason='stop', delta=SimpleNamespace(content='{}'))], usage=SimpleNamespace(model_dump=lambda: {
                'prompt_tokens': 10, 'completion_tokens': 2, 'completion_tokens_details': {'reasoning_tokens': 0},
                'prompt_cache_hit_tokens': 0,
            }))])

    monkeypatch.setattr(api_client, '_log_connection_error', lambda *args, **kwargs: None)
    monkeypatch.setattr(api_client.time, 'sleep', lambda *_: None)
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    with api_metrics_scope(SimpleNamespace(log=rows.append), 'json_repair'):
        assert api_client.json_call(client, [], max_tokens=128) == ('{}', 'stop')
    metrics = [json.loads(row.split(' ', 1)[1]) for row in rows]
    assert len(calls) == len(metrics) == 2
    assert [metric['outcome'] for metric in metrics] == ['failure', 'success']
    assert all(metric['stage'] == 'json_repair' for metric in metrics)
    assert metrics[0]['promptTokens'] is None
    assert metrics[1]['cacheHitTokens'] == 0


def test_offline_benchmark_compares_logs_without_double_counting_nested_audit(tmp_path):
    from scripts.benchmark_workout_planning import analyze_log, render_comparison

    path = tmp_path / 'run.log'
    path.write_text('\n'.join([
        '[2026-10-16 10:00:00] [request] repair: private payload',
        '[2026-10-16 10:00:05] [api_metric] {"event":"api_request","stage":"draft","outcome":"success","elapsedSeconds":4,"promptTokens":100,"completionTokens":20,"reasoningTokens":9}',
        '[2026-10-16 10:00:05] Tool audit_workout_plan finished (5.00s)',
        '[2026-10-16 10:00:05] Planning paused: reviewer failed',
    ]), encoding='utf-8')
    summary = analyze_log(path)
    assert summary['status'] == 'paused' and summary['wallSeconds'] == 5
    assert summary['apiRequestSecondsSum'] == 4
    assert summary['plannerResponseSeconds'] == 0
    assert 'private payload' not in render_comparison([summary])


def test_benchmark_does_not_treat_missing_usage_as_zero(tmp_path):
    from scripts.benchmark_workout_planning import analyze_log

    path = tmp_path / 'partial.log'
    path.write_text('\n'.join([
        '[2026-10-16 10:00:00] [api_metric] {"event":"api_request","outcome":"success","elapsedSeconds":1,"promptTokens":100,"completionTokens":20,"reasoningTokens":10}',
        '[2026-10-16 10:00:01] [api_metric] {"event":"api_request","outcome":"failure","elapsedSeconds":1,"promptTokens":null,"completionTokens":null,"reasoningTokens":null}',
    ]), encoding='utf-8')
    summary = analyze_log(path)
    assert summary['promptTokens'] is None and summary['completionTokens'] is None
    assert summary['apiFailures'] == 1
