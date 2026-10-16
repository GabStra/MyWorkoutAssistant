import copy
import json
import sys

import pytest

from workout_generator_pkg import backup_migration as migration


def case():
    old = {'id': 'old', 'name': 'Bench Press', 'exerciseType': 'WEIGHT', 'equipmentId': 'bar',
           'muscleGroups': ['FRONT_CHEST']}
    new = {**old, 'id': 'new', 'secondaryMuscleGroups': ['BACK_TRICEPS']}
    exercise = {'id': 'occurrence', 'type': 'Exercise', 'exerciseDefinitionId': 'old',
                'name': 'Bench Press', 'exerciseType': 'WEIGHT', 'equipmentId': 'bar',
                'sets': [{'id': 'set', 'type': 'WeightSet', 'reps': 8, 'weight': 60}],
                'notes': 'Placement notes', 'generateWarmUpSets': True}
    backup = {'WorkoutStore': {'schemaVersion': 4, 'exerciseDefinitions': [old],
        'workouts': [{'id': 'workout', 'workoutComponents': [{'type': 'Superset', 'id': 'pair', 'exercises': [exercise]}]}]},
        'SetHistories': [{'id': 'history-set', 'exerciseId': 'occurrence', 'workoutHistoryId': 'session', 'setId': 'set',
                          'setData': {'type': 'WeightSetData', 'actualReps': 8, 'actualWeight': 60}}],
        'WorkoutHistories': [{'id': 'session', 'workoutId': 'workout'}],
        'ExerciseInfos': [{'id': 'occurrence'}], 'ExerciseMovements': [{'old': 'motion'}]}
    return backup, {'exerciseDefinitions': [new], 'exerciseMovements': []}


def test_conversion_updates_library_data_without_rewriting_history_or_prescriptions():
    backup, library = case()
    before = copy.deepcopy(backup)
    result, report = migration.convert_backup(backup, library)
    assert result['WorkoutStore']['exerciseDefinitions'] == library['exerciseDefinitions']
    exercise = next(migration.exercises(result))
    original = next(migration.exercises(backup))
    assert exercise['exerciseDefinitionId'] == 'new'
    assert exercise['secondaryMuscleGroups'] == ['BACK_TRICEPS']
    assert exercise['sets'] == original['sets'] and exercise['id'] == original['id']
    assert result['SetHistories'] == backup['SetHistories']
    assert result['WorkoutHistories'] == backup['WorkoutHistories']
    assert result['ExerciseInfos'] == backup['ExerciseInfos']
    assert backup == before
    assert report['preservedSetHistories'] == 1


def test_unmatched_exercises_block_conversion_instead_of_pruning(monkeypatch):
    backup, library = case()
    library['exerciseDefinitions'][0]['name'] = 'Different movement'
    def match(sources, targets, equipment, client):
        return {key: {'newId': None, 'reason': 'Not equivalent', 'method': 'semantic'} for key in sources}
    monkeypatch.setattr(migration, 'semantic_matches', match)
    result, report = migration.convert_backup(backup, library, client=object())
    assert result is None and len(report['unresolvedExercises']) == 1
    assert report['unresolvedExercises'][0]['reason'] == 'Not equivalent'
    key = report['unresolvedExercises'][0]['sourceKey']
    converted, _ = migration.convert_backup(backup, library, previous=report, overrides={key: 'new'})
    assert next(migration.exercises(converted))['name'] == 'Different movement'


@pytest.mark.parametrize('reference', ['UNKNOWN', 'TARGET_1'])
def test_semantic_response_rejects_invented_or_incompatible_targets(monkeypatch, reference):
    backup, library = case()
    source = migration.identity(next(migration.exercises(backup)), {'old': backup['WorkoutStore']['exerciseDefinitions'][0]})
    library['exerciseDefinitions'].append({**library['exerciseDefinitions'][0], 'id': 'cable', 'equipmentId': 'cable'})
    content = json.dumps({'mappings': [{'sourceKey': 'source', 'targetReference': reference, 'reason': 'bad'}]})
    monkeypatch.setattr(migration, 'chat_call', lambda *args, **kwargs: (content, None, None))
    with pytest.raises(ValueError):
        migration.semantic_matches({'source': source}, library['exerciseDefinitions'], {}, object())


def test_recovery_restores_orphan_occurrence_links_without_editing_recorded_sets():
    backup, library = case()
    recovery = copy.deepcopy(backup)
    backup['WorkoutStore']['workouts'][0]['workoutComponents'] = []
    result, report = migration.convert_backup(backup, library, recoveries=[recovery])
    assert result is not None
    assert next(migration.exercises(result))['id'] == 'occurrence'
    assert result['SetHistories'] == backup['SetHistories']
    assert report['recoveredExercises'][0]['exerciseId'] == 'occurrence'


def test_cache_is_bound_to_source_files_and_explicit_mapping_checks_load_semantics():
    backup, library = case()
    _, report = migration.convert_backup(backup, library)
    changed = copy.deepcopy(backup)
    changed['WorkoutStore']['workouts'][0]['id'] = 'different'
    with pytest.raises(ValueError, match='different input'):
        migration.convert_backup(changed, library, previous=report)
    library['exerciseDefinitions'][0]['equipmentId'] = 'dumbbells'
    key = migration.source_key(next(migration.exercises(backup)))
    with pytest.raises(ValueError, match='equipment/type'):
        migration.convert_backup(backup, library, overrides={key: 'new'})


def test_cli_writes_new_backup_and_report_but_refuses_to_overwrite_inputs(monkeypatch, tmp_path):
    backup, library = case()
    source, catalog, output = [tmp_path / name for name in ('source.json', 'library.json', 'converted.json')]
    source.write_text(json.dumps(backup), encoding='utf-8')
    catalog.write_text(json.dumps(library), encoding='utf-8')
    original = source.read_bytes()
    arguments = ['convert', '--backup', str(source), '--exercise-library', str(catalog), '--output', str(output), '--offline']
    monkeypatch.setattr(sys, 'argv', arguments)
    assert migration.main() == 0
    assert json.loads(output.read_text())['SetHistories'] == backup['SetHistories']
    assert json.loads(output.with_suffix('.mapping.json').read_text())['outputWritten'] is True
    assert source.read_bytes() == original
    with pytest.raises(SystemExit):
        migration.main()
    arguments[-2:] = [str(source), '--offline']
    with pytest.raises(SystemExit):
        migration.main()
    assert source.read_bytes() == original


def test_interactive_resolution_filters_choices_saves_and_resumes_without_model_calls():
    backup, library = case()
    library['exerciseDefinitions'][0]['name'] = 'Renamed Bench Press'
    _, report = migration.convert_backup(backup, library)
    answers = iter(['renamed', '1', 'y'])
    saved = []
    migration.resolve_interactively(report, library, lambda value: saved.append(copy.deepcopy(value)), lambda prompt: next(answers))
    assert len(saved) == 1
    choice = next(iter(saved[0]['mappings'].values()))
    assert choice['method'] == 'interactive' and choice['newId'] == 'new'
    converted, _ = migration.convert_backup(backup, library, previous=saved[0])
    assert next(migration.exercises(converted))['name'] == 'Renamed Bench Press'


@pytest.mark.parametrize('response', ['', 'q', KeyboardInterrupt()])
def test_interactive_defer_or_interrupt_preserves_unresolved_records(response):
    backup, library = case()
    library['exerciseDefinitions'][0]['name'] = 'Unidentified equivalent'
    _, report = migration.convert_backup(backup, library)
    def answer(prompt):
        if isinstance(response, BaseException):
            raise response
        return response
    migration.resolve_interactively(report, library, lambda value: None, answer)
    converted, pending = migration.convert_backup(backup, library, previous=report)
    assert converted is None and len(pending['unresolvedExercises']) == 1


@pytest.mark.parametrize('confirmation', ['CONVERT TIMER', 'y'])
def test_timer_conversion_requires_explicit_approval_and_preserves_actual_history(confirmation):
    backup, library = case()
    source = next(migration.exercises(backup))
    source['exerciseType'] = 'COUNTUP'
    source['sets'] = [{'id': 'set', 'type': 'EnduranceSet', 'timeInMillis': 60000, 'autoStart': True, 'autoStop': False}]
    backup['WorkoutStore']['exerciseDefinitions'][0]['exerciseType'] = 'COUNTUP'
    backup['SetHistories'][0]['setData'] = {'type': 'EnduranceSetData', 'startTimer': 0, 'endTimer': 42000}
    library['exerciseDefinitions'][0]['exerciseType'] = 'COUNTDOWN'
    original = copy.deepcopy(backup)
    _, report = migration.convert_backup(backup, library)
    answers = iter(['1', confirmation, ''])
    migration.resolve_interactively(report, library, lambda value: None, lambda prompt: next(answers))
    converted, _ = migration.convert_backup(backup, library, previous=report)
    if confirmation == 'y':
        assert converted is None
    else:
        result = next(migration.exercises(converted))
        assert result['sets'] == [{**source['sets'][0], 'type': 'TimedDurationSet'}]
        assert result['exerciseType'] == 'COUNTDOWN'
        assert converted['SetHistories'] == backup['SetHistories']
    assert backup == original


def test_cli_interactive_resolution_writes_only_after_confirmation(monkeypatch, tmp_path):
    backup, library = case()
    library['exerciseDefinitions'][0]['name'] = 'Renamed Bench Press'
    source, catalog, output = [tmp_path / name for name in ('input.json', 'library.json', 'converted.json')]
    source.write_text(json.dumps(backup), encoding='utf-8')
    catalog.write_text(json.dumps(library), encoding='utf-8')
    monkeypatch.setattr(sys, 'argv', ['convert', '--backup', str(source), '--exercise-library', str(catalog),
                                   '--output', str(output), '--offline', '--interactive'])
    answers = iter(['1', 'y'])
    monkeypatch.setattr('builtins.input', lambda prompt: next(answers))
    assert migration.main() == 0
    assert json.loads(output.read_text())['SetHistories'] == backup['SetHistories']
    choices = json.loads(output.with_suffix('.mapping.json').read_text())['mappings'].values()
    assert next(iter(choices))['method'] == 'interactive'


@pytest.mark.parametrize('mode', ['interactive', 'bulk', 'mapping-file'])
def test_keep_original_preserves_exercise_history_and_related_movements(mode):
    backup, library = case()
    original = copy.deepcopy(backup)
    library['exerciseDefinitions'][0]['name'] = 'Not the same exercise'
    _, report = migration.convert_backup(backup, library)
    if mode == 'interactive':
        migration.resolve_interactively(report, library, lambda value: None, lambda prompt: 'k')
        converted, report = migration.convert_backup(backup, library, previous=report)
    elif mode == 'bulk':
        converted, report = migration.convert_backup(backup, library, keep_unmatched=True)
    else:
        key = migration.source_key(next(migration.exercises(backup)))
        converted, report = migration.convert_backup(backup, library, overrides={key: 'keep'})
    assert next(migration.exercises(converted)) == next(migration.exercises(backup))
    assert converted['SetHistories'] == backup['SetHistories']
    assert converted['ExerciseMovements'] == backup['ExerciseMovements']
    definitions = {d['id']: d for d in converted['WorkoutStore']['exerciseDefinitions']}
    assert definitions['new'] == library['exerciseDefinitions'][0]
    assert definitions['old']['name'] == 'Bench Press'
    assert report['retainedExercises'][0]['definitionId'] == 'old'
    assert backup == original


def test_retained_definition_gets_stable_identity_if_library_reuses_its_id():
    backup, library = case()
    library['exerciseDefinitions'][0].update(id='old', name='Different exercise')
    one, report_one = migration.convert_backup(backup, library, keep_unmatched=True)
    two, report_two = migration.convert_backup(backup, library, keep_unmatched=True)
    kept_id = next(migration.exercises(one))['exerciseDefinitionId']
    assert kept_id != 'old'
    assert kept_id == next(migration.exercises(two))['exerciseDefinitionId']
    assert report_one['retainedExercises'] == report_two['retainedExercises']
    assert one['SetHistories'] == backup['SetHistories']


@pytest.mark.parametrize('history_field', ['SetHistories', 'RestHistories', 'ExerciseSessionProgressions'])
def test_recovery_resolves_exact_workout_links_even_when_occurrence_exists_elsewhere(history_field):
    backup, library = case()
    recovery = copy.deepcopy(backup)
    original = copy.deepcopy(backup['WorkoutStore']['workouts'][0])
    original['id'] = 'other-version'
    backup['WorkoutStore']['workouts'].append(original)
    backup['WorkoutStore']['workouts'][0]['workoutComponents'] = []
    if history_field != 'SetHistories':
        backup[history_field] = backup.pop('SetHistories')
    blocked, report = migration.convert_backup(backup, library)
    assert blocked is None
    assert report['unresolvedReferences'][0]['workoutId'] == 'workout'
    converted, report = migration.convert_backup(backup, library, recoveries=[recovery])
    assert converted is not None
    assert next(migration.exercises(converted['WorkoutStore']['workouts'][0]))['id'] == 'occurrence'
    assert converted[history_field] == backup[history_field]
    assert report['recoveredExercises'][0]['workoutIds'] == ['workout']


def test_recovery_blocks_unknown_session_and_ambiguous_versions():
    backup, library = case()
    recovery = copy.deepcopy(backup)
    backup['WorkoutStore']['workouts'][0]['workoutComponents'] = []
    different = copy.deepcopy(recovery['WorkoutStore']['workouts'][0])
    different['id'] = 'different-version'
    next(migration.exercises(different))['sets'][0]['reps'] = 12
    recovery['WorkoutStore']['workouts'][0]['id'] = 'older-version'
    recovery['WorkoutStore']['workouts'].append(different)
    converted, report = migration.convert_backup(backup, library, recoveries=[recovery])
    assert converted is None
    assert 'conflicting' in report['unresolvedReferences'][0]['reason']
    backup['SetHistories'][0]['workoutHistoryId'] = 'unknown-session'
    converted, report = migration.convert_backup(backup, library, recoveries=[recovery])
    assert converted is None
    assert 'context is missing' in report['unresolvedReferences'][0]['reason']
