"""Compare retained workout-planning logs or workflow receipts without model requests.

Create a receipt after verifying the exact export:
  python scripts/benchmark_workout_planning.py --workflow-log conversation.log \\
      --identity-json identity.json --valid-package --output workflow_metrics.json

Compare receipts labelled prescribed and open-ended:
  python scripts/benchmark_workout_planning.py --workflow-reports prescribed.json open-ended.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
if __package__ in (None, ''):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from workout_generator_pkg.usage_reporting import (usage_events, summarize_usage,
    compare_workflow_metrics, workflow_metrics_from_log)


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


def render_workflow_comparison(comparison):
    reports = comparison['reports']
    fields = (
        ('End-to-end wall seconds', 'totalWallSeconds'),
        ('API calls (completed + pending)', 'apiCalls'),
        ('Summed API request seconds (may overlap)', 'apiRequestSecondsSummed'),
        ('Repair attempts', 'repairAttempts'),
        ('Valid package', 'validPackage'),
        ('Prompt tokens', 'promptTokens'), ('Completion tokens', 'completionTokens'),
        ('Reasoning tokens', 'reasoningTokens'), ('Cache-hit tokens', 'cacheHitTokens'),
        ('Cache-miss tokens', 'cacheMissTokens'), ('Models', 'models'),
        ('API calls by stage', 'callsByStage'),
        ('Provided stage wall seconds', 'stageWallSeconds'),
        ('API stage wall seconds', 'apiStageWallSeconds'), ('Reused stages', 'reusedStages'),
    )
    rows = ['| Metric | Prescribed | Open-ended |', '| --- | --- | --- |']
    for label, field in fields:
        values = []
        for report in reports.values():
            value = report.get(field) if field in ('totalWallSeconds', 'apiCalls',
                'apiRequestSecondsSummed', 'repairAttempts', 'validPackage', 'stageWallSeconds',
                'apiStageWallSeconds', 'reusedStages', 'models', 'callsByStage') else \
                (report.get('tokenTotals') or {}).get(field)
            values.append(json.dumps(value, ensure_ascii=False, sort_keys=True) if isinstance(value, (dict, list))
                          else '?' if value is None else str(value))
        rows.append(f'| {label} | {values[0]} | {values[1]} |')
    identity_status = 'YES' if comparison['identityMatched'] else 'NO'
    valid_status = 'YES' if comparison['controlledComparison'] else 'NO'
    rows.extend(['', f"Identity fields match: **{identity_status}**.",
                 f"Valid controlled effectiveness comparison: **{valid_status}**.", comparison['interpretation']])
    if comparison['identityMismatches']:
        rows.append('Mismatched or missing identity fields: ' + ', '.join(comparison['identityMismatches']) + '.')
    rows.append('Wall-time differences are measurements for these runs; this report does not attribute causation or infer model speedups from stub timings.')
    return '\n'.join(rows)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('logs', nargs='*', help='retained conversation .log files')
    parser.add_argument('--workflow-reports', nargs=2, metavar=('PRESCRIBED_JSON', 'OPEN_ENDED_JSON'),
                        help='compare two measured workflow JSON reports with identity checks')
    parser.add_argument('--workflow-log', help='write the measured workflow receipt from one conversation log')
    parser.add_argument('--identity-json', help='JSON object with source/library/history/model/settings identities')
    package = parser.add_mutually_exclusive_group()
    package.add_argument('--valid-package', action='store_true', dest='valid_package',
                         help='caller has verified the exact exported package')
    package.add_argument('--invalid-package', action='store_false', dest='valid_package',
                         help='caller verified that no valid package was produced')
    parser.set_defaults(valid_package=None)
    parser.add_argument('--repair-attempts', type=int, default=0)
    parser.add_argument('--reused-stage', action='append', default=[])
    parser.add_argument('--stage-times-json', help='optional JSON object of measured caller-owned stage wall seconds')
    parser.add_argument('--output', help='write the workflow receipt JSON to this path instead of stdout')
    args = parser.parse_args(argv)
    if args.workflow_reports:
        if args.workflow_log or args.logs:
            parser.error('--workflow-reports cannot be combined with logs or --workflow-log')
        try:
            reports = [json.loads(Path(path).read_text(encoding='utf-8')) for path in args.workflow_reports]
        except (OSError, ValueError) as error:
            parser.error(f'cannot read workflow report: {error}')
        if not all(isinstance(report, dict) for report in reports):
            parser.error('workflow reports must be JSON objects')
        comparison = compare_workflow_metrics(*reports)
        print(render_workflow_comparison(comparison))
        return 0 if comparison['controlledComparison'] else 2
    if args.workflow_log:
        if args.logs:
            parser.error('--workflow-log cannot be combined with positional logs')
        if args.valid_package is None:
            parser.error('state --valid-package or --invalid-package; package validity is caller-verified')
        try:
            identity = json.loads(Path(args.identity_json).read_text(encoding='utf-8')) if args.identity_json else None
            stage_times = json.loads(Path(args.stage_times_json).read_text(encoding='utf-8')) if args.stage_times_json else None
            if identity is not None and not isinstance(identity, dict):
                raise ValueError('identity JSON must be an object')
            if stage_times is not None and not isinstance(stage_times, dict):
                raise ValueError('stage times JSON must be an object')
            report = workflow_metrics_from_log(args.workflow_log, identity=identity,
                valid_package=args.valid_package, repair_attempts=args.repair_attempts,
                stage_times=stage_times, reused_stages=args.reused_stage)
        except (OSError, ValueError) as error:
            parser.error(f'cannot build workflow report: {error}')
        output = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + '\n'
        if args.output:
            Path(args.output).write_text(output, encoding='utf-8')
        else:
            print(output, end='')
        return 0
    if not args.logs:
        parser.error('provide conversation logs or --workflow-reports')
    summaries = [analyze_log(path) for path in args.logs]
    print(render_comparison(summaries))
    print('\nWall time includes user idle time. Planner/tool durations can be nested; they are shown separately, never added to wall time. API request seconds may overlap when calls run concurrently.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
