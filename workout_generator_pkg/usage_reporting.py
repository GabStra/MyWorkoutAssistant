"""Provider-reported token totals and reproducible model-token cost estimates."""
import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from .json_io import write_json_atomic


PRICE_SOURCE = 'https://api-docs.deepseek.com/quick_start/pricing/'
PRICE_VERIFIED = '2026-10-18'
HOLIDAY_SOURCE = 'https://www.beijing.gov.cn/fuwu/bmfw/sy/jrts/202511/t20251104_4258838.html'
# USD per million cached-input, uncached-input and output tokens; peak rates are double.
RATES = {'deepseek-flash': ('0.003', '0.15', '0.60'), 'deepseek-v4-pro': ('0.022', '0.66', '1.98')}
ALIASES = {'deepseek-v4-flash': 'deepseek-flash', 'deepseek-v4-flash-vision-exp': 'deepseek-flash'}
HOLIDAYS_2026 = [('01-01','01-03'), ('02-15','02-23'), ('04-04','04-06'), ('05-01','05-05'),
                 ('06-19','06-21'), ('09-25','09-27'), ('10-01','10-07')]
METRIC = re.compile(r'\[api_metric\]\s+(\{.*\})\s*$')


def usage_events(lines):
    """Read only structured metrics; prompts and model text never enter the report."""
    for line in lines:
        match = METRIC.search(line)
        if not match:
            continue
        try:
            event = json.loads(match.group(1))
        except (ValueError, TypeError):
            continue
        if isinstance(event, dict) and event.get('event') in ('api_request', 'api_request_started', 'submission_rejected'):
            yield event


def _count(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _periods(moment):
    if moment.weekday() >= 5 or not (1 <= moment.hour < 4 or 6 <= moment.hour < 10):
        return {0}
    if moment.year != 2026:
        return {0, 1}  # The next official holiday calendar must be verified before assuming weekday peak billing.
    day = moment.strftime('%m-%d')
    return {0 if any(start <= day <= end for start, end in HOLIDAYS_2026) else 1}


def quote_cost(event):
    """A rate-card calculation, never a claim about the provider's final invoice."""
    model = event.get('model')
    rates = RATES.get(ALIASES.get(model,model)) if isinstance(model,str) else None
    prompt, output = event.get('promptTokens'), event.get('completionTokens')
    if not rates or not _count(prompt) or not _count(output):
        return None
    hit, miss = event.get('cacheHitTokens'), event.get('cacheMissTokens')
    if not _count(hit) and _count(miss) and miss <= prompt:
        hit = prompt - miss
    if not _count(miss) and _count(hit) and hit <= prompt:
        miss = prompt - hit
    cache_known = _count(hit) and _count(miss) and hit + miss == prompt
    start, end = event.get('requestStartedAtUTC'), event.get('requestFinishedAtUTC')
    periods = {0, 1}
    if start and end:
        try:
            first, last = [datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc) for value in (start,end)]
            if first <= last:
                periods = _periods(first) | _periods(last)
                day = first.replace(hour=0,minute=0,second=0,microsecond=0)
                while day <= last:
                    for hour in (0,1,4,6,10):
                        boundary = day + timedelta(hours=hour)
                        if first <= boundary <= last:
                            periods |= _periods(boundary)
                    day += timedelta(days=1)
        except (ValueError, TypeError, OverflowError):
            pass
    cached, uncached, emitted = map(Decimal,rates)
    low_hit, high_hit = (hit,hit) if cache_known else (prompt,0)
    amounts = [(Decimal(low_hit)*cached + Decimal(prompt-low_hit)*uncached + Decimal(output)*emitted),
               (Decimal(high_hit)*cached + Decimal(prompt-high_hit)*uncached + Decimal(output)*emitted)]
    return {'currency':'USD', 'minimum':str(amounts[0] * (2 ** min(periods)) / 1_000_000),
            'maximum':str(amounts[1] * (2 ** max(periods)) / 1_000_000),
            'rateCardVerifiedAt':PRICE_VERIFIED, 'source':PRICE_SOURCE,
            'cacheSplitKnown':cache_known, 'period': 'off_peak' if periods == {0} else 'peak' if periods == {1} else 'uncertain'}


def summarize_usage(events):
    events = list(events)
    started, completed, legacy = {}, {}, []
    for event in events:
        identifier = event.get('requestId')
        if event.get('event') == 'api_request_started' and identifier:
            started[identifier] = event
        elif event.get('event') == 'api_request':
            if identifier:
                completed[identifier] = event
            else:
                legacy.append(event)
    pending = set(started) - set(completed)
    rows = [*completed.values(), *legacy]
    totals = {field:sum(row[field] for row in rows if _count(row.get(field)))
              for field in ('promptTokens','completionTokens','reasoningTokens','cacheHitTokens','cacheMissTokens')}
    missing = sum(not (_count(row.get('promptTokens')) and _count(row.get('completionTokens'))) for row in rows)
    costs = [row.get('costEstimate') or quote_cost(row) for row in rows]
    priced = [cost for cost in costs if cost]
    untracked = len(legacy) + len(set(completed) - set(started))
    exact_usage = bool(rows) and not missing and not pending and not untracked
    failed_missing_usage = sum(row.get('outcome') == 'failure'
        and not (_count(row.get('promptTokens')) and _count(row.get('completionTokens'))) for row in rows)
    other_missing_usage = missing - failed_missing_usage
    unknown_price_with_usage = sum(cost is None and _count(row.get('promptTokens'))
        and _count(row.get('completionTokens')) for row, cost in zip(rows, costs))
    unpriced_completed = len(rows) - len(priced)
    return {'requests':len(rows)+len(pending), 'completedRequests':len(rows), 'pendingRequests':len(pending),
        'unfinishedRequests':len(pending),
        'pendingRequestDetails':[started[key] for key in sorted(pending)],
        'requestsMissingUsage':missing, 'legacyRequestsWithoutStartTracking':untracked,
        'completedFailureMissingUsage':failed_missing_usage,
        'otherCompletedMissingUsage':other_missing_usage,
        'reportedTokenTotals':totals, 'tokenTotalsComplete':exact_usage,
        'tokenFieldsMissing':{field:sum(not _count(row.get(field)) for row in rows) for field in totals},
        'totalTokens':totals['promptTokens']+totals['completionTokens'] if exact_usage else None,
        'reasoningAccounting':'Reasoning is a subset of completion tokens and is not added again.',
        'outcomes':dict(Counter(row.get('outcome','unknown') for row in rows)),
        'stages':dict(Counter(row.get('stage','unscoped') for row in rows)),
        'models':dict(Counter(row.get('model','unknown') for row in rows)),
        'costEstimateUSD':{'knownRequestsMinimum':str(sum((Decimal(c['minimum']) for c in priced),Decimal(0))) if priced else None,
            'knownRequestsMaximum':str(sum((Decimal(c['maximum']) for c in priced),Decimal(0))) if priced else None,
            'requestsUnpriced':unpriced_completed+len(pending),
            'completedRequestsUnpriced':unpriced_completed,
            'unfinishedRequestsUnpriced':len(pending),
            'completedFailureMissingUsage':failed_missing_usage,
            'otherCompletedMissingUsage':other_missing_usage,
            'requestsWithUsageButUnknownPrice':unknown_price_with_usage,
            'complete':exact_usage and len(priced)==len(rows),
            'basis':'Published model-token rate card, not an invoice or balance deduction.',
            'rateCardVerifiedAt':PRICE_VERIFIED,'source':PRICE_SOURCE,'holidaySource':HOLIDAY_SOURCE},
        'requestsDetail':rows, 'stageRejections': summarize_rejections(events)}


def summarize_rejections(events):
    """Count rejected calls once, even when multiple validators reject their output."""
    requests, submissions, responses, rejections, tracked = {}, {}, {}, [], set()
    for index, event in enumerate(events):
        kind = event.get('event')
        if kind in ('api_request', 'api_request_started'):
            identifier = event.get('requestId') or f'legacy_{index}'
            requests[identifier] = event.get('stage', 'unscoped')
            if event.get('rejectionTracking'):
                tracked.add(identifier)
            for submission in event.get('submissionIds', []):
                submissions[submission] = identifier
            if event.get('responseFingerprint'):
                responses[(event.get('stage'), event['responseFingerprint'])] = identifier
        elif kind == 'submission_rejected':
            identifier = (event.get('requestId')
                          or responses.get((event.get('stage'), event.get('responseFingerprint')))
                          or submissions.get(event.get('submissionId')))
            rejections.append((event, identifier))
    stages = {stage: {'calls': 0, 'callsWithRejectionTracking': 0, 'rejectedCalls': 0, 'rejectedSubmissions': 0,
                     'reasonClasses': {key: 0 for key in ('schema', 'reference-ID', 'numerical', 'other')}}
              for stage in requests.values()}
    for identifier, stage in requests.items():
        stages[stage]['calls'] += 1
        stages[stage]['callsWithRejectionTracking'] += identifier in tracked
    rejected_calls, seen, seen_submissions, unmatched = set(), set(), set(), 0
    for event, identifier in rejections:
        if identifier not in requests:
            unmatched += 1
            continue
        stage = requests[identifier]
        reason = event['reasonClass']
        key = (identifier, event.get('submissionId'), reason)
        if key in seen:
            continue
        seen.add(key)
        submission = (identifier, event.get('submissionId'))
        if submission not in seen_submissions:
            stages[stage]['rejectedSubmissions'] += 1
            seen_submissions.add(submission)
        stages[stage]['reasonClasses'][reason] += 1
        rejected_calls.add(identifier)
    for identifier in rejected_calls:
        stages[requests[identifier]]['rejectedCalls'] += 1
    for row in stages.values():
        row['rejectionRate'] = (row['rejectedCalls'] / row['calls']
            if row['calls'] and row['callsWithRejectionTracking'] == row['calls'] else None)
    top = sorted((stage for stage in stages if stages[stage]['rejectedCalls']),
                 key=lambda stage: (-stages[stage]['rejectedCalls'], stage))[:2]
    return {'stages': stages, 'topTwoStages': top, 'unmatchedRejectionEvents': unmatched,
            'measurement': 'Explicit validation rejections; semantic review findings and provider failures are not rejections.'}


def report_usage(logger):
    path = getattr(logger,'log_filepath',None)
    if not isinstance(path,(str,Path)) or not Path(path).exists():
        return None
    try:
        summary = summarize_usage(usage_events(Path(path).read_text(encoding='utf-8',errors='replace').splitlines()))
    except OSError as error:
        logger.log_print(f'Usage report unavailable: {error}')
        return None
    if not summary['requests']:
        return None
    output = Path(path).with_suffix('.usage.json')
    try:
        write_json_atomic(output,summary)
    except OSError as error:
        logger.log_print(f'Could not save usage report: {error}. Request metrics remain in {path}.')
    total = summary['totalTokens']
    tokens = f'{total:,}' if total is not None else f"at least {summary['reportedTokenTotals']['promptTokens']+summary['reportedTokenTotals']['completionTokens']:,} reported"
    cost = summary['costEstimateUSD']
    if cost['knownRequestsMinimum'] is None:
        amount = 'unavailable (no request costs could be priced)'
    else:
        low, high = Decimal(cost['knownRequestsMinimum']), Decimal(cost['knownRequestsMaximum'])
        amount = f'${low:.6f}' if low == high else f'${low:.6f}-${high:.6f}'
    incomplete = []
    if summary['completedFailureMissingUsage']:
        incomplete.append(f"{summary['completedFailureMissingUsage']} completed failure(s) missing token usage")
    if summary['otherCompletedMissingUsage']:
        incomplete.append(f"{summary['otherCompletedMissingUsage']} other completed request(s) missing token usage")
    if cost['requestsWithUsageButUnknownPrice']:
        incomplete.append(f"{cost['requestsWithUsageButUnknownPrice']} request(s) with usage but unknown price")
    if summary['unfinishedRequests']:
        incomplete.append(f"{summary['unfinishedRequests']} started request(s) without a terminal event (pending or abandoned)")
    if summary['legacyRequestsWithoutStartTracking']:
        incomplete.append(f"{summary['legacyRequestsWithoutStartTracking']} legacy record(s)")
    partial_detail = ', '.join(incomplete) or f"{cost['requestsUnpriced']} request(s) unpriced"
    logger.log_print(f"Run usage: {tokens} tokens; model-token cost estimate {amount}"
                     + (f' (partial; {partial_detail}).' if not cost['complete'] else '.'))
    logger.log_print(f'Usage report: {output}')
    return summary
