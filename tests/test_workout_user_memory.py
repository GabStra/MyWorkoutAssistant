import copy
import json

import pytest

from workout_user_memory import (
    bind_history, capture_scope, create_profile, facts_for, forget_fact, load_profile,
    main, memory_root, profile_for_history, record_fact, resolve_profile,
)


def library():
    return {'equipments': [{'id': 'bar', 'name': 'Barbell', 'type': 'BARBELL', 'barWeight': 20},
                           {'id': 'db', 'name': 'Dumbbells', 'type': 'DUMBBELLS'}],
            'accessoryEquipments': [{'id': 'bench', 'name': 'Bench', 'type': 'BENCH'}],
            'exerciseDefinitions': [{'id': 'raise', 'name': 'Lateral raise', 'equipmentId': 'db',
                                     'exerciseType': 'WEIGHT', 'requiredAccessoryEquipmentIds': []}]}


def source(statement='The barbell and bench share one station.'):
    return {'role': 'user', 'statement': statement, 'conversationId': 'session-one',
            'sourceReferences': ['SOURCE_0']}


def test_profile_reuse_is_explicit_and_users_stay_isolated(tmp_path, monkeypatch):
    monkeypatch.setenv('MYWORKOUT_USER_MEMORY_DIR', str(tmp_path))
    monkeypatch.delenv('MYWORKOUT_PROFILE_ID', raising=False)
    first = create_profile('First')['profileId']
    second = create_profile('Second')['profileId']
    history = tmp_path / 'history.json'
    assert resolve_profile(history_path=history) is None
    fact = record_fact(first, kind='standing_preference', value='Prefer morning workouts.', source=source())
    assert facts_for(first)['facts'] == [fact]
    assert facts_for(second)['facts'] == []
    bind_history(first, history)
    assert profile_for_history(history.parent / '.' / history.name) == first
    assert resolve_profile(history_path=history) == first
    with pytest.raises(ValueError, match='another user'):
        bind_history(second, history)
    with pytest.raises(ValueError, match='conflicts'):
        resolve_profile(second, history)
    monkeypatch.setenv('MYWORKOUT_PROFILE_ID', first)
    assert resolve_profile() == first
    assert memory_root() == tmp_path
    with pytest.raises(ValueError):
        resolve_profile('')


def test_supersession_is_explicit_and_forget_erases_personal_fact_content(tmp_path):
    profile = create_profile('User', tmp_path)['profileId']
    options = dict(kind='standing_restriction', value='Avoid overhead presses.', source=source(), root=tmp_path)
    old = record_fact(profile, **options)
    assert record_fact(profile, **options)['factId'] == old['factId']
    new = record_fact(profile, kind='standing_restriction', value='Overhead presses are now allowed.',
                      source=source('I can press overhead again.'), supersedes=old['factId'], root=tmp_path)
    assert facts_for(profile, root=tmp_path)['facts'] == [new]
    with pytest.raises(ValueError, match='active fact'):
        record_fact(profile, **options, supersedes=old['factId'])
    forget_fact(profile, old['factId'], tmp_path)
    forget_fact(profile, new['factId'], tmp_path)
    saved = load_profile(profile, tmp_path)
    assert all(set(fact) == {'factId', 'status', 'forgottenAt'} for fact in saved['facts'])
    assert facts_for(profile, root=tmp_path)['facts'] == []


def test_scoped_fact_ignores_renames_and_unrelated_changes_but_rejects_changed_dependencies(tmp_path):
    equipment = library()
    profile = create_profile('User', tmp_path)['profileId']
    scope = capture_scope(equipment, ['bar', 'bench'], ['raise'])
    fact = record_fact(profile, kind='setup_access', value={
        'independentDefinitionIds': ['raise'], 'retainedResourceIds': ['bar', 'bench']},
        source=source('I can use the dumbbells while the barbell and bench stay in place.'),
        scope=scope, root=tmp_path)
    edited = copy.deepcopy(equipment)
    edited['equipments'][0]['name'] = 'Renamed bar'
    edited['exerciseDefinitions'][0]['name'] = 'Renamed raise'
    edited['exerciseDefinitions'].append({'id': 'unrelated', 'name': 'Other', 'equipmentId': 'bar'})
    edited['history'] = [{'unrelated': True}]
    edited['equipments'][0]['barWeight'] = 15
    edited['equipments'][0]['availablePlates'] = [{'weight': 10}, {'weight': 20}]
    edited['exerciseDefinitions'][0]['reviewedExecution'] = {'limbMode': 'bilateral', 'rangeOfMotion': 'full'}
    assert facts_for(profile, edited, tmp_path)['facts'] == [fact]
    edited['equipments'][0]['type'] = 'DUMBBELLS'
    unavailable = facts_for(profile, edited, tmp_path)
    assert unavailable['facts'] == []
    assert unavailable['unavailableFacts'][0]['factId'] == fact['factId']
    assert 'changed' in unavailable['unavailableFacts'][0]['reason']
    edited = copy.deepcopy(equipment)
    edited['equipments'].pop(1)
    assert 'Missing resource' in facts_for(profile, edited, tmp_path)['unavailableFacts'][0]['reason']
    assert facts_for(profile, root=tmp_path)['facts'] == []
    edited = copy.deepcopy(equipment)
    edited['exerciseDefinitions'][0]['equipmentId'] = 'bar'
    assert facts_for(profile, edited, tmp_path)['facts'] == []
    configured = copy.deepcopy(equipment)
    configured['exerciseDefinitions'][0]['reviewedExecution'] = {'setupConfiguration': [
        {'resourceId': 'db', 'state': {'position': 'clear floor'}, 'source': 'manual', 'basis': 'observed'}]}
    configured_scope = capture_scope(configured, ['bar', 'bench'], ['raise'])
    configured['exerciseDefinitions'][0]['reviewedExecution']['setupConfiguration'][0]['source'] = 'new citation'
    assert capture_scope(configured, ['bar', 'bench'], ['raise']) == configured_scope
    configured['exerciseDefinitions'][0]['reviewedExecution']['setupConfiguration'][0]['state']['position'] = 'rack'
    assert capture_scope(configured, ['bar', 'bench'], ['raise']) != configured_scope


@pytest.mark.parametrize('change', ['invalid_json', 'missing_facts', 'bad_fact', 'wrong_profile_id'])
def test_malformed_store_is_not_treated_as_empty(tmp_path, change):
    profile = create_profile('User', tmp_path)
    path = tmp_path / 'profiles' / f"{profile['profileId']}.json"
    if change == 'invalid_json':
        path.write_text('{broken', encoding='utf-8')
    else:
        if change == 'missing_facts':
            profile.pop('facts')
        elif change == 'bad_fact':
            profile['facts'] = [{'factId': '../../escape'}]
        else:
            profile['profileId'] = 'wrong'
        path.write_text(json.dumps(profile), encoding='utf-8')
    with pytest.raises(ValueError):
        load_profile(path.stem, tmp_path)
    with pytest.raises(ValueError):
        record_fact(path.stem, kind='standing_preference', value='Morning.', source=source(), root=tmp_path)
    with pytest.raises(ValueError):
        load_profile('../../escape', tmp_path)


def test_trust_boundary_requires_user_evidence_and_complete_physical_scope(tmp_path):
    profile = create_profile('User', tmp_path)['profileId']
    for invalid in ({'role': 'assistant', 'statement': 'I assume this.'}, {'role': 'user', 'statement': ''}):
        with pytest.raises(ValueError):
            record_fact(profile, kind='standing_preference', value='Morning.', source=invalid, root=tmp_path)
    with pytest.raises(ValueError, match='snapshots'):
        record_fact(profile, kind='shared_station', value=['bar', 'bench'], source=source(), root=tmp_path)
    with pytest.raises(ValueError, match='cover'):
        record_fact(profile, kind='shared_station', value=['bar', 'bench'], source=source(),
                    scope=capture_scope(library(), ['bar']), root=tmp_path)
    contextual_source = {'role': 'user', 'statement': 'Yes.', 'context': [
        {'role': 'assistant', 'content': 'Do the barbell and bench share a station?'}]}
    fact = record_fact(profile, kind='shared_station', value=['bar', 'bench'], source=contextual_source,
                       scope=capture_scope(library(), ['bar', 'bench']), root=tmp_path)
    assert facts_for(profile, library(), tmp_path)['facts'][0]['source'] == contextual_source
    with pytest.raises(ValueError, match='context'):
        record_fact(profile, kind='standing_preference', value='Morning.',
                    source={**source(), 'context': [{'role': 'tool', 'content': 'Inferred fact'}]}, root=tmp_path)


def test_cli_can_create_confirm_show_forget_and_bind(tmp_path, capsys):
    base = ['--root', str(tmp_path)]
    main([*base, 'create', 'User'])
    profile = json.loads(capsys.readouterr().out)['profileId']
    main([*base, 'confirm', '--profile', profile, '--kind', 'standing_preference',
          '--value', '"Morning sessions."', '--source', 'I prefer morning sessions.'])
    fact = json.loads(capsys.readouterr().out)
    main([*base, 'show', profile])
    assert json.loads(capsys.readouterr().out)['facts'] == [fact]
    main([*base, 'bind-history', profile, str(tmp_path / 'history.json')])
    assert json.loads(capsys.readouterr().out)['profileId'] == profile
    main([*base, 'forget', profile, fact['factId']])
    assert json.loads(capsys.readouterr().out)['forgotten'] == fact['factId']
    backup = tmp_path / 'backup.json'
    backup.write_text(json.dumps({'WorkoutStore': library(), 'SetHistories': []}), encoding='utf-8')
    main([*base, 'confirm', '--profile', profile, '--kind', 'shared_station',
          '--value', '["bar", "bench"]', '--source', source()['statement'], '--library', str(backup)])
    physical_fact = json.loads(capsys.readouterr().out)
    main([*base, 'show', profile, '--library', str(backup)])
    assert json.loads(capsys.readouterr().out)['facts'] == [physical_fact]
