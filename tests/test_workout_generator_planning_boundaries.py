import copy
import json

import pytest

from workout_generator_pkg import interactive_shell, cli, exercise_library_tools as library
from workout_generator_pkg.planning_tools import (
    audit_workout_plan, requirements_approved, set_workout_requirements,
)
from test_workout_generator_planning_tools import planning_case, requirement_messages
from test_workout_generator_conversation_sessions import (
    make_shell_deps, run_shell, FakeToolCall, FakeFunction, load_active_conversation_record, save_conversation,
)


def test_requirements_need_display_and_explicit_approval_and_changes_invalidate_it():
    equipment, requirements, stored, draft = planning_case()
    messages = requirement_messages(stored)
    unshown = messages[:3] + [{'role': 'user', 'content': 'CONFIRM REQUIREMENTS'}]
    assert not requirements_approved(unshown)
    with pytest.raises(ValueError, match='user approval'):
        audit_workout_plan(draft, equipment, unshown)
    assert requirements_approved(messages)
    changed = copy.deepcopy(requirements)
    changed['auditTargets']['weeklyEffectiveSets']['chest']['minimum'] = 4
    messages.append({'role': 'user', 'content': 'Reduce the chest minimum to four'})
    replacement = set_workout_requirements(changed, messages)
    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': 'changed', 'function': {'name': 'set_workout_requirements'}}]},
        {'role': 'tool', 'tool_call_id': 'changed', 'content': json.dumps(replacement)}])
    assert not requirements_approved(messages)
    with pytest.raises(ValueError, match='user approval'):
        audit_workout_plan({**draft, 'requirementsId': replacement['requirementsId']}, equipment, messages)


def test_approved_exclusions_filter_discovery_and_block_draft_substitutions():
    equipment, requirements, _, draft = planning_case()
    requirements['exerciseRestrictions'] = {'excludeNameTerms': ['cable'], 'exceptNameTerms': ['crunch']}
    equipment['exerciseDefinitions'][0]['name'] = 'Cable Fly'
    equipment['exerciseDefinitions'].append({**equipment['exerciseDefinitions'][0], 'id': 'abs', 'name': 'Cable Crunch'})
    stored = set_workout_requirements(requirements, [], equipment)
    messages = requirement_messages(stored)
    result = library.execute_library_tool('search_exercise_library', {'queries': ['Cable Crunch']}, equipment, messages=messages)
    assert result['results'][0]['exercises'][0]['name'] == 'Cable Crunch'
    # Sorted IDs keep LIBRARY_1 assigned to the excluded fly, even after filtering.
    draft['requirementsId'] = stored['requirementsId']
    draft['workouts'][0]['exercises'][0]['definition_id'] = 'LIBRARY_1'
    with pytest.raises(ValueError, match='violates approved restrictions'):
        audit_workout_plan(draft, equipment, messages)
    assert not library.definition_available({'name': 'Machine press', 'equipmentId': 'missing'}, equipment, {})


def test_discovery_stops_for_a_draft_and_combined_calls_cannot_exceed_limit(monkeypatch):
    equipment, _, stored, _ = planning_case()
    calls = []
    def rank(client, queries, entries):
        calls.append(queries)
        return [{0: 0.9} for _ in queries]
    monkeypatch.setattr(library, '_semantic_matches', rank)
    messages = requirement_messages(stored)
    result = library.execute_library_tool('search_exercise_library', {'queries': ['chest push']}, equipment, object(), messages)
    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': 'search', 'function': {'name': 'search_exercise_library'}}]},
        {'role': 'tool', 'tool_call_id': 'search', 'content': json.dumps(result)}])
    with pytest.raises(ValueError, match='build and audit'):
        library.execute_library_tool('search_exercise_library', {'queries': ['other push']}, equipment, object(), messages)
    cached = library.execute_library_tool('search_exercise_library', {'queries': ['chest push']}, equipment, object(), messages)
    assert cached == result and len(calls) == 1
    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': 'audit', 'function': {'name': 'audit_workout_plan'}}]},
        {'role': 'tool', 'tool_call_id': 'audit', 'content': json.dumps({'passed': False, 'errors': [{'code': 'weekly_volume_below_minimum'}]})}])
    library.execute_library_tool('search_exercise_library', {'queries': ['other push']}, equipment, object(), messages)
    assert len(calls) == 2
    with pytest.raises(ValueError, match='six queries'):
        library.execute_library_searches([('one', {'queries': ['a', 'b', 'c', 'd']}),
                                          ('two', {'queries': ['e', 'f', 'g']})], equipment, object(), messages)
    assert len(calls) == 2


def test_clear_writes_new_log_tool_result_before_close(monkeypatch, tmp_path):
    requirements = planning_case()[1]
    call = FakeToolCall('requirements', 'function', FakeFunction('set_workout_requirements', json.dumps(requirements)))
    deps = make_shell_deps(tmp_path, chat_results=[(None, [call])], generation_results=[], generation_calls=[])
    deps.ConversationLogger = cli.ConversationLogger
    run_shell(monkeypatch, deps, ['/clear', 'Record my requirements', '/exit'])
    record = load_active_conversation_record(str(tmp_path))
    log = (tmp_path / 'logs' / record['metadata']['log_filename']).read_text(encoding='utf-8')
    assert 'Conversation logging started:' in log
    assert 'Record my requirements' in log
    assert 'tool result set_workout_requirements' in log
    assert 'Conversation checkpoint saved:' in log
    assert len(list((tmp_path / 'logs').glob('*.log'))) == 2


def test_reopening_empty_log_recovers_saved_transcript(tmp_path):
    conversation_id = '12345678-1234-4567-890a-123456789abc'
    save_conversation([{'role': 'user', 'content': 'Preserve this turn'}], conversation_id=conversation_id, script_dir=str(tmp_path))
    path = tmp_path / 'logs' / 'conversation_12345678.log'
    path.parent.mkdir()
    path.touch()
    logger, _ = interactive_shell._create_logger(cli.ConversationLogger, str(tmp_path), conversation_id)
    try:
        recovered = path.read_text(encoding='utf-8')
        assert 'Recovering empty log' in recovered and 'Preserve this turn' in recovered
    finally:
        logger.close()


def test_manual_generate_cannot_skip_requirements_or_audited_preview(monkeypatch, tmp_path, capsys):
    equipment, requirements, _, _ = planning_case()
    path = tmp_path / 'library.json'
    path.write_text(json.dumps(equipment), encoding='utf-8')
    call = FakeToolCall('requirements', 'function', FakeFunction('set_workout_requirements', json.dumps(requirements)))
    generated = []
    deps = make_shell_deps(tmp_path, chat_results=[(None, [call]), ('Ready to draft.', None)],
                           generation_results=[], generation_calls=generated)
    inputs = iter(['/generate', 'Record requirements', 'CONFIRM REQUIREMENTS', '/generate', '/exit'])
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test-key')
    monkeypatch.setattr('builtins.input', lambda prompt='': next(inputs))
    monkeypatch.setattr('sys.argv', ['workout_generator.py', '--exercise-library-file', str(path)])
    interactive_shell.main(deps=deps)
    assert not generated
    output = capsys.readouterr().out
    assert 'review and CONFIRM REQUIREMENTS' in output
    assert 'passing audit_workout_plan draft' in output


@pytest.mark.parametrize('cycle', [False, True])
def test_repeated_unchanged_failure_pauses_and_continue_repairs_same_plan(monkeypatch, tmp_path, capsys, cycle):
    equipment, requirements, _, draft = planning_case()
    bad = copy.deepcopy(draft)
    bad['workouts'][0]['exercises'][0]['numWorkSets'] = 3
    path = tmp_path / 'library.json'
    path.write_text(json.dumps(equipment), encoding='utf-8')
    def tool(name, args, identifier):
        return (None, [FakeToolCall(identifier, 'function', FakeFunction(name, json.dumps(args)))])
    def patch(revision, sets):
        return {'requirementsId': draft['requirementsId'], 'baseDraftId': f'REVISION_{revision}',
                'patch': [{'op': 'replace', 'path': '/workouts/0/exercises/0/numWorkSets', 'value': sets}]}
    failures = [tool('audit_workout_plan', bad, 'bad1')]
    if cycle:
        failures.extend([tool('audit_workout_plan', patch(0, 4), 'intermediate'),
                         tool('audit_workout_plan', patch(1, 3), 'bad2')])
    else:
        failures.append(tool('audit_workout_plan', patch(0, 3), 'bad2'))
    generated = []
    deps = make_shell_deps(tmp_path, chat_results=[
        tool('set_workout_requirements', requirements, 'requirements'),
        *failures, tool('audit_workout_plan', patch(2 if cycle else 0, 5), 'fixed'),
        tool('generate_workout', {}, 'export')],
        generation_results=[{'success': True, 'filepath': 'generated.json', 'error': None}], generation_calls=generated)
    inputs = iter(['Plan my workout', 'CONFIRM REQUIREMENTS', '/continue', 'CONFIRM GENERATE', '/exit'])
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test-key')
    monkeypatch.setattr('builtins.input', lambda prompt='': next(inputs))
    monkeypatch.setattr('sys.argv', ['workout_generator.py', '--exercise-library-file', str(path)])
    interactive_shell.main(deps=deps)
    output = capsys.readouterr().out
    assert 'same unchanged draft failed again' in output
    assert 'Type /continue to resume' in output
    assert len(generated) == 1
    messages = load_active_conversation_record(str(tmp_path))['messages']
    assert requirements_approved(messages)
    assert sum(c['function']['name'] == 'set_workout_requirements' for m in messages for c in m.get('tool_calls', [])) == 1


def test_more_than_eight_distinct_draft_repairs_can_finish(monkeypatch, tmp_path):
    equipment, requirements, _, draft = planning_case()
    path = tmp_path / 'library.json'
    path.write_text(json.dumps(equipment), encoding='utf-8')
    def tool(name, args, identifier):
        return (None, [FakeToolCall(identifier, 'function', FakeFunction(name, json.dumps(args)))])
    repairs = []
    for index, sets in enumerate([1, 2, 3, 4, 7, 8, 9, 10, 11]):
        changed = copy.deepcopy(draft)
        changed['workouts'][0]['exercises'][0]['numWorkSets'] = sets
        if index:
            changed = {'requirementsId': draft['requirementsId'], 'baseDraftId': f'REVISION_{index-1}',
                       'patch': [{'op': 'replace', 'path': '/workouts/0/exercises/0/numWorkSets', 'value': sets}]}
        repairs.append(tool('audit_workout_plan', changed, f'repair-{sets}'))
    passing = {'requirementsId': draft['requirementsId'], 'baseDraftId': 'REVISION_8',
               'patch': [{'op': 'replace', 'path': '/workouts/0/exercises/0/numWorkSets', 'value': 5}]}
    generated = []
    deps = make_shell_deps(tmp_path, chat_results=[tool('set_workout_requirements', requirements, 'requirements'),
                           *repairs, tool('audit_workout_plan', passing, 'passing'), tool('generate_workout', {}, 'export')],
        generation_results=[{'success': True, 'filepath': 'generated.json', 'error': None}], generation_calls=generated)
    inputs = iter(['Plan', 'CONFIRM REQUIREMENTS', 'CONFIRM GENERATE', '/exit'])
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test-key')
    monkeypatch.setattr('builtins.input', lambda prompt='': next(inputs))
    monkeypatch.setattr('sys.argv', ['workout_generator.py', '--exercise-library-file', str(path)])
    interactive_shell.main(deps=deps)
    assert len(generated) == 1


def test_rephrasing_blocked_searches_cannot_bypass_the_progress_guard(monkeypatch, tmp_path, capsys):
    equipment, requirements, _, _ = planning_case()
    path = tmp_path / 'library.json'
    path.write_text(json.dumps(equipment), encoding='utf-8')
    def tool(name, args, key):
        return (None, [FakeToolCall(key, 'function', FakeFunction(name, json.dumps(args)))])
    deps = make_shell_deps(tmp_path, chat_results=[
        tool('set_workout_requirements', requirements, 'req'),
        tool('search_exercise_library', {'queries': ['chest pressing']}, 'first'),
        tool('search_exercise_library', {'queries': ['different chest movement']}, 'blocked'),
        tool('search_exercise_library', {'queries': ['rephrased chest movement']}, 'blocked-again')],
        generation_results=[], generation_calls=[])
    requests, ranks = [], []
    original_chat = deps.chat_call_with_loading
    def chat(client, messages, tools, logger, **options):
        requests.append([t['function']['name'] for t in tools if 'function' in t])
        return original_chat(client, messages, tools, logger, **options)
    deps.chat_call_with_loading = chat
    monkeypatch.setattr(library, '_semantic_matches', lambda client, queries, entries, **kwargs: ranks.append(queries) or [{0: .9} for _ in queries])
    monkeypatch.setattr('sys.argv', ['workout_generator.py', '--exercise-library-file', str(path)])
    inputs = iter(['Plan chest training', 'CONFIRM REQUIREMENTS', '/exit'])
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test-key')
    monkeypatch.setattr('builtins.input', lambda prompt='': next(inputs))
    interactive_shell.main(deps=deps)
    assert len(requests) == 4 and len(ranks) == 1
    assert 'search_exercise_library' not in requests[-1]
    output = capsys.readouterr().out
    assert 'rewording queries made no progress' in output and 'Planning paused' in output


def test_new_failed_draft_reopens_targeted_discovery(monkeypatch, tmp_path):
    equipment, requirements, _, draft = planning_case()
    draft['workouts'][0]['exercises'][0]['numWorkSets'] = 3
    path = tmp_path / 'library.json'
    path.write_text(json.dumps(equipment), encoding='utf-8')
    def tool(name, args, key):
        return (None, [FakeToolCall(key, 'function', FakeFunction(name, json.dumps(args)))])
    deps = make_shell_deps(tmp_path, chat_results=[
        tool('set_workout_requirements', requirements, 'req'),
        tool('search_exercise_library', {'queries': ['chest pressing']}, 'first'),
        tool('search_exercise_library', {'queries': ['different chest movement']}, 'blocked'),
        tool('audit_workout_plan', draft, 'draft'),
        tool('search_exercise_library', {'queries': ['specific gap after audit']}, 'followup'),
        ('I will now revise the draft.', None)], generation_results=[], generation_calls=[])
    requests, ranks = [], []
    original_chat = deps.chat_call_with_loading
    def chat(client, messages, tools, logger, **options):
        requests.append([t['function']['name'] for t in tools if 'function' in t])
        return original_chat(client, messages, tools, logger, **options)
    deps.chat_call_with_loading = chat
    monkeypatch.setattr(library, '_semantic_matches', lambda client, queries, entries, **kwargs: ranks.append(queries) or [{0: .9} for _ in queries])
    monkeypatch.setattr('sys.argv', ['workout_generator.py', '--exercise-library-file', str(path)])
    inputs = iter(['Plan chest training', 'CONFIRM REQUIREMENTS', '/exit'])
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test-key')
    monkeypatch.setattr('builtins.input', lambda prompt='': next(inputs))
    interactive_shell.main(deps=deps)
    assert 'search_exercise_library' not in requests[3]
    assert 'search_exercise_library' in requests[4]
    assert len(ranks) == 2
