import json
from types import SimpleNamespace

import pytest
from jsonschema import ValidationError

from workout_generator_pkg.api_metrics import (
    api_metrics_scope, record_api_metric, record_submission_rejection,
    record_tool_rejections, rejection_reason_class, response_fingerprint,
)
from workout_generator_pkg.usage_reporting import report_usage, summarize_usage, usage_events


@pytest.mark.parametrize('repair_outcome', ['valid', 'scope_escape', 'still_invalid'])
def test_session_preflight_and_repair_rejections_reach_usage(monkeypatch, repair_outcome):
    import copy
    import uuid
    from workout_generator_pkg import session_drafting
    from test_workout_generator_parallel_planning import week_case

    equipment, messages, prepared, exercises = week_case()
    monkeypatch.setattr('workout_generator_pkg.recipe_contracts.qualify_recipe_contracts',
        lambda *a, **k: {'inputHash': 'fixture', 'contracts': [], 'capabilities': {}})
    rows = []
    logger = SimpleNamespace(log=rows.append, log_request=lambda *a, **k: None,
                             log_response=lambda *a, **k: None)
    def respond(client, request, **options):
        payload = json.loads(request[-1]['content'])
        if 'permittedPaths' in payload:
            content = json.dumps({'patch': [{'op': 'replace',
                'path': '/workouts/0/exercises/0/' + ('numWorkSets' if repair_outcome == 'scope_escape' else 'minReps'),
                'value': (999 if repair_outcome == 'scope_escape' else 'still invalid'
                          if repair_outcome == 'still_invalid' else exercises[0]['minReps'])}]})
        else:
            values = copy.deepcopy(exercises)
            if payload['session']['name'] == 'Session 0':
                values[0]['minReps'] = 'invalid'
            content = json.dumps({'exercises': values})
        record_api_metric({'event': 'api_request', 'requestId': uuid.uuid4().hex,
            'responseFingerprint': response_fingerprint(content), 'rejectionTracking': True})
        return content, None, None
    monkeypatch.setattr(session_drafting, 'chat_call', respond)
    result = session_drafting.draft_workout_sessions(None, {'preparationId': prepared['preparationId']},
        messages, equipment, {}, logger=logger)
    assert bool(result.get('proposedSubmission')) is (repair_outcome == 'valid')
    report = summarize_usage(usage_events(rows))['stageRejections']
    assert report['unmatchedRejectionEvents'] == 0
    assert report['stages']['draft_session_0']['rejectedCalls'] == 1
    assert report['stages']['draft_session_0']['reasonClasses']['schema'] == 1
    expected = {'valid': 0, 'scope_escape': 1, 'still_invalid': 2}[repair_outcome]
    assert report['stages']['draft_session_0_preflight_repair']['rejectedCalls'] == expected
    assert all(report['stages'][f'draft_session_{i}']['rejectedCalls'] == 0 for i in (1, 2))


def test_recipe_qualification_rejection_is_recorded_before_successful_retry(monkeypatch):
    import uuid
    from workout_generator_pkg import recipe_contracts
    from workout_generator_pkg.planning_tools import set_workout_requirements, library_fingerprint
    from test_workout_generator_planning_tools import planning_case

    equipment, requirements, _, _ = planning_case()
    stored = set_workout_requirements(requirements, [{'role': 'user', 'content': 'Use chest exercises.'}], equipment)
    prepared = {'definition_ids': ['LIBRARY_0'], 'candidates': {'LIBRARY_0': equipment['exerciseDefinitions'][0]},
                'sourceMessages': [], 'libraryFingerprint': library_fingerprint(equipment)}
    rows, attempts = [], []
    logger = SimpleNamespace(log=rows.append, log_request=lambda *a, **k: None, log_response=lambda *a, **k: None)
    def qualify(*args, **kwargs):
        attempts.append(1)
        content = json.dumps({'contracts': [{'definition_id': 'LIBRARY_0', 'progressionPlan': {
            'kind': 'reps', 'nextDefinitionId': None,
            'nextDefinitionName': 'Invented' if len(attempts) == 1 else None,
            'atCeilingAction': 're_audit_higher_reps'}}]})
        record_api_metric({'event': 'api_request', 'requestId': uuid.uuid4().hex,
            'responseFingerprint': response_fingerprint(content), 'rejectionTracking': True})
        return content, None, None
    monkeypatch.setattr(recipe_contracts, 'chat_call', qualify)
    result = recipe_contracts.qualify_recipe_contracts(None, prepared, stored, equipment, [], {}, logger=logger)
    assert result['contracts'][0]['progressionPlan']['nextDefinitionName'] is None
    report = summarize_usage(usage_events(rows))['stageRejections']
    assert report['unmatchedRejectionEvents'] == 0
    stage = report['stages']['qualify_recipe_contracts']
    assert (stage['calls'], stage['rejectedCalls']) == (2, 1)


def test_rejections_join_concurrent_requests_and_count_calls_once(tmp_path):
    path = tmp_path / 'run.log'
    lines = []
    logger = SimpleNamespace(log=lines.append, log_filepath=path, log_print=lambda _: None)
    with api_metrics_scope(logger, 'review'):
        for identifier, content in [('one', 'first response'), ('two', 'second response')]:
            record_api_metric({'event': 'api_request_started', 'requestId': identifier})
            record_api_metric({'event': 'api_request', 'requestId': identifier,
                'responseFingerprint': response_fingerprint(content), 'outcome': 'success'})
        record_submission_rejection(ValueError('Unknown reference FACT_999'), content='first response')
        record_submission_rejection(ValueError('Unknown reference FACT_999'), content='first response')
        record_submission_rejection(ValidationError('missing field'), content='first response')
    with api_metrics_scope(logger, 'Repairing draft'):
        record_api_metric({'event': 'api_request', 'requestId': 'three', 'submissionIds': ['edit-a', 'edit-b']})
    with api_metrics_scope(logger, 'repair_workout_alternative', submission_id='edit-a'):
        record_submission_rejection(ValueError('Numerically infeasible'))
    record_tool_rejections(json.dumps({'failureStage': 'repair_admission', 'errors': [
        {'validator': 'additionalProperties', 'message': 'extra field'}]}),
        logger=logger, stage='repair_workout_alternative', submission_id='edit-b')
    # An ordinary blocking review and an execution failure must not inflate rejections.
    for payload in ({'passed': False, 'errors': [{'code': 'independent_review_pending'}]},
                    {'executionFailure': True, 'failureStage': 'repair_admission', 'errors': [{}]}):
        record_tool_rejections(json.dumps(payload), logger=logger, stage='review', submission_id='edit-b')
    path.write_text('\n'.join(lines), encoding='utf-8')
    summary = report_usage(logger)
    assert summary['requests'] == 3
    report = summary['stageRejections']
    assert report['unmatchedRejectionEvents'] == 0
    assert report['topTwoStages'] == ['Repairing draft', 'review']
    review = report['stages']['review']
    assert (review['calls'], review['rejectedCalls'], review['rejectedSubmissions']) == (2, 1, 1)
    assert review['rejectionRate'] == .5
    repair = report['stages']['Repairing draft']
    assert (repair['calls'], repair['rejectedCalls'], repair['rejectedSubmissions']) == (1, 1, 2)
    assert repair['reasonClasses']['schema'] == repair['reasonClasses']['numerical'] == 1
    assert json.loads(path.with_suffix('.usage.json').read_text())['stageRejections'] == report
    assert 'first response' not in '\n'.join(lines)


@pytest.mark.parametrize('error,expected', [
    (ValidationError('bad shape'), 'schema'), (json.JSONDecodeError('bad JSON', '', 0), 'schema'),
    (ValueError('Unknown reference EXERCISE_99'), 'reference-ID'),
    (KeyError('weeklyVolume'), 'reference-ID'),
    (ValueError('Joint menu infeasible'), 'numerical'), (ValueError('conflicting edit ownership'), 'other'),
    ({'code': 'missing_unilateral_intra_set_rest', 'message': 'Missing rest between sides.',
      'repair': 'Correct volume and duration; preserve requirementsId.'}, 'other'),
])
def test_rejection_classification_is_diagnostic(error, expected):
    assert rejection_reason_class(error) == expected


def test_provider_schema_rejection_keeps_original_exception_and_usage():
    from workout_generator_pkg.api_client import chat_call, StructuredResponseError
    rows = []
    response = SimpleNamespace(model='deepseek-flash', usage={'prompt_tokens': 12, 'completion_tokens': 3},
        choices=[SimpleNamespace(finish_reason='stop', message=SimpleNamespace(content='{}', tool_calls=None))])
    client = SimpleNamespace(with_options=lambda **_: SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **_: response))))
    with api_metrics_scope(SimpleNamespace(log=rows.append), 'assessment'):
        with pytest.raises(StructuredResponseError):
            chat_call(client, [], output_schema={'type': 'object', 'required': ['findings']})
    summary = summarize_usage(usage_events(rows))
    assert summary['requests'] == 1
    assert summary['reportedTokenTotals']['promptTokens'] == 12
    assert summary['stageRejections']['stages']['assessment']['rejectedCalls'] == 1


def test_identical_responses_are_attributed_when_they_were_rejected():
    rows = []
    with api_metrics_scope(SimpleNamespace(log=rows.append), 'review'):
        for identifier in ('first', 'second'):
            record_api_metric({'event': 'api_request', 'requestId': identifier,
                'responseFingerprint': response_fingerprint('{}')})
            record_submission_rejection(ValueError('Unknown reference FACT_999'), content='{}')
    report = summarize_usage(usage_events(rows))['stageRejections']
    assert report['stages']['review']['rejectedCalls'] == 2
    assert report['unmatchedRejectionEvents'] == 0


def test_repaired_json_is_linked_to_later_semantic_rejection():
    from workout_generator_pkg.api_client import chat_call
    rows = []
    response = SimpleNamespace(model='deepseek-flash', usage=None,
        choices=[SimpleNamespace(finish_reason='stop', message=SimpleNamespace(
            content='{"findings": []}}', tool_calls=None))])
    client = SimpleNamespace(with_options=lambda **_: SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **_: response))))
    with api_metrics_scope(SimpleNamespace(log=rows.append), 'assessment'):
        content, _, _ = chat_call(client, [], output_schema={'type': 'object', 'required': ['findings']})
        record_submission_rejection(ValueError('Assessment must cover every finding exactly once.'), content=content)
    report = summarize_usage(usage_events(rows))['stageRejections']
    assert report['unmatchedRejectionEvents'] == 0
    assert report['stages']['assessment']['rejectedCalls'] == 1
