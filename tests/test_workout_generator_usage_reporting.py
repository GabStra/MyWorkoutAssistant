import json
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from workout_generator_pkg.usage_reporting import quote_cost, summarize_usage, report_usage


def event(start='2026-10-18T02:00:00+00:00', end=None):
    return {'event':'api_request','requestId':'one','model':'deepseek-flash','stage':'review',
        'requestStartedAtUTC':start,'requestFinishedAtUTC':end or (datetime.fromisoformat(start)+timedelta(seconds=1)).isoformat(),
        'outcome':'success','promptTokens':1_000_000,'completionTokens':300_000,'reasoningTokens':140_000,
        'cacheHitTokens':800_000,'cacheMissTokens':200_000}


@pytest.mark.parametrize('start,end,minimum,maximum',[
    ('2026-10-18T02:00:00+00:00',None,'0.2124','0.2124'),  # Sunday.
    ('2026-10-19T02:00:00+00:00',None,'0.4248','0.4248'),
    ('2026-10-01T02:00:00+00:00',None,'0.2124','0.2124'),  # Verified Chinese holiday.
    ('2026-10-19T00:59:59+00:00','2026-10-19T01:00:01+00:00','0.2124','0.4248'),
    ('2027-01-06T02:00:00+00:00',None,'0.2124','0.4248'),  # Holiday calendar not yet verified.
])
def test_cost_uses_cache_split_period_and_verified_calendar(start,end,minimum,maximum):
    cost = quote_cost(event(start,end))
    assert Decimal(cost['minimum']) == Decimal(minimum)
    assert Decimal(cost['maximum']) == Decimal(maximum)


def test_total_deduplicates_resumed_events_without_double_counting_reasoning_or_cache():
    request = event()
    started = {**request,'event':'api_request_started'}
    summary = summarize_usage([started,request,request])
    assert summary['requests'] == 1 and summary['totalTokens'] == 1_300_000
    assert summary['reportedTokenTotals']['reasoningTokens'] == 140_000
    assert summary['costEstimateUSD']['complete']
    assert Decimal(summary['costEstimateUSD']['knownRequestsMinimum']) == Decimal('0.2124')


def test_missing_usage_pending_requests_and_legacy_records_never_imply_zero_consumption(tmp_path):
    pending = {'event':'api_request_started','requestId':'pending','model':'deepseek-flash'}
    failed = {**event(),'requestId':'failure','promptTokens':None,'completionTokens':None,'outcome':'failure'}
    legacy = {k:v for k,v in event().items() if k != 'requestId'}
    summary = summarize_usage([pending,failed,legacy])
    assert summary['pendingRequests'] == summary['requestsMissingUsage'] == 1
    assert summary['completedFailureMissingUsage'] == 1
    assert summary['unfinishedRequests'] == 1
    assert not summary['tokenTotalsComplete'] and summary['totalTokens'] is None
    assert summary['reportedTokenTotals']['promptTokens'] == 1_000_000
    assert summary['costEstimateUSD']['requestsUnpriced'] == 2
    assert summary['costEstimateUSD']['completedRequestsUnpriced'] == 1
    assert summary['costEstimateUSD']['unfinishedRequestsUnpriced'] == 1
    no_usage = summarize_usage([failed])
    assert no_usage['costEstimateUSD']['knownRequestsMinimum'] is None
    path = tmp_path/'failure.log'
    path.write_text('[api_metric] '+json.dumps(failed),encoding='utf-8')
    printed=[]
    report_usage(SimpleNamespace(log_filepath=path,log_print=printed.append))
    assert 'completed failure(s) missing token usage' in printed[0]
    assert 'pending or abandoned' not in printed[0]
    assert 'unavailable' in printed[0] and '$0.000000' not in printed[0]


def test_unknown_prices_and_cache_splits_are_explicit():
    request = event()
    request.update(cacheHitTokens=None,cacheMissTokens=None)
    cost = quote_cost(request)
    assert not cost['cacheSplitKnown'] and Decimal(cost['minimum']) < Decimal(cost['maximum'])
    request['model'] = 'unpriced-model'
    assert quote_cost(request) is None


def test_report_survives_resume_and_preserves_logs_without_prompt_data(tmp_path):
    path = tmp_path/'conversation.log'
    request = event()
    rows = [{'event':'api_request_started','requestId':'one'},request]
    text = '[request] review: PRIVATE PROMPT\n'+'\n'.join('[api_metric] '+json.dumps(row) for row in rows)
    path.write_text(text,encoding='utf-8')
    printed=[]
    logger=SimpleNamespace(log_filepath=str(path),log_print=printed.append)
    first=report_usage(logger)
    second=report_usage(logger)
    assert first == second and first['totalTokens'] == 1_300_000
    assert path.read_text(encoding='utf-8') == text
    report=path.with_suffix('.usage.json').read_text(encoding='utf-8')
    assert 'PRIVATE' not in report and 'Run usage:' in printed[0]


def test_report_write_error_does_not_fail_generation(tmp_path,monkeypatch):
    from workout_generator_pkg import usage_reporting
    path=tmp_path/'conversation.log'
    path.write_text('[api_metric] '+json.dumps(event()),encoding='utf-8')
    printed=[]
    def fail(*args):
        raise OSError('disk full')
    monkeypatch.setattr(usage_reporting,'write_json_atomic',fail)
    summary=report_usage(SimpleNamespace(log_filepath=path,log_print=printed.append))
    assert summary['completedRequests'] == 1
    assert any('metrics remain' in line for line in printed)


def test_usage_report_reads_production_shell_logger_after_resume(tmp_path):
    from workout_generator_pkg.deps import resolve_shell_deps
    path=tmp_path/'conversation.log'
    factory=resolve_shell_deps().ConversationLogger
    first=factory(str(path))
    request=event()
    first.log('[api_metric] '+json.dumps({'event':'api_request_started','requestId':'one'}))
    first.log('[api_metric] '+json.dumps(request))
    resumed=factory(str(path))
    assert report_usage(resumed)['totalTokens']==1_300_000
    assert path.with_suffix('.usage.json').exists()
