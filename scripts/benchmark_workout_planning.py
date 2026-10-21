"""Compare retained workout-planning logs without making model requests."""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
if __package__ in (None, ''):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from workout_generator_pkg.usage_reporting import usage_events, summarize_usage


TIMESTAMP = re.compile(r'^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\]')
REQUEST = re.compile(r'\[request\]\s+[^:]+:\s?(.*)$')
PLANNER_TIME = re.compile(r'Planning response ready \(([\d.]+)s\)')
TOOL_TIME = re.compile(r'Tool ([^ ]+) finished \(([\d.]+)s\)')


def analyze_log(path):
    """Summarize visible runtime and request metadata; never return prompt text."""
    path = Path(path)
    lines = path.read_text(encoding='utf-8', errors='replace').splitlines()
    usage = summarize_usage(usage_events(lines))
    times, metrics, planner_seconds, tools = [], usage['requestsDetail'], [], Counter()
    request_chars, truncations = [], 0
    audit_rounds = review_rounds = repair_rounds = 0
    for line in lines:
        timestamp = TIMESTAMP.match(line)
        if timestamp:
            try:
                times.append(datetime.strptime(timestamp.group(1), '%Y-%m-%d %H:%M:%S'))
            except ValueError:
                pass
        request_match = REQUEST.search(line)
        if request_match:
            request_chars.append(len(request_match.group(1)))
        planner_match = PLANNER_TIME.search(line)
        if planner_match:
            planner_seconds.append(float(planner_match.group(1)))
        tool_match = TOOL_TIME.search(line)
        if tool_match:
            tools[tool_match.group(1)] += 1
            if tool_match.group(1) == 'audit_workout_plan':
                audit_rounds += 1
        if '[request] independent_plan_review:' in line:
            review_rounds += 1
        if 'Loading started: Repairing draft' in line:
            repair_rounds += 1
        if 'Response truncated at ' in line or 'TruncatedResponseError' in line:
            truncations += 1

    terminal_states = []
    for index, line in enumerate(lines):
        if 'Workout Plan Generated Successfully' in line:
            terminal_states.append((index, 'completed'))
        elif 'Planning paused:' in line:
            terminal_states.append((index, 'paused'))
        elif 'Workout generation failed:' in line:
            terminal_states.append((index, 'failed'))
    status = max(terminal_states, default=(0, 'incomplete'))[1]
    outcomes = [m.get('outcome') for m in metrics]
    elapsed = max(0.0, (times[-1] - times[0]).total_seconds()) if len(times) > 1 else None
    return {
        'file': str(path), 'status': status, 'wallSeconds': elapsed,
        'usage':usage,
        'planningRounds': len(planner_seconds), 'plannerResponseSeconds': round(sum(planner_seconds), 1),
        'numericalAuditRounds': audit_rounds, 'independentReviewRequests':sum(str(m.get('stage','')).startswith(('independent_plan_review', 'independent_structure_review')) for m in metrics),
        'repairRounds': repair_rounds,
        'toolCalls': sum(tools.values()), 'toolCounts': dict(sorted(tools.items())),
        'truncations': truncations, 'loggedRequestCount': len(request_chars),
        'largestLoggedRequestChars': max(request_chars, default=None),
        'apiRequests': len(metrics),
        'apiSuccesses': outcomes.count('success'),
        'apiFailures': sum(value in {'failure', 'truncated', 'cancelled'} for value in outcomes),
        'apiRequestSecondsSum': _sum_known(metrics, 'elapsedSeconds'),
        'promptTokens': _sum_known(metrics, 'promptTokens'),
        'completionTokens': _sum_known(metrics, 'completionTokens'),
        'reasoningTokens': _sum_known(metrics, 'reasoningTokens'),
        'cacheHitTokens': _sum_known(metrics, 'cacheHitTokens'),
        'models': sorted({m['model'] for m in metrics if m.get('model')}),
        'stages': dict(sorted(Counter(m.get('stage', 'unscoped') for m in metrics).items())),
    }


def _sum_known(rows, field):
    if not rows or any(not isinstance(row.get(field), (int, float)) for row in rows):
        return None
    return round(sum(row[field] for row in rows), 1)


def render_comparison(summaries):
    fields = (
        ('Status', 'status'), ('Wall time (s)', 'wallSeconds'),
        ('Planning rounds', 'planningRounds'), ('Repair rounds', 'repairRounds'),
        ('Numerical audit rounds', 'numericalAuditRounds'), ('Independent review requests', 'independentReviewRequests'),
        ('Planner response seconds (non-additive)', 'plannerResponseSeconds'),
        ('Tool calls', 'toolCalls'), ('Truncations', 'truncations'),
        ('API requests', 'apiRequests'), ('API successes / failures', None),
        ('API request seconds summed (may overlap)', 'apiRequestSecondsSum'),
        ('Prompt / completion / reasoning tokens', None), ('Cache-hit tokens', 'cacheHitTokens'),
        ('Known model-token cost estimate (USD)', None),
        ('Largest logged request (chars, approximate)', 'largestLoggedRequestChars'),
        ('API stage counts', None),
        ('Tool counts', None),
    )
    headers = ['Metric', *[Path(s['file']).name for s in summaries]]
    rows = []
    for label, key in fields:
        vals = []
        for summary in summaries:
            if key is None and label == 'API successes / failures':
                value = f"{summary['apiSuccesses']} / {summary['apiFailures']}"
            elif key is None and label == 'API stage counts':
                value = ', '.join(f'{name}:{count}' for name, count in summary['stages'].items()) or '?'
            elif key is None and label == 'Tool counts':
                value = ', '.join(f'{name}:{count}' for name, count in summary['toolCounts'].items()) or '?'
            elif key is None and label == 'Known model-token cost estimate (USD)':
                cost = summary['usage']['costEstimateUSD']
                amount = (f"{cost['knownRequestsMinimum']}–{cost['knownRequestsMaximum']}"
                          if cost['knownRequestsMinimum'] is not None else 'unavailable')
                value = f"{amount} ({cost['requestsUnpriced']} unpriced)"
            elif key is None:
                value = '/'.join(str(summary[field] if summary[field] is not None else '?')
                                 for field in ('promptTokens', 'completionTokens', 'reasoningTokens'))
            else:
                value = summary.get(key)
                value = '?' if value is None else value
            vals.append(str(value))
        rows.append('| ' + ' | '.join([label, *vals]) + ' |')
    return '\n'.join(['| ' + ' | '.join(headers) + ' |', '| ' + ' | '.join(['---'] * len(headers)) + ' |', *rows])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('logs', nargs='+', help='one or more retained conversation .log files')
    args = parser.parse_args(argv)
    summaries = [analyze_log(path) for path in args.logs]
    print(render_comparison(summaries))
    print('\nWall time includes user idle time. Planner/tool durations can be nested; they are shown separately, never added to wall time. API request seconds may overlap when calls run concurrently.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
