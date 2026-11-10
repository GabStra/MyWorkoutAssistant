import copy
import json
from pathlib import Path

import pytest

from workout_generator_pkg import plan_editing
from workout_generator_pkg.conversation_store import save_conversation, load_conversation_record, list_conversations


def saved_plan(tmp_path):
    from test_workout_generator_planning_tools import planning_case, capability_requirement_messages
    from workout_generator_pkg.planning_tools import audit_workout_plan

    equipment, _, stored, draft = planning_case()
    context = capability_requirement_messages(stored, equipment)
    result = audit_workout_plan(draft, equipment, context, False)
    assert result['passed'], result['errors']
    messages = [{'role': 'system', 'content': 'Workout generator', 'incumbentPlan': {'old': 'gate'}}]
    messages += context + [
        {'role': 'assistant', 'tool_calls': [{'id': 'draft', 'function': {'name': 'audit_workout_plan', 'arguments': json.dumps(draft)}}]},
        {'role': 'tool', 'tool_call_id': 'draft', 'content': json.dumps(result)},
        {'role': 'assistant', 'content': result['preview'], 'canonicalDraftPreview': result['draftId']},
        {'role': 'user', 'content': 'CONFIRM GENERATE'}]
    library = tmp_path / 'library.json'
    library.write_text(json.dumps(equipment), encoding='utf-8')
    save_conversation(messages, conversation_id='source-plan', script_dir=str(tmp_path), metadata={
        'input_files': {'exercise_library_file': str(library)}, 'last_generation_result': {'success': True}})
    return equipment, messages, result, library


def test_edit_copy_preserves_base_and_requirements_but_requires_new_export_consent(tmp_path):
    from workout_generator_pkg.planning_tools import _latest_result, confirmed_draft, requirements_approved
    from workout_generator_pkg.interactive_shell import _bind_planning_intent

    equipment, original, result, _ = saved_plan(tmp_path)
    source_path = tmp_path / 'workouts/conversation_sessions/source-plan/messages.json'
    before = source_path.read_bytes()
    source = plan_editing.select_plan_for_edit('source-plan', str(tmp_path))
    edited = plan_editing.editing_messages(source, equipment)
    _bind_planning_intent(edited)
    assert edited[0]['planningIntent'] == 'edit' and 'incumbentPlan' not in edited[0]
    assert requirements_approved(edited)
    _, retained = _latest_result(edited, 'audit_workout_plan')
    assert retained['submittedDraft'] == result['submittedDraft']
    assert not any(m.get('content') == 'CONFIRM GENERATE' for m in edited)
    with pytest.raises(ValueError, match='CONFIRM GENERATE'):
        confirmed_draft(edited, equipment, False, require_confirmation=True)
    assert source_path.read_bytes() == before and original[0]['incumbentPlan']
    from workout_generator_pkg.interactive_shell import _messages_for_api
    from workout_generator_pkg.planner_context import request_planning_state
    edited.append({'role': 'user', 'content': 'Change the between-set rest to 105 seconds and keep everything else.'})
    state = request_planning_state(_messages_for_api(edited, True, None, equipment))
    assert state['editTask']['baseDraftId'] == state['currentDraftId']
    from workout_generator_pkg.planning_tools import compile_coordinated_repair, audit_workout_plan
    compiled, _ = compile_coordinated_repair({'requirementsId': state['requirementsId'],
        'baseDraftId': state['currentDraftId'], 'edits': {'exerciseUpdates': [
            {'exerciseRef': 'EXERCISE_0', 'setFields': {'restBetweenSetsSeconds': 105}}]}},
        {**state['editTask'], 'requirements': state['requirements']}, state['currentDraft'])
    updated = audit_workout_plan(compiled, equipment, edited, False)
    assert updated['passed'], updated['errors']
    expected = copy.deepcopy(result['submittedDraft'])
    expected['workouts'][0]['exercises'][0]['restBetweenSetsSeconds'] = 105
    assert updated['submittedDraft']['workouts'] == expected['workouts']
    assert updated['audit']['weeklyVolume'] == result['audit']['weeklyVolume']
    from workout_generator_pkg.planning_tools import coordinated_repair_tool
    assessed = {**state['editTask'], 'currentDraft': state['currentDraft'],
        'findingsAssessment': {'groups': [{'disposition': 'repair', 'findingIndexes': [0],
            'repairDimensions': ['ordering'], 'repairObjectives': []}]}}
    assert 'useSolverMenu' in coordinated_repair_tool(assessed)['function']['parameters']['properties']
    changed = copy.deepcopy(equipment)
    changed['exerciseDefinitions'][0]['name'] = 'A different library'
    with pytest.raises(ValueError, match='same full library'):
        plan_editing.editing_messages(source, changed)


def test_export_selection_checks_exact_execution_and_definition_identity(tmp_path):
    from workout_generator_pkg.domain_ops import (assemble_placeholder_workout_store,
        build_workout_structure, _materialize_exercise_definition)

    equipment, _, snapshot, _ = saved_plan(tmp_path)
    plan = snapshot['planIndex']
    exercises = {e['id']: _materialize_exercise_definition(e) for e in plan['exercises']}
    structures = {day['id']: build_workout_structure(day) for day in plan['workouts']}
    payload = assemble_placeholder_workout_store({}, {}, exercises, structures, plan)
    for day in payload['workouts']:
        for item in day['workoutComponents']:
            if item['type'] == 'Exercise':
                item['exerciseDefinitionId'] = 'press'
    path = tmp_path / 'workouts/plan.json'
    path.write_text(json.dumps(payload), encoding='utf-8')
    save_conversation(load_conversation_record('source-plan', str(tmp_path))['messages'],
        conversation_id='source-plan', script_dir=str(tmp_path), metadata={'generated_output_paths': [str(path)]})
    source = plan_editing.select_plan_for_edit(str(path), str(tmp_path))
    assert source['snapshot']['draftId'] == snapshot['draftId']
    payload['workouts'][0]['workoutComponents'][0]['sets'][0]['reps'] += 1
    path.write_text(json.dumps(payload), encoding='utf-8')
    with pytest.raises(ValueError, match='modified outside'):
        plan_editing.select_plan_for_edit(str(path), str(tmp_path))
    payload['workouts'][0]['workoutComponents'][0]['sets'][0]['reps'] -= 1
    payload['workouts'][0]['workoutComponents'][0]['exerciseDefinitionId'] = 'another-definition'
    path.write_text(json.dumps(payload), encoding='utf-8')
    with pytest.raises(ValueError, match='definitions differ'):
        plan_editing.select_plan_for_edit(str(path), str(tmp_path))


@pytest.mark.parametrize('startup', [False, True])
def test_shell_edit_opens_separate_copy_and_reuses_saved_inputs(tmp_path, monkeypatch, startup):
    from test_workout_generator_conversation_sessions import make_shell_deps
    from workout_generator_pkg.interactive_shell import main

    _, _, _, library = saved_plan(tmp_path)
    source_path = tmp_path / 'workouts/conversation_sessions/source-plan/messages.json'
    before = source_path.read_bytes()
    deps = make_shell_deps(tmp_path, chat_results=[], generation_results=[], generation_calls=[])
    args = ['workout_generator.py', '--edit-plan', 'source-plan'] if startup else [
        'workout_generator.py', '--exercise-library-file', str(library)]
    monkeypatch.setattr('sys.argv', args)
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test-key')
    inputs = iter(['/exit'] if startup else ['/edit source-plan', '/exit'])
    monkeypatch.setattr('builtins.input', lambda _: next(inputs))
    main(deps=deps)
    records = [r for r in list_conversations(str(tmp_path)) if r['conversation_id'] != 'source-plan']
    assert len(records) == 1
    edited = records[0]
    assert edited['metadata']['planningIntent'] == 'edit'
    assert edited['metadata']['edit_source'] == str(source_path.resolve())
    assert edited['metadata']['last_generation_result'] is None
    assert edited['metadata']['generated_output_paths'] == []
    assert edited['metadata']['input_files']['exercise_library_file'] == str(library)
    assert source_path.read_bytes() == before


def test_exporting_an_edit_never_overwrites_a_same_second_original(tmp_path, monkeypatch):
    from datetime import datetime
    from types import SimpleNamespace
    from workout_generator_pkg import cli

    monkeypatch.setattr(cli, 'datetime', SimpleNamespace(now=lambda: datetime(2026, 11, 8, 12, 0, 0)))
    first = Path(cli.save_workout_to_file({'name': 'Original'}, str(tmp_path)))
    before = first.read_bytes()
    second = Path(cli.save_workout_to_file({'name': 'Edited'}, str(tmp_path)))
    assert first != second and first.read_bytes() == before
    assert json.loads(second.read_text(encoding='utf-8')) == {'name': 'Edited'}
