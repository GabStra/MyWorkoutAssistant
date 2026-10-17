import copy
import json
import threading

import pytest

from workout_generator_pkg import session_drafting, plan_review, interactive_shell as shell
from workout_generator_pkg.planner_context import request_planning_state, pending_evidence
from workout_generator_pkg.planning_tools import audit_workout_plan, set_workout_requirements
from test_workout_generator_planning_tools import planning_case, requirement_messages


def store_tool(messages, name, arguments, result):
    key = 'call_' + str(len(messages))
    messages.extend([{'role': 'assistant', 'tool_calls': [{'id': key, 'function': {
        'name': name, 'arguments': json.dumps(arguments)}}]},
        {'role': 'tool', 'tool_call_id': key, 'content': json.dumps(result)}])


def week_case():
    equipment, requirements, _, draft = planning_case()
    requirements['sessionsPerWeek'] = 3
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 15, 'maximum': 18}
    stored = set_workout_requirements(requirements, [{'role': 'user', 'content': 'Three sessions, 5-6 chest sets each, 15-18 weekly.'}], equipment)
    messages = requirement_messages(stored)
    sessions = [{**{key: value for key, value in draft['workouts'][0].items() if key != 'exercises'},
                 'name': f'Session {index}', 'trainingDays': [index * 2], 'definition_ids': ['LIBRARY_0']}
                for index in range(3)]
    arguments = {'requirementsId': stored['requirementsId'], 'baseDraftId': None,
                 'name': 'Program', 'sessions': sessions}
    prepared = session_drafting.prepare_workout_sessions(arguments, messages, equipment)
    store_tool(messages, 'prepare_workout_sessions', arguments, prepared)
    return equipment, messages, prepared, draft['workouts'][0]['exercises']


def test_sessions_draft_concurrently_then_merge_once_and_audit_complete_week(monkeypatch):
    equipment, messages, prepared, exercises = week_case()
    state = request_planning_state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert state['constructionTask']['stage'] == 'draft_sessions'
    assert pending_evidence(state) == ['LIBRARY_0']  # Retrieved automatically when a history backup is loaded.
    barrier = threading.Barrier(3)
    def draft(client, request, **options):
        payload = json.loads(request[-1]['content'])
        assert payload['sharedSessionTargets']['chest'] == {'minimum': 5, 'maximum': 6}
        assert len(payload['sharedWeek']) == 3
        barrier.wait(timeout=3)
        selection = payload['session']
        return json.dumps({**{k: v for k, v in selection.items() if k != 'definition_ids'},
                           'exercises': exercises}), None, None
    monkeypatch.setattr(session_drafting, 'chat_call', draft)
    before = copy.deepcopy(messages)
    checkpoints = []
    result = session_drafting.draft_workout_sessions(None, {'preparationId': prepared['preparationId']}, messages,
        equipment, state, checkpoint=lambda result: checkpoints.append(copy.deepcopy(result)))
    assert messages == before and len(checkpoints) == 3
    assert [day['name'] for day in result['proposedSubmission']['workouts']] == ['Session 0', 'Session 1', 'Session 2']
    store_tool(messages, 'draft_workout_sessions', {}, result)
    pending = request_planning_state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert pending['currentDraft'] is None and pending['parallelSubmission'] == result['proposedSubmission']
    report = audit_workout_plan(pending['parallelSubmission'], equipment, messages)
    assert report['passed'] and report['audit']['weeklyVolume']['chest']['effective'] == 15


def test_failed_session_preserves_completed_workers_and_retries_only_unfinished(monkeypatch):
    equipment, messages, prepared, exercises = week_case()
    state = request_planning_state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    ready = threading.Event()
    calls = []
    def draft(client, request, **options):
        selection = json.loads(request[-1]['content'])['session']
        calls.append(selection['name'])
        if selection['name'] == 'Session 1' and calls.count('Session 1') == 1:
            assert ready.wait(3)
            raise RuntimeError('Worker failed')
        return json.dumps({**{k: v for k, v in selection.items() if k != 'definition_ids'}, 'exercises': exercises}), None, None
    monkeypatch.setattr(session_drafting, 'chat_call', draft)
    def checkpoint(result):
        if len(result['workerResults']) == 2:
            ready.set()
    arguments = {'preparationId': prepared['preparationId']}
    failed = session_drafting.draft_workout_sessions(None, arguments, messages, equipment, state, checkpoint=checkpoint)
    assert failed['passed'] is False and 'proposedSubmission' not in failed
    assert set(failed['workerResults']) == {'0', '2'}
    store_tool(messages, 'draft_workout_sessions', arguments, failed)
    resumed = session_drafting.draft_workout_sessions(None, arguments, messages, equipment, state)
    assert 'proposedSubmission' in resumed
    assert calls.count('Session 0') == calls.count('Session 2') == 1 and calls.count('Session 1') == 2
    messages.append({'role': 'user', 'content': 'Change the movement allocation.'})
    with pytest.raises(ValueError, match='stale'):
        session_drafting.draft_workout_sessions(None, arguments, messages, equipment, state)


def test_missing_muscle_metadata_is_warning_but_supported_violation_remains_blocking(monkeypatch):
    equipment, _, stored, draft = planning_case()
    findings = [{'severity': 'blocking', 'basis': 'established_violation', 'path': '/draft/exercises/0',
                 'evidencePaths': ['/draft/libraryDefinitions/LIBRARY_0'],
                 'message': 'The claimed regional work is not represented.', 'repair': 'Find another regional exercise.',
                 'muscleTargets': ['lateralDelts']},
                {'severity': 'blocking', 'basis': 'established_violation', 'path': '/draft/exercises/0',
                 'evidencePaths': ['/sourceMessages/SOURCE_0'],
                 'message': 'The execution contradicts an explicit instruction.', 'repair': 'Correct the instruction.',
                 'muscleTargets': []}]
    monkeypatch.setattr(plan_review, 'chat_call', lambda *a, **k: (json.dumps({'findings': findings}), None, None))
    result = json.loads(shell.handle_function_call(None, requirement_messages(stored), 'audit_workout_plan', draft, equipment)['result'])
    assert [item['severity'] for item in result['review']['findings']] == ['warning', 'blocking']
    assert len(result['errors']) == 1 and result['errors'][0]['message'] == findings[1]['message']


def test_execution_repair_keeps_history_summaries_and_retrieves_details_only_on_demand():
    from workout_generator_pkg.planner_context import _focus_repair
    equipment, _, stored, draft = planning_case()
    state = {'requirementsApproved': True, 'requirements': stored['requirements'],
             'currentDraftId': 'REVISION_0', 'currentDraft': copy.deepcopy(draft),
             'lastAudit': {'passed': False, 'errors': [{'code': 'independent_review_finding',
                 'path': '/draft', 'reviewScope': 'execution', 'message': 'Check weekly movement balance.'}]},
             'otherToolResults': {}, 'exerciseCandidates': {'LIBRARY_0': {'name': 'Push-Up'}},
             'trainingEvidence': {'LIBRARY_0': {'reference': 'LIBRARY_0', 'name': 'Push-Up',
                 'status': 'comparable_records', 'sessions': [{'details': 'saved performance ' * 5000}]}}}
    before = copy.deepcopy(state)
    _focus_repair(state, set())
    assert not state['trainingEvidence']
    assert state['trainingEvidenceSummary']['LIBRARY_0']['status'] == 'comparable_records'
    assert len(json.dumps(state)) < len(json.dumps(before)) / 10
    requested = copy.deepcopy(before)
    _focus_repair(requested, set(), fresh_evidence={'LIBRARY_0'})
    assert requested['trainingEvidence'] == before['trainingEvidence']


def test_cancelled_parallel_work_keeps_checkpoints_and_never_publishes_late_results():
    from workout_generator_pkg.parallel_work import parallel_proposals
    from workout_generator_pkg.cancellation import run_cancellable
    cancelled, stopped, release, returned = (threading.Event() for _ in range(4))
    barrier = threading.Barrier(2)
    saved = []
    def fast():
        barrier.wait(3)
        return 'completed'
    def slow():
        barrier.wait(3)
        assert release.wait(3)
        returned.set()
        return 'late'
    def checkpoint(key, value):
        saved.append((key, value))
        cancelled.set()
    def run():
        try:
            return parallel_proposals([('fast', fast), ('slow', slow)], on_result=checkpoint)
        finally:
            stopped.set()
    try:
        with pytest.raises(KeyboardInterrupt):
            run_cancellable(run, cancel_event=cancelled)
        assert stopped.wait(3)
    finally:
        release.set()
    assert returned.wait(3)
    assert saved == [('fast', 'completed')]


def test_execution_and_evidence_reviews_run_concurrently_and_fail_closed(monkeypatch):
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    raw = audit_workout_plan(draft, equipment, messages)
    context = plan_review._context(raw, messages, equipment, None, len(messages) - 1)
    context['history'] = {'LIBRARY_0': {'sessions': [{'reps': 8}], 'reference': 'LIBRARY_0'}}
    monkeypatch.setattr(plan_review, '_context', lambda *a: copy.deepcopy(context))
    barrier = threading.Barrier(2)
    scopes = []
    execution_done = threading.Event()
    def review(client, request, **kwargs):
        payload = json.loads(request[-1]['content'])
        scope = 'evidence' if 'history' in payload else 'execution'
        scopes.append(scope)
        barrier.wait(3)
        if scope == 'evidence':
            assert execution_done.wait(3)
            raise RuntimeError('Evidence review unavailable')
        return '{"findings":[]}', None, None
    monkeypatch.setattr(plan_review, 'chat_call', review)
    result = plan_review.review_draft(None, raw, messages, equipment,
        progress=lambda text: execution_done.set() if text == 'Independent review: execution complete' else None)
    assert sorted(scopes) == ['evidence', 'execution']
    assert not result['passed'] and 'preview' not in result
    assert result['errors'][-1]['code'] == 'review_execution_failed'
    assert 'execution' in result['review']['scopeResults']
    store_tool(messages, 'audit_workout_plan', draft, result)
    messages.append({'role': 'user', 'content': '/continue'})
    retried = []
    def retry(client, request, **kwargs):
        retried.append(json.loads(request[-1]['content']))
        return '{"findings":[]}', None, None
    monkeypatch.setattr(plan_review, 'chat_call', retry)
    approved = plan_review.review_draft(None, raw, messages, equipment)
    assert approved['passed'] and len(retried) == 1 and 'history' in retried[0]


def test_shell_prepares_parallel_sessions_and_audits_combined_proposal_without_extra_planner_turn(monkeypatch, tmp_path):
    from test_workout_generator_conversation_sessions import make_shell_deps, FakeToolCall, FakeFunction
    from workout_generator_pkg.conversation_store import load_active_conversation_record
    equipment, messages, prepared, exercises = week_case()
    stored = json.loads(next(m['content'] for m in messages if m.get('tool_call_id') == 'requirements'))
    path = tmp_path / 'library.json'
    path.write_text(json.dumps(equipment), encoding='utf-8')
    arguments = {key: prepared[key] for key in ('requirementsId', 'baseDraftId', 'name', 'sessions')}
    def tool(name, args, key):
        return None, [FakeToolCall(key, 'function', FakeFunction(name, json.dumps(args)))]
    deps = make_shell_deps(tmp_path, chat_results=[
        tool('set_workout_requirements', stored['requirements'], 'requirements'),
        tool('search_exercise_library', {'queries': ['Push-Up']}, 'search'),
        tool('prepare_workout_sessions', arguments, 'prepare')], generation_results=[], generation_calls=[])
    chat = deps.chat_call_with_loading
    requests = []
    def capture(client, messages, tools, logger, **options):
        state = request_planning_state(messages)
        requests.append(state.get('constructionTask', {}).get('stage'))
        result = chat(client, messages, tools, logger, **options)
        for call in result[1] or []:
            if call.function.name == 'prepare_workout_sessions':
                assert 'prepare_workout_sessions' in [tool['function']['name'] for tool in tools]
                args = json.loads(call.function.arguments)
                args['requirementsId'] = state['requirementsId']
                call.function.arguments = json.dumps(args)
        return result
    deps.chat_call_with_loading = capture
    def worker(client, request, **kwargs):
        selection = json.loads(request[-1]['content'])['session']
        return json.dumps({**{key: value for key, value in selection.items() if key != 'definition_ids'},
                           'exercises': exercises}), None, None
    monkeypatch.setattr(session_drafting, 'chat_call', worker)
    monkeypatch.setattr('sys.argv', ['workout_generator.py', '--exercise-library-file', str(path)])
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test-key')
    inputs = iter(['Plan three sessions, 5-6 chest sets each and 15-18 weekly.', 'CONFIRM REQUIREMENTS', '/exit'])
    monkeypatch.setattr('builtins.input', lambda prompt='': next(inputs))
    shell.main(deps=deps)
    saved = load_active_conversation_record(str(tmp_path))['messages']
    audits = [json.loads(m['content']) for m in saved if m.get('role') == 'tool' and '"auditVersion"' in m.get('content', '')]
    assert len(requests) == 3
    assert len(audits) == 1 and audits[0]['passed']
    assert len(audits[0]['submittedDraft']['workouts']) == 3
