import copy
import json
import threading
from types import SimpleNamespace

import pytest

from workout_generator_pkg import interactive_shell as shell
from workout_generator_pkg.exercise_library_tools import execute_library_tool
from workout_generator_pkg.lookup_batch import execute_lookup_batch
from workout_generator_pkg.planner_context import construction_tool_failure, discovery_tool_failure, pending_evidence
from workout_generator_pkg.planning_tools import (
    audit_workout_plan, library_fingerprint, prepare_workout_session, validate_construction_submission,
    construction_workout_tool, latest_draft_submission, planning_tool_failure, set_workout_requirements,
)
from workout_generator_pkg.training_history import TrainingHistory
from test_workout_generator_planning_tools import planning_case, requirement_messages
from test_workout_generator_planner_context import _state, _tool
from test_workout_generator_training_history import history_case


@pytest.mark.parametrize('malformed', ['summary', 'missing_exercises', 'null_exercises', 'incomplete_exercise'])
def test_append_schema_rejects_incomplete_sessions_without_losing_saved_draft(malformed):
    from jsonschema import validate, ValidationError
    equipment, requirements, _, draft = planning_case()
    requirements['sessionsPerWeek'] = 3
    stored = set_workout_requirements(requirements, [{'role': 'user', 'content': 'Three sessions.'}], equipment)
    draft['requirementsId'] = stored['requirementsId']
    messages = requirement_messages(stored)
    result = audit_workout_plan(draft, equipment, messages)
    _tool(messages, 'audit_workout_plan', draft, result, 'first')
    task = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))['constructionTask']
    task['definition_ids'] = ['LIBRARY_0']
    before = latest_draft_submission(messages, equipment)
    day = copy.deepcopy(draft['workouts'][0])
    if malformed == 'summary':
        day['reference'] = 'WORKOUT_1'
        day['exerciseSummary'] = day.pop('exercises')
    elif malformed == 'missing_exercises':
        day.pop('exercises')
    elif malformed == 'null_exercises':
        day['exercises'] = None
    else:
        day['exercises'][0].pop('numWorkSets')
    arguments = {'requirementsId': stored['requirementsId'], 'baseDraftId': before[1],
                 'patch': [{'op': 'add', 'path': '/workouts/-', 'value': day}]}
    schema = construction_workout_tool(task)['function']['parameters']
    with pytest.raises(ValidationError):
        validate(arguments, schema)
    with pytest.raises(ValidationError) as error:
        validate_construction_submission(arguments, task)
    failure = planning_tool_failure('audit_workout_plan', error.value, arguments)
    assert failure['errors'][0]['code'] == 'invalid_arguments'
    assert failure['errors'][0]['path'].startswith('/patch/0/value')
    _tool(messages, 'audit_workout_plan', arguments, failure, 'malformed')
    assert latest_draft_submission(messages, equipment) == before
    state = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert state['constructionTask']['action'] == 'append_session'
    arguments['patch'][0]['value'] = {**copy.deepcopy(draft['workouts'][0]), 'name': 'Day B'}
    validate(arguments, schema)
    validate_construction_submission(arguments, task)
    repaired = audit_workout_plan(arguments, equipment, messages)
    assert len(repaired['submittedDraft']['workouts']) == 2
    assert repaired['submittedDraft']['workouts'][0] == before[0]['workouts'][0]


def test_preparation_commits_selection_and_fetches_only_missing_evidence():
    equipment, stored, draft, backup = history_case()
    history = TrainingHistory(backup)
    messages = requirement_messages(stored)
    result = execute_library_tool('search_exercise_library', {'queries': ['Push-Up']}, equipment, messages=messages)
    _tool(messages, 'search_exercise_library', {'queries': ['Push-Up']}, result, 'search')
    state = _state(shell._messages_for_api(messages, True, history, equipment))
    assert state['constructionTask']['stage'] == 'choose_movements'
    assert construction_tool_failure('get_exercise_candidates', {'definition_ids': ['LIBRARY_0']}, state)
    assert construction_tool_failure('get_training_evidence', {'definition_ids': ['LIBRARY_0']}, state)
    args = {'requirementsId': stored['requirementsId'], 'baseDraftId': None, 'definition_ids': ['LIBRARY_0']}
    prepared = prepare_workout_session(args, messages, equipment)
    _tool(messages, 'prepare_workout_session', args, prepared, 'prepared')
    with pytest.raises(ValueError, match='already committed'):
        prepare_workout_session(args, messages, equipment)
    state = _state(shell._messages_for_api(messages, True, history, equipment))
    assert state['constructionTask']['stage'] == 'retrieve_evidence'
    assert pending_evidence(state) == ['LIBRARY_0']
    assert construction_tool_failure('audit_workout_plan', draft, state)
    evidence_args = {'definition_ids': ['LIBRARY_0']}
    _tool(messages, 'get_training_evidence', evidence_args, history.evidence(evidence_args, equipment), 'history')
    messages.append({'role': 'user', 'content': '/continue'})
    before = copy.deepcopy(messages)
    state = _state(shell._messages_for_api(messages, True, history, equipment))
    assert state['constructionTask']['stage'] == 'submit_session'
    assert pending_evidence(state) == []
    assert state['retrievedEvidenceReferences'] == ['LIBRARY_0']
    assert state['trainingEvidence']['LIBRARY_0']['sessions']
    assert construction_tool_failure('get_training_evidence', evidence_args, state)
    assert construction_tool_failure('prepare_workout_session', args, state)
    assert not construction_tool_failure('audit_workout_plan', draft, state)
    validate_construction_submission(draft, state['constructionTask'])
    wrong = copy.deepcopy(draft)
    wrong['workouts'][0]['exercises'][0]['definition_id'] = 'LIBRARY_1'
    with pytest.raises(ValueError, match='committed movement selection'):
        validate_construction_submission(wrong, state['constructionTask'])
    with pytest.raises(ValueError, match='stale'):
        prepare_workout_session({**args, 'baseDraftId': 'REVISION_999'}, messages, equipment)
    assert messages == before


def test_repeat_history_pages_are_detected_but_new_pages_are_not_blocked():
    equipment, stored, draft, backup = history_case()
    history = TrainingHistory(backup)
    messages = requirement_messages(stored)
    draft['workouts'][0]['exercises'][0]['numWorkSets'] = 3
    args = {'definition_ids': ['LIBRARY_0']}
    evidence = history.evidence(args, equipment)
    _tool(messages, 'get_training_evidence', args, evidence, 'before-audit')
    _tool(messages, 'audit_workout_plan', draft, audit_workout_plan(draft, equipment, messages), 'draft')
    for key in ['once', 'twice']:
        _tool(messages, 'get_training_evidence', args, evidence, key)
    state = _state(shell._messages_for_api(messages, True, history, equipment))
    assert discovery_tool_failure('get_training_evidence', state)
    assert not state.get('evidenceReaudit')
    older = {**args, 'session_offset': 1}
    _tool(messages, 'get_training_evidence', older, history.evidence(older, equipment), 'older')
    assert not _state(shell._messages_for_api(messages, True, history, equipment)).get('discoveryPaused')


def test_related_summary_does_not_satisfy_an_explicit_evidence_dependency():
    state = {'requirementsApproved': True, 'currentDraftAudited': True,
             'selectedDefinitionReferences': ['LIBRARY_0'], 'retrievedEvidenceReferences': [],
             'trainingEvidenceSummary': {'LIBRARY_0': {'status': 'comparable_records'}},
             'trainingEvidence': {'LIBRARY_0': {'sessions': [{'performances': []}]}}}
    assert pending_evidence(state) == ['LIBRARY_0']
    state['retrievedEvidenceReferences'] = ['LIBRARY_0']
    assert pending_evidence(state) == []


def test_session_summary_preserves_spacing_and_movement_identity():
    from workout_generator_pkg.planner_context import _session_summary
    _, _, _, draft = planning_case()
    day = draft['workouts'][0]
    day['trainingDays'] = [0]
    day['exercises'][0]['satisfiesCoverage'] = ['upper_push']
    before = copy.deepcopy(day)
    summary = _session_summary(day, 0, {'LIBRARY_0': {'name': 'Push-Up'}})
    assert summary['trainingDays'] == [0] and summary['detailsOmitted']
    assert summary['exerciseSummary'][0]['name'] == 'Push-Up'
    assert summary['exerciseSummary'][0]['satisfiesCoverage'] == ['upper_push']
    assert day == before


def test_large_history_request_is_chunked_and_resume_cache_is_page_and_snapshot_specific():
    equipment, _, stored, _ = planning_case()
    equipment['exerciseDefinitions'] = [{**copy.deepcopy(equipment['exerciseDefinitions'][0]), 'id': f'exercise-{i:02d}'}
                                      for i in range(14)]
    messages = requirement_messages(stored)
    calls = []
    history = SimpleNamespace(fingerprint='snapshot')
    def evidence(args, equipment, client=None):
        calls.append(copy.deepcopy(args))
        return {'historyFingerprint': history.fingerprint, 'libraryFingerprint': library_fingerprint(equipment),
                'exercises': [{'reference': ref, 'sessions': [], 'page': args.get('session_offset', 0)} for ref in args['definition_ids']]}
    history.evidence = evidence
    args = {'definition_ids': [f'LIBRARY_{i}' for i in range(14)]}
    result = execute_lookup_batch([('big', 'get_training_evidence', args)], equipment, None, messages, history)['big']
    assert [len(call['definition_ids']) for call in calls] == [12, 2]
    assert len(result['exercises']) == 14
    _tool(messages, 'get_training_evidence', args, result, 'saved')
    subset = {'definition_ids': ['LIBRARY_13', 'LIBRARY_0']}
    result = execute_lookup_batch([('reuse', 'get_training_evidence', subset)], equipment, None, messages, history)['reuse']
    assert len(calls) == 2 and [x['reference'] for x in result['exercises']] == subset['definition_ids']
    execute_lookup_batch([('page', 'get_training_evidence', {**subset, 'session_offset': 1})], equipment, None, messages, history)
    assert len(calls) == 3
    history.fingerprint = 'new-snapshot'
    execute_lookup_batch([('fresh', 'get_training_evidence', subset)], equipment, None, messages, history)
    assert len(calls) == 4
    history.fingerprint = 'snapshot'
    equipment['exerciseDefinitions'][0]['name'] = 'Changed definition'
    execute_lookup_batch([('library', 'get_training_evidence', subset)], equipment, None, messages, history)
    assert len(calls) == 5


def test_one_large_history_call_preserves_completed_chunk_when_cancelled():
    equipment, _, stored, _ = planning_case()
    equipment['exerciseDefinitions'] = [{**copy.deepcopy(equipment['exerciseDefinitions'][0]), 'id': f'exercise-{i:02d}'}
                                      for i in range(13)]
    messages = requirement_messages(stored)
    saved, checkpointed = {}, threading.Event()
    calls = []
    history = SimpleNamespace(fingerprint='snapshot')
    def evidence(args, equipment, client=None):
        calls.append(args['definition_ids'])
        if args['definition_ids'] == ['LIBRARY_12'] and len(calls) == 2:
            assert checkpointed.wait(3)
            raise KeyboardInterrupt
        return {'historyFingerprint': history.fingerprint, 'libraryFingerprint': library_fingerprint(equipment),
                'exercises': [{'reference': ref} for ref in args['definition_ids']]}
    history.evidence = evidence
    args = {'definition_ids': [f'LIBRARY_{i}' for i in range(13)]}
    def checkpoint(key, payload):
        saved[key] = payload
        checkpointed.set()
    with pytest.raises(KeyboardInterrupt):
        execute_lookup_batch([('big', 'get_training_evidence', args)], equipment, None, messages, history, on_result=checkpoint)
    assert saved['big']['inProgress'] and len(saved['big']['exercises']) == 12
    _tool(messages, 'get_training_evidence', args, saved['big'], 'partial')
    result = execute_lookup_batch([('resumed', 'get_training_evidence', args)], equipment, None, messages, history)['resumed']
    assert len(result['exercises']) == 13 and calls[-1] == ['LIBRARY_12']


def test_shell_prepares_fetches_and_submits_without_another_lookup_round(monkeypatch, tmp_path):
    from test_workout_generator_conversation_sessions import make_shell_deps, FakeToolCall, FakeFunction
    equipment, _, stored, draft = planning_case()
    _, _, _, backup = history_case()
    history = TrainingHistory(backup)
    path = tmp_path / 'library.json'
    path.write_text(json.dumps(equipment), encoding='utf-8')
    calls, requests = [], []
    original_evidence = history.evidence
    def evidence(*args, **kwargs):
        calls.append((copy.deepcopy(args[0]), kwargs.get('client') is not None))
        return original_evidence(*args, **kwargs)
    history.evidence = evidence
    monkeypatch.setattr(TrainingHistory, 'from_file', lambda path: history)
    def tool(name, args, key):
        return (None, [FakeToolCall(key, 'function', FakeFunction(name, json.dumps(args)))])
    deps = make_shell_deps(tmp_path, chat_results=[
        tool('set_workout_requirements', stored['requirements'], 'requirements'),
        tool('search_exercise_library', {'queries': ['Push-Up']}, 'search'),
        tool('prepare_workout_session', {'requirementsId': stored['requirementsId'], 'baseDraftId': None, 'definition_ids': ['LIBRARY_0']}, 'prepare'),
        tool('audit_workout_plan', draft, 'submit')], generation_results=[], generation_calls=[])
    chat = deps.chat_call_with_loading
    def capture(client, messages, tools, logger, **options):
        state = _state(messages) if any((m.get('content') or '').startswith('Current planning state') for m in messages) else {}
        requests.append((state.get('constructionTask', {}).get('stage'), [t['function']['name'] for t in tools if 'function' in t]))
        result = chat(client, messages, tools, logger, **options)
        for call in result[1] or []:
            if call.function.name == 'prepare_workout_session':
                args = json.loads(call.function.arguments)
                args['requirementsId'] = state['requirementsId']
                call.function.arguments = json.dumps(args)
        return result
    deps.chat_call_with_loading = capture
    monkeypatch.setattr('sys.argv', ['workout_generator.py', '--exercise-library-file', str(path), '--history-backup-file', 'backup.json'])
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test-key')
    inputs = iter(['Plan chest training', 'CONFIRM REQUIREMENTS', '/exit'])
    monkeypatch.setattr('builtins.input', lambda prompt='': next(inputs))
    shell.main(deps=deps)
    assert [stage for stage, _ in requests[1:]] == ['discover_movements', 'choose_movements', 'submit_session']
    # The search summary is separate from the single full evidence dependency.
    assert len(calls) == 2 and sum(full for _, full in calls) == 1
    assert set(requests[-1][1]) == {'audit_workout_plan', 'ask_user'}
