import copy
import json

import pytest

from workout_generator_pkg.generation_audit import available_muscle_targets, muscle_credits_per_set, audit_workout_package
from workout_generator_pkg.planning_tools import workout_requirements_tool, set_workout_requirements, audit_workout_plan, PlanningInputError
from workout_generator_pkg.plan_contract import hydrate_plan_index_from_exercise_library
from scripts.enrich_training_muscles import apply_roles, enrich_library
from test_workout_generator_planning_tools import planning_case, requirement_messages


def test_regional_roles_override_coarse_map_and_do_not_double_count_groups():
    definition = {'exerciseType': 'WEIGHT', 'exerciseCategory': 'MODERATE_COMPOUND',
        'muscleGroups': ['FRONT_DELTOIDS'], 'secondaryMuscleGroups': ['BACK_DELTOIDS'],
        'trainingMuscles': {'primary': ['lateralDelts'], 'secondary': ['rearDelts']}}
    credits = muscle_credits_per_set(definition)
    assert credits == {'shoulders': {'direct': 1, 'indirect': 0},
        'lateralDelts': {'direct': 1, 'indirect': 0}, 'rearDelts': {'direct': 0, 'indirect': 0.5}}
    definition['trainingMuscles']['primary'].append('rearDelts')
    with pytest.raises(ValueError, match='both primary and secondary'):
        muscle_credits_per_set(definition)


def test_tools_offer_only_regions_with_actual_library_credits_and_legacy_cannot_fake_them():
    gear, arguments, _, _ = planning_case()
    gear['exerciseDefinitions'][0]['muscleGroups'] = ['BACK_UPPER_BACK']
    gear['exerciseDefinitions'][0]['secondaryMuscleGroups'] = []
    assert set(available_muscle_targets(gear)) == {'back'}
    arguments['auditTargets']['weeklyEffectiveSets'] = {'lats': {'minimum': 5, 'maximum': 6}}
    arguments['auditTargets']['perSessionEffectiveSets'] = {}
    with pytest.raises(PlanningInputError, match='no auditable credit'):
        set_workout_requirements(arguments, [], gear)
    gear['exerciseDefinitions'][0]['trainingMuscles'] = {'primary': ['lats'], 'secondary': ['upperBack']}
    supported = set(available_muscle_targets(gear))
    assert supported == {'lats', 'upperBack', 'back'}
    schema = workout_requirements_tool(gear)['function']['parameters']['properties']['auditTargets']
    assert set(schema['properties']['weeklyEffectiveSets']['properties']) == supported
    result = set_workout_requirements(arguments, [], gear)
    assert set(result['supportedMuscleTargets']) == supported


@pytest.mark.parametrize('region,coarse', [('lats', 'BACK_UPPER_BACK'), ('lateralDelts', 'FRONT_DELTOIDS'),
                                         ('abductors', 'BACK_GLUTEAL')])
@pytest.mark.parametrize('scope,target', [('weeklyEffectiveSets', 2), ('perSessionEffectiveSets', 2),
                                         ('weeklyEffectiveSets', 0), ('weeklyEffectiveSets', 5)])
def test_mixed_metadata_cannot_approve_unknown_regional_volume(region, coarse, scope, target):
    gear, arguments, _, draft = planning_case()
    annotated = gear['exerciseDefinitions'][0]
    annotated.update(id='a', name='Annotated movement', muscleGroups=[coarse], secondaryMuscleGroups=[],
                     trainingMuscles={'primary': [region], 'secondary': []})
    legacy = copy.deepcopy(annotated)
    legacy.update(id='b', name='Legacy movement')
    legacy.pop('trainingMuscles')
    gear['exerciseDefinitions'].append(legacy)
    for field in ('weeklyEffectiveSets', 'perSessionEffectiveSets'):
        arguments['auditTargets'][field] = {region: {'minimum': target, 'maximum': target}} if field == scope else {}
    stored = set_workout_requirements(arguments, [{'role': 'user', 'content': f'Exactly {target} {region} sets.'}], gear)
    draft['requirementsId'] = stored['requirementsId']
    exercise = draft['workouts'][0]['exercises'][0]
    exercise['numWorkSets'] = 2
    legacy_exercise = {**copy.deepcopy(exercise), 'definition_id': 'LIBRARY_1'}
    draft['workouts'][0]['exercises'] = [exercise, legacy_exercise] if target else [legacy_exercise]
    messages = requirement_messages(stored)
    result = audit_workout_plan(draft, gear, messages)
    assert not result['passed'] and 'preview' not in result
    assert [error['code'] for error in result['errors']] == ['missing_training_muscle_roles']
    assert result['errors'][0]['muscles'] == [region]
    assert result['audit']['workouts'][0]['contributions'][-1]['unverifiedMuscles'] == [region]
    # Explicitly reviewed absence is distinguishable from missing data.
    legacy['trainingMuscles'] = {'primary': [], 'secondary': []}
    resolved = audit_workout_plan(draft, gear, messages)
    assert all(error['code'] != 'missing_training_muscle_roles' for error in resolved['errors'])
    assert resolved['passed'] is (target != 5)


def test_regional_roles_survive_plan_hydration_schema_materialization_and_audit():
    from workout_generator_pkg.domain_ops import apply_exercise_library_schema_v2
    gear, _, stored, draft = planning_case()
    definition = gear['exerciseDefinitions'][0]
    definition['trainingMuscles'] = {'primary': ['chest'], 'secondary': ['anteriorDelts', 'triceps']}
    result = audit_workout_plan(draft, gear, requirement_messages(stored))
    plan = result['planIndex']
    assert plan['exercises'][0]['trainingMuscles'] == definition['trainingMuscles']
    assert result['audit']['weeklyVolume']['anteriorDelts']['effective'] == 2.5
    assert result['audit']['weeklyVolume']['lateralDelts']['effective'] == 0
    plan['exercises'][0]['trainingMuscles'] = {'primary': ['lateralDelts'], 'secondary': []}
    hydrate_plan_index_from_exercise_library(plan, gear['exerciseDefinitions'])
    assert plan['exercises'][0]['trainingMuscles'] == definition['trainingMuscles']
    package = {'workouts': [{'workoutComponents': [dict(plan['exercises'][0], type='Exercise', sets=[])]}]}
    apply_exercise_library_schema_v2(package, gear['exerciseDefinitions'])
    assert package['exerciseDefinitions'][0]['trainingMuscles'] == definition['trainingMuscles']


def test_enrichment_resumes_and_preserves_ids_history_and_body_map(monkeypatch, tmp_path):
    import scripts.enrich_training_muscles as script
    gear, _, _, _ = planning_case()
    original = copy.deepcopy(gear)
    roles = {'primary': ['chest'], 'secondary': ['anteriorDelts', 'triceps']}
    calls = []
    def review(client, definitions, equipment, caller):
        calls.append(1)
        return [{**d, 'muscleGroups': ['BACK_DELTOIDS'], 'trainingMuscles': roles} for d in definitions]
    monkeypatch.setattr(script, '_review_muscle_semantics_batch', review)
    checkpoint = tmp_path / 'progress.json'
    enriched, assigned = enrich_library(None, gear, checkpoint)
    enriched_again, _ = enrich_library(None, gear, checkpoint)
    assert len(calls) == 1 and enriched_again == enriched
    definition = enriched['exerciseDefinitions'][0]
    assert {k: v for k, v in definition.items() if k != 'trainingMuscles'} == original['exerciseDefinitions'][0]
    assert gear == original
    backup = {'WorkoutStore': {**gear, 'workouts': [{'workoutComponents': [
        {'id': 'occurrence', 'type': 'Exercise', 'exerciseDefinitionId': 'press', 'sets': [{'id': 'set', 'weight': 40}]}]}]},
        'SetHistories': [{'id': 'history', 'exerciseId': 'occurrence', 'actualReps': 10}]}
    converted = apply_roles(backup, assigned)
    assert converted['SetHistories'] == backup['SetHistories']
    exercise = converted['WorkoutStore']['workouts'][0]['workoutComponents'][0]
    assert exercise['trainingMuscles'] == roles and exercise['sets'] == backup['WorkoutStore']['workouts'][0]['workoutComponents'][0]['sets']
    exercise.pop('trainingMuscles')
    converted['WorkoutStore']['exerciseDefinitions'][0].pop('trainingMuscles')
    assert converted == backup


def test_enrichment_cancellation_stops_workers_and_prevents_followup_calls(monkeypatch, tmp_path):
    import threading
    import time
    import scripts.enrich_training_muscles as script
    from workout_generator_pkg.cancellation import check_cancelled
    started, release, finished = (threading.Event() for _ in range(3))
    requests, followups = [], []
    def blocked(*args, **kwargs):
        requests.append(1)
        started.set()
        try:
            release.wait(5)
            check_cancelled()
            followups.append(1)
            return []
        finally:
            finished.set()
    def interrupt(*args):
        assert started.wait(2)
        raise KeyboardInterrupt
    monkeypatch.setattr(script, '_review_muscle_semantics_batch', blocked)
    monkeypatch.setattr(script, 'as_completed', interrupt)
    checkpoint = tmp_path / 'progress.json'
    before = time.monotonic()
    try:
        with pytest.raises(KeyboardInterrupt):
            enrich_library(None, {'exerciseDefinitions': [{'id': str(i)} for i in range(4)]}, checkpoint,
                           batch_size=1, workers=1)
        assert time.monotonic() - before < 1
        assert not finished.is_set() and not checkpoint.exists()
    finally:
        release.set()
        assert finished.wait(2)
    assert requests == [1] and followups == []


def test_enrichment_preflights_all_destinations_before_model_work(monkeypatch, tmp_path):
    import sys
    import scripts.enrich_training_muscles as script
    library, backup = tmp_path / 'library.json', tmp_path / 'backup.json'
    library.write_text(json.dumps({'exerciseDefinitions': [{'id': 'a'}]}), encoding='utf-8')
    backup.write_text('{}', encoding='utf-8')
    blocked = tmp_path / 'blocked'
    blocked.write_text('not a directory', encoding='utf-8')
    output = tmp_path / 'output.json'
    monkeypatch.setattr(sys, 'argv', ['enrich', '--library-file', str(library), '--output-file', str(output),
        '--backup-file', str(backup), '--backup-output-file', str(blocked / 'output.json')])
    monkeypatch.setattr(script, '_resolve_api_key', lambda: pytest.fail('Preflight must happen before model setup'))
    with pytest.raises(SystemExit) as failure:
        script.main()
    assert failure.value.code == 2 and not output.exists()


def test_enrichment_resumes_partial_publication_offline_and_rejects_conflicting_outputs(monkeypatch, tmp_path):
    import sys
    from contextlib import nullcontext
    import openai
    import scripts.enrich_training_muscles as script
    gear, _, _, _ = planning_case()
    library, backup = tmp_path / 'library.json', tmp_path / 'backup.json'
    output, backup_output = tmp_path / 'output.json', tmp_path / 'backup-output.json'
    library.write_text(json.dumps(gear), encoding='utf-8')
    backup.write_text(json.dumps({'WorkoutStore': gear, 'SetHistories': [{'id': 'history'}]}), encoding='utf-8')
    monkeypatch.setattr(sys, 'argv', ['enrich', '--library-file', str(library), '--output-file', str(output),
        '--backup-file', str(backup), '--backup-output-file', str(backup_output)])
    monkeypatch.setattr(script, '_resolve_api_key', lambda: 'offline-test')
    monkeypatch.setattr(openai, 'OpenAI', lambda **kwargs: nullcontext(None))
    calls = []
    def review(client, definitions, *args):
        calls.append(1)
        return [{**d, 'trainingMuscles': {'primary': ['chest'], 'secondary': []}} for d in definitions]
    monkeypatch.setattr(script, '_review_muscle_semantics_batch', review)
    write = script.write_json_atomic
    def fail_backup(path, payload):
        if path == backup_output:
            raise OSError('simulated interruption during publication')
        write(path, payload)
    monkeypatch.setattr(script, 'write_json_atomic', fail_backup)
    with pytest.raises(OSError, match='simulated interruption'):
        script.main()
    assert output.exists() and not backup_output.exists()
    first_modified = output.stat().st_mtime_ns
    monkeypatch.setattr(script, 'write_json_atomic', write)
    monkeypatch.setattr(script, '_resolve_api_key', lambda: pytest.fail('Completed checkpoint must resume offline'))
    script.main()
    assert calls == [1] and output.stat().st_mtime_ns == first_modified
    assert json.loads(backup_output.read_text(encoding='utf-8'))['SetHistories'] == [{'id': 'history'}]
    output.write_text('{"unrelated":true}', encoding='utf-8')
    with pytest.raises(SystemExit) as failure:
        script.main()
    assert failure.value.code == 2 and json.loads(output.read_text(encoding='utf-8')) == {'unrelated': True}
