import json
from pathlib import Path

from workout_generator_pkg.usage_reporting import (
    api_stage_wall_seconds,
    build_workflow_metrics,
    compare_workflow_metrics,
    workflow_metrics_from_log,
)


def _request(request_id, start, finish, **metrics):
    return {'event': 'api_request', 'requestId': request_id, 'stage': 'draft',
        'requestStartedAtUTC': f'2026-11-14T00:00:{start:02d}+00:00',
        'requestFinishedAtUTC': f'2026-11-14T00:00:{finish:02d}+00:00', **metrics}


def test_workflow_metrics_union_concurrent_stage_time_and_keep_unknown_tokens_null():
    events = [
        _request('a', 0, 10, outcome='success', elapsedSeconds=10, promptTokens=100,
                 completionTokens=20, reasoningTokens=5, cacheHitTokens=30, cacheMissTokens=70),
        _request('b', 5, 15, outcome='success', elapsedSeconds=10, promptTokens=50,
                 completionTokens=10),
        _request('c', 20, 23, outcome='failure', elapsedSeconds=3),
    ]

    report = build_workflow_metrics(events, total_wall_seconds=25, stage_times={'drafting': 4}, repair_attempts=2,
        valid_package=True, reused_stages=['discovery', 'discovery'])

    assert api_stage_wall_seconds(events) == {'draft': 18.0}
    assert report['stageWallSeconds'] == {'drafting': 4}
    assert report['apiStageWallSeconds'] == {'draft': 18.0}
    assert report['totalWallSeconds'] == 25
    assert report['apiCalls'] == 3 and report['apiSuccesses'] == 2 and report['apiFailures'] == 1
    assert report['apiRequestSecondsSummed'] == 23
    assert report['tokenTotals'] == {
        'promptTokens': None, 'completionTokens': None, 'reasoningTokens': None,
        'cacheHitTokens': None, 'cacheMissTokens': None}
    assert report['tokenTotalsComplete'] is False
    assert report['repairAttempts'] == 2 and report['repairAttemptsSource'] == 'argument'
    assert report['validPackage'] is True and report['reusedStages'] == ['discovery']


def test_workflow_comparison_requires_all_five_matching_identities():
    identity = {'source': 'src', 'library': 'lib', 'history': 'hist', 'model': 'model-x', 'settings': 'cfg'}
    prescribed = build_workflow_metrics([], total_wall_seconds=1, identity=identity)
    open_ended = build_workflow_metrics([], total_wall_seconds=2, identity={**identity, 'history': 'other'})

    result = compare_workflow_metrics(prescribed, open_ended)

    assert not result['identityMatched']
    assert not result['controlledComparison']
    assert result['identityMismatches'] == ['history']
    assert 'identities must match' in result['interpretation']
    assert json.loads(json.dumps(result))['reports']['prescribed']['identity'] == identity


def test_workflow_comparison_accepts_matching_identities_and_event_counted_repairs():
    identity = {'source': 'src', 'library': 'lib', 'history': 'none', 'model': 'model-x', 'settings': 'cfg'}
    first = build_workflow_metrics([{'event': 'repair_attempt'}], total_wall_seconds=1,
        identity=identity, valid_package=True)
    second = build_workflow_metrics([], total_wall_seconds=1, identity=identity, valid_package=True)

    assert first['repairAttempts'] == 1 and first['repairAttemptsSource'] == 'events'
    assert compare_workflow_metrics(first, second)['controlledComparison']
    assert second['tokenTotals'] == {key: 0 for key in (
        'promptTokens', 'completionTokens', 'reasoningTokens', 'cacheHitTokens', 'cacheMissTokens')}

    invalid = build_workflow_metrics([], total_wall_seconds=0.1, identity=identity, valid_package=False)
    comparison = compare_workflow_metrics(first, invalid)
    assert comparison['identityMatched'] and not comparison['controlledComparison']
    assert comparison['validPackages'] == {'prescribed': True, 'open-ended': False}


def test_benchmark_cli_labels_reports_and_returns_nonzero_for_identity_mismatch(tmp_path, capsys):
    import importlib.util
    script = Path(__file__).resolve().parents[1] / 'scripts' / 'benchmark_workout_planning.py'
    spec = importlib.util.spec_from_file_location('benchmark_workout_planning', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    identity = {'source': 'src', 'library': 'lib', 'history': None, 'model': 'model-x', 'settings': 'cfg'}
    reports = [build_workflow_metrics([], total_wall_seconds=1, identity=identity),
               build_workflow_metrics([], total_wall_seconds=2, identity={**identity, 'settings': 'other'})]
    paths = [tmp_path / 'prescribed.json', tmp_path / 'open-ended.json']
    for path, report in zip(paths, reports):
        path.write_text(json.dumps(report), encoding='utf-8')

    assert module.main(['--workflow-reports', *(str(path) for path in paths)]) == 2
    output = capsys.readouterr().out
    assert '| Metric | Prescribed | Open-ended |' in output
    assert 'Identity fields match: **NO**.' in output
    assert 'settings' in output


def test_log_receipt_measures_full_conversation_through_saved_export_and_requires_marker(tmp_path):
    log = tmp_path / 'conversation.log'
    event = _request('a', 2, 5, outcome='success', elapsedSeconds=3, promptTokens=10,
                     completionTokens=4, reasoningTokens=0, cacheHitTokens=0, cacheMissTokens=10)
    log.write_text('\n'.join([
        '[2026-11-14 12:00:00] User> start',
        f'[2026-11-14 12:00:02] [api_metric] {json.dumps(event)}',
        '[2026-11-14 12:00:30] Assistant> Workout generated successfully and saved to: plan.json',
        f'[2026-11-14 12:00:35] [api_metric] {json.dumps(_request("after", 32, 34, outcome="success", elapsedSeconds=2, promptTokens=100, completionTokens=100))}',
    ]), encoding='utf-8')
    identity = {'source': 'src', 'library': 'lib', 'history': None, 'model': 'model', 'settings': 'cfg'}

    report = workflow_metrics_from_log(log, identity=identity, valid_package=True, repair_attempts=1)

    assert report['totalWallSeconds'] == 30
    assert report['completionBoundary'] == 'saved_export'
    assert report['wallIncludesUserIdleTime'] is True
    assert report['validPackage'] is True and report['identity'] == identity
    assert report['apiCalls'] == 1 and report['tokenTotals']['promptTokens'] == 10

    import importlib.util
    script = Path(__file__).resolve().parents[1] / 'scripts' / 'benchmark_workout_planning.py'
    spec = importlib.util.spec_from_file_location('benchmark_workout_planning_log', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    identity_path, report_path = tmp_path / 'identity.json', tmp_path / 'workflow_metrics.json'
    identity_path.write_text(json.dumps(identity), encoding='utf-8')
    assert module.main(['--workflow-log', str(log), '--identity-json', str(identity_path),
        '--valid-package', '--repair-attempts', '1', '--output', str(report_path)]) == 0
    assert json.loads(report_path.read_text(encoding='utf-8'))['completionBoundary'] == 'saved_export'

    log.write_text('[2026-11-14 12:00:00] User> start\n', encoding='utf-8')
    try:
        workflow_metrics_from_log(log, identity=identity, valid_package=True)
    except ValueError as error:
        assert 'no saved-export marker' in str(error)
    else:
        raise AssertionError('A valid receipt needs a timestamped successful-save marker.')
