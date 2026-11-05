import copy
import json
import math

import pytest

from workout_generator_pkg import generation_audit as audit
from workout_generator_pkg.plan_contract import ContractValidationError


def test_volume_disclosure_uses_audited_roles_and_weekly_frequency():
    report = {'weeklyVolume': {'shoulders': {'direct': 5, 'indirect': 2, 'effective': 7}},
        'workouts': [
            {'timesCompletedInAWeek': 2, 'contributions': [
                {'exercise': 'Press', 'workingSets': 2, 'credits': {'shoulders': {'direct': 2, 'indirect': 0}}},
                {'exercise': 'Row', 'workingSets': 2, 'credits': {'shoulders': {'direct': 0, 'indirect': 1}}}]},
            {'timesCompletedInAWeek': 1, 'contributions': [
                {'exercise': 'Fly', 'workingSets': 1, 'credits': {'shoulders': {'direct': 1, 'indirect': 0}}}]}]}
    before = copy.deepcopy(report)
    text = audit.render_volume_disclosure(report, 'shoulders')
    assert '7 effective sets weekly (5 direct + 2 weighted indirect)' in text
    direct, indirect = text.split('Indirect credit sources:')
    assert 'Press: 4 working sets weekly (4 credited sets)' in direct
    assert 'Fly: 1 working sets weekly (1 credited sets)' in direct
    assert 'Row' not in direct and 'Press' not in indirect
    assert 'Row: 4 working sets weekly (2 credited sets)' in indirect
    assert report == before


def _exercise(exercise_id, reps, count, *, primary=None, secondary=None, intra=None):
    sets = []
    for index in range(count):
        if index:
            sets.append({"type": "RestSet", "timeInSeconds": 90})
        sets.append({"type": "WeightSet", "reps": reps, "weight": 20, "subCategory": "WorkSet"})
    return {
        "id": exercise_id, "type": "Exercise", "name": exercise_id, "exerciseType": "WEIGHT",
        "sets": sets, "muscleGroups": primary or ["FRONT_CHEST"], "secondaryMuscleGroups": secondary or [],
        "exerciseCategory": "MODERATE_COMPOUND", "intraSetRestInSeconds": intra,
        "generateWarmUpSets": False,
    }


def _package(*components):
    return {"workouts": [{"id": "WORKOUT_0", "name": "Day", "workoutComponents": list(components)}]}


@pytest.mark.parametrize('count', [1, 2])
def test_opening_setup_counts_once_and_changes_session_limit(count):
    package = _package(*[_exercise(f'exercise-{index}', 1, 1) for index in range(count)])
    baseline = audit.audit_workout_package(package, {})['workouts'][0]
    assert baseline['timing']['generalWarmupSeconds'] == 300
    assert baseline['timing']['transitionSeconds'] == 60 * count
    assert len(baseline['setupEstimates']) == count
    changed = audit.audit_workout_package(package, {'maximumSessionSeconds': baseline['estimatedSeconds']},
        setup_seconds_by_exercise={'exercise-0': 300})
    assert changed['workouts'][0]['estimatedSeconds'] - baseline['estimatedSeconds'] == 240
    assert changed['workouts'][0]['setupEstimates'][0] == {
        'exerciseId': 'exercise-0', 'seconds': 300,
        'scope': 'one_time_before_exercise', 'basis': 'declared_estimate'}
    assert any(issue['code'] == 'duration_exceeded' for issue in changed['errors'])


@pytest.mark.parametrize('index', [0, 1])
@pytest.mark.parametrize('seconds', [-1, True, 1801])
def test_invalid_setup_rejects_opening_and_later_exercises_equally(index, seconds):
    package = _package(_exercise('first', 1, 1), _exercise('second', 1, 1))
    exercise_id = ('first', 'second')[index]
    report = audit.audit_workout_package(package, {}, setup_seconds_by_exercise={exercise_id: seconds})
    issue = next(issue for issue in report['errors'] if issue['code'] == 'invalid_setup_time')
    assert issue['exerciseId'] == exercise_id
    assert issue['path'] == f'/workouts/0/exercises/{index}/setupSeconds'
    assert report['workouts'][0]['timing']['transitionSeconds'] == 120


def test_minimum_only_volume_target_accepts_overage_and_numeric_maximum_still_rejects_it():
    package = _package(_exercise('press', 10, 21))
    minimum_only = {'weeklyEffectiveSets': {'chest': {'minimum': 15, 'maximum': None}},
                    'perSessionEffectiveSets': {}, 'maximumSessionSeconds': None}
    audit.validate_audit_targets(minimum_only)
    assert audit.volume_target_bounds(minimum_only['weeklyEffectiveSets']['chest']) == (15, math.inf)
    assert audit.volume_target_text(minimum_only['weeklyEffectiveSets']['chest']) == '≥ 15'
    assert not audit.audit_workout_package(package, minimum_only)['errors']

    capped = copy.deepcopy(minimum_only)
    capped['weeklyEffectiveSets']['chest']['maximum'] = 20
    assert 'volume_above_target' in {item['code'] for item in audit.audit_workout_package(package, capped)['errors']}


def test_volume_menu_coupling_uses_only_the_minimum_without_serializing_infinity():
    result = audit.muscle_credit_coupling_evidence([{
        'id': 'LIBRARY_0', 'name': 'Press',
        'creditsPerWorkingSet': {'chest': {'direct': 1, 'indirect': 0}},
    }], {'auditTargets': {'weeklyEffectiveSets': {
        'chest': {'minimum': 15, 'maximum': None}}}})

    assert result['status'] == 'proven'
    assert result['profileLowerBounds'][0]['minimumWeeklyWorkingSets'] == 15
    json.dumps(result, allow_nan=False)


def test_development_menu_diagnostic_omits_unbounded_upper_rows():
    result = audit.development_menu_limits([{
        'id': 'LIBRARY_0', 'name': 'Press',
        'creditsPerWorkingSet': {'chest': {'direct': 1, 'indirect': 0}},
    }], {
        'auditTargets': {'weeklyEffectiveSets': {'chest': {'minimum': 15, 'maximum': None}}},
        'requiredCoverage': [{'key': 'upper_push', 'scope': 'weekly', 'intent': 'development',
                              'minimumWeeklySets': 6}],
    }, {'LIBRARY_0': ['upper_push']}, source_set_cap=30,
       training_occurrences=3, minimum_work_sets=2)

    assert result['status'] == 'proven_upper_bounds'
    assert result['roleUpperBounds']['upper_push'] == 30
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize('bounds', [
    {'minimum': True, 'maximum': None},
    {'minimum': math.nan, 'maximum': None},
    {'minimum': math.inf, 'maximum': None},
    {'minimum': 15, 'maximum': True},
    {'minimum': 15, 'maximum': math.nan},
    {'minimum': 15, 'maximum': math.inf},
    {'minimum': 15, 'maximum': 14},
    {'minimum': 15, 'maximum': 101},
    {'minimum': 101, 'maximum': None},
    {'minimum': 15},
])
def test_volume_target_bounds_reject_invalid_or_upper_only_shapes(bounds):
    targets = {'weeklyEffectiveSets': {'chest': bounds}, 'perSessionEffectiveSets': {},
               'maximumSessionSeconds': None}
    with pytest.raises(ContractValidationError):
        audit.validate_audit_targets(targets)


def test_zero_to_zero_volume_target_remains_an_explicit_ban():
    targets = {'weeklyEffectiveSets': {'chest': {'minimum': 0, 'maximum': 0}},
               'perSessionEffectiveSets': {}, 'maximumSessionSeconds': None}
    assert not audit.audit_workout_package(_package(_exercise('press', 10, 0)), targets)['errors']
    assert 'volume_above_target' in {item['code'] for item in audit.audit_workout_package(
        _package(_exercise('press', 10, 1)), targets)['errors']}


def test_volume_deduplicates_tags_and_excludes_warmup_and_calibration():
    exercise = _exercise("press", 10, 3, primary=["FRONT_TRICEPS", "BACK_TRICEPS"], secondary=["BACK_TRICEPS", "FRONT_DELTOIDS"])
    exercise["sets"].extend([
        {"type": "WeightSet", "reps": 5, "subCategory": "WarmupSet"},
        {"type": "WeightSet", "reps": 5, "subCategory": "CalibrationSet"},
    ])
    report = audit.audit_workout_package(_package(exercise), {})
    assert report["weeklyVolume"]["triceps"] == {"direct": 3, "indirect": 0, "effective": 3}
    assert report["weeklyVolume"]["shoulders"]["effective"] == 1.5
    assert report["workouts"][0]["workingSets"] == 3


def test_coverage_totals_use_executed_sets_frequency_and_distinct_physical_work():
    press, pull = _exercise('press', 8, 3), _exercise('pull', 8, 2)
    press['sets'].insert(0, {'type': 'WeightSet', 'reps': 4, 'subCategory': 'WarmupSet'})
    pull['sets'].insert(0, {'type': 'WeightSet', 'reps': 4, 'subCategory': 'WarmupSet'})
    squat = _exercise('squat', 8, 3, primary=['FRONT_QUADRICEPS'], intra=20)
    package = _package({'type': 'Superset', 'exercises': [press, pull],
                        'restSecondsByExercise': {'press': 30, 'pull': 90}}, squat)
    package['workouts'][0]['timesCompletedInAWeek'] = 2
    package['workouts'].append({'name': 'Disabled', 'enabled': False,
        'workoutComponents': [_exercise('disabled', 8, 5)]})
    assignments = {'press': ['horizontal_push', 'horizontal_push'], 'pull': ['horizontal_pull'],
                   'squat': ['knee_dominant', 'lower_body'], 'disabled': ['unused']}
    before = copy.deepcopy(package)
    report = audit.audit_workout_package(package, {}, coverage_by_exercise=assignments)
    assert report['weeklyWorkingSets'] == 14  # Two rounds of both members + three unilateral sets, twice weekly.
    assert report['weeklyCoverageSets'] == {'horizontal_push': 4, 'horizontal_pull': 4,
        'knee_dominant': 6, 'lower_body': 6, 'unused': 0}
    assert report['workouts'][0]['coverageSets']['horizontal_push'] == 2
    assert report['coverageByExercise'] == assignments and report['coverageByExercise'] is not assignments
    assert package == before


@pytest.mark.parametrize('assignments', [{'unknown': ['push']}, {'press': 'push'}])
def test_coverage_totals_reject_invalid_metadata(assignments):
    with pytest.raises(ValueError, match='Coverage metadata'):
        audit.audit_workout_package(_package(_exercise('press', 8, 3)), {}, coverage_by_exercise=assignments)


def test_unilateral_timing_counts_both_sides_but_volume_once():
    exercise = _exercise("split squat", 10, 2, primary=["FRONT_QUADRICEPS"], intra=20)
    exercise["generateWarmUpSets"] = True
    report = audit.audit_workout_package(_package(exercise), {})
    workout = report["workouts"][0]
    assert workout["volume"]["quads"]["effective"] == 2
    assert workout["timing"] == {
        "workSeconds": 120, "restSeconds": 130, "generalWarmupSeconds": 300,
        "rampUpSeconds": 120, "transitionSeconds": 60,
        "calibrationSeconds": 0,
    }
    assert workout["estimatedSeconds"] == 730


@pytest.mark.parametrize('set_type', ['EnduranceSet', 'TimedDurationSet'])
@pytest.mark.parametrize('superset', [False, True])
def test_timed_unilateral_rest_can_make_a_session_exceed_its_limit(set_type, superset):
    hold = {'id': 'hold', 'type': 'Exercise', 'name': 'Unilateral hold',
            'exerciseType': 'COUNTUP' if set_type == 'EnduranceSet' else 'COUNTDOWN',
            'intraSetRestInSeconds': 20,
            'sets': [{'type': set_type, 'timeInMillis': 30000} for _ in range(2)]}
    component = {'type': 'Superset', 'exercises': [hold, _exercise('partner', 10, 2)],
                 'restSecondsByExercise': {'hold': 30, 'partner': 60}} if superset else hold
    limit = 680 if superset else 430
    report = audit.audit_workout_package(_package(component), {'maximumSessionSeconds': limit})
    workout = report['workouts'][0]
    assert workout['timing']['restSeconds'] == (160 if superset else 40)
    assert workout['estimatedSeconds'] == (760 if superset else 520)
    assert any(error['code'] == 'duration_exceeded' for error in report['errors'])


def test_native_load_calibration_estimates_one_inserted_set_without_changing_working_set_credit():
    exercise = _exercise("press", 10, 3)
    exercise["requiresLoadCalibration"] = True
    report = audit.audit_workout_package(_package(exercise), {'maximumSessionSeconds': 700})
    assert report["workouts"][0]["workingSets"] == 3
    assert report["weeklyVolume"]["chest"]["direct"] == 3
    assert report["workouts"][0]["timing"]["calibrationSeconds"] == 30
    assert report["workouts"][0]["estimatedSeconds"] == 660
    assert not report["errors"]
    assert 'interaction, retries, and actual execution time remain unknown' in report['calibrationTiming']
    over_limit = audit.audit_workout_package(_package(exercise), {'maximumSessionSeconds': 590})
    assert any(error['code'] == 'duration_exceeded' for error in over_limit['errors'])


def test_native_unilateral_calibration_estimate_counts_both_sides_and_between_side_rest():
    exercise = _exercise('split squat', 8, 2, intra=20)
    exercise['requiresLoadCalibration'] = True
    report = audit.audit_workout_package(_package(exercise), {})
    timing = report['workouts'][0]['timing']
    assert timing['calibrationSeconds'] == 48
    assert timing['restSeconds'] == 150
    assert report['workouts'][0]['estimatedSeconds'] == 654


def test_plan_audit_keeps_native_calibration_flag_without_inventing_attempt_metadata():
    plan = _plan()
    plan['exercises'][0]['requiresLoadCalibration'] = True
    package = audit.plan_audit_package(plan)
    exercise = package['workouts'][0]['workoutComponents'][0]
    assert exercise['requiresLoadCalibration'] is True
    assert 'calibrationRecoverySeconds' not in exercise
    assert 'calibrationAttempts' not in exercise
    report = audit.audit_workout_package(package, plan['auditTargets'])
    assert report['workouts'][0]['workingSets'] == 3
    assert report['workouts'][0]['timing']['calibrationSeconds'] == 30
    assert report['workouts'][0]['estimatedSeconds'] == 660


def test_explicit_calibration_set_and_rest_are_timed_as_real_activity():
    exercise = _exercise('bodyweight', 10, 3)
    exercise.update(exerciseType='BODY_WEIGHT', requiresLoadCalibration=True)
    for item in exercise['sets']:
        if item['type'] == 'WeightSet':
            item.update(type='BodyWeightSet', additionalWeight=0)
            item.pop('weight')
    exercise['sets'].extend([
        {'type': 'RestSet', 'timeInSeconds': 75},
        {'type': 'BodyWeightSet', 'reps': 5, 'additionalWeight': 0, 'subCategory': 'CalibrationSet'},
    ])
    report = audit.audit_workout_package(_package(exercise), {})
    day = report['workouts'][0]
    assert day['workingSets'] == 3
    assert day['timing']['workSeconds'] == 90
    assert day['timing']['restSeconds'] == 255
    assert day['timing']['calibrationSeconds'] == 15
    assert day['estimatedSeconds'] == 720


def test_superset_uses_round_rest_and_omits_final_recovery():
    first = _exercise("first", 10, 2)
    second = _exercise("second", 20, 2)
    superset = {"type": "Superset", "exercises": [first, second], "restSecondsByExercise": {"first": 40, "second": 75}}
    report = audit.audit_workout_package(_package(superset), {})
    assert report["workouts"][0]["timing"]["restSeconds"] == 155
    assert report["workouts"][0]["estimatedSeconds"] == 755
    second["sets"].extend([{"type": "RestSet", "timeInSeconds": 90}, {"type": "WeightSet", "reps": 20}])
    report = audit.audit_workout_package(_package(superset), {})
    assert report["workouts"][0]["workingSets"] == 4
    assert "shortest member" in report["issues"][0]


@pytest.mark.parametrize('rounds', [1, 2])
def test_zero_member_recovery_only_counts_completed_round_rests_and_keeps_setup(rounds):
    first = _exercise('first', 10, rounds)
    second = _exercise('second', 10, rounds)
    for exercise in (first, second):
        for item in exercise['sets']:
            if item['type'] == 'RestSet':
                item['timeInSeconds'] = 60
    straight = audit.audit_workout_package(_package(first, second), {})['workouts'][0]
    superset = {'type': 'Superset', 'exercises': [first, second],
        'restSecondsByExercise': {'first': 0, 'second': 60}}
    grouped = audit.audit_workout_package(_package(superset), {})['workouts'][0]

    assert grouped['timing']['restSeconds'] == 60 * (rounds - 1)
    assert grouped['timing']['transitionSeconds'] == straight['timing']['transitionSeconds'] == 120
    assert grouped['setupEstimates'] == straight['setupEstimates']
    assert grouped['volume'] == straight['volume']
    assert straight['estimatedSeconds'] - grouped['estimatedSeconds'] == 60 * (rounds - 1)
    assert 'Zero prescribed recovery between members does not imply zero physical changeover time' in audit.audit_policy()['setupTiming']


def _plan():
    return {
        "planName": "Program", "equipments": [{"id": "EQUIPMENT_0", "name": "Barbell", "type": "BARBELL"}],
        "accessoryEquipments": [],
        "auditTargets": {"weeklyEffectiveSets": {"chest": {"minimum": 4, "maximum": 4}}, "maximumSessionSeconds": 1000},
        "exercises": [{
            "id": "EXERCISE_0", "name": "Bench Press", "exerciseType": "WEIGHT", "equipmentId": "EQUIPMENT_0",
            "bodyWeightPercentage": None, "requiredAccessoryEquipmentIds": [], "intraSetRestInSeconds": None,
            "muscleGroups": ["FRONT_CHEST"], "secondaryMuscleGroups": [], "exerciseCategory": "MODERATE_COMPOUND",
            "numWorkSets": 3, "minReps": 8, "maxReps": 10, "restBetweenSetsSeconds": 90, "generateWarmUpSets": False,
        }],
        "workouts": [{"id": "WORKOUT_0", "name": "Day", "exerciseIds": ["EXERCISE_0"], "restToNextSeconds": [0]}],
    }


def test_early_repair_fixes_counts_and_keeps_targets_and_identity(monkeypatch):
    calls = []

    def repair(_client, messages, *_args, **_kwargs):
        calls.append(json.loads(messages[-1]["content"]))
        return '{"changes":[{"exerciseId":"EXERCISE_0","numWorkSets":4}]}'

    monkeypatch.setattr(audit, "json_call_reasoner_only_with_loading", repair)
    plan = _plan()
    original = copy.deepcopy(plan)
    fixed, report = audit.audit_and_repair_plan(None, plan, None)
    assert not report["issues"]
    assert fixed["exercises"][0]["numWorkSets"] == 4
    assert fixed["auditTargets"] == original["auditTargets"]
    assert fixed["exercises"][0]["equipmentId"] == "EQUIPMENT_0"
    assert plan == original
    assert "Weekly chest: 3 effective sets" in calls[0]["audit"]["issues"][0]


def test_repair_is_bounded_and_cannot_change_targets_or_muscles(monkeypatch):
    calls = []

    def ineffective(*_, **_kwargs):
        calls.append(1)
        return '{"changes":[{"exerciseId":"EXERCISE_0","numWorkSets":3}]}'

    monkeypatch.setattr(audit, "json_call_reasoner_only_with_loading", ineffective)
    with pytest.raises(ValueError, match="after bounded repair"):
        audit.audit_and_repair_plan(None, _plan(), None)
    assert len(calls) == 2
    monkeypatch.setattr(audit, "json_call_reasoner_only_with_loading", lambda *_, **_kwargs: '{"changes":[{"exerciseId":"EXERCISE_0","numWorkSets":4,"muscleGroups":["FRONT_CHEST"]}]}')
    with pytest.raises(ValueError, match="only working-set counts"):
        audit.audit_and_repair_plan(None, _plan(), None)


def test_time_limit_and_per_session_shortfall_are_reported_from_actual_sets():
    report = audit.audit_workout_package(_package(_exercise("press", 10, 3)), {
        "maximumSessionSeconds": 100, "perSessionEffectiveSets": {"chest": {"minimum": 5, "maximum": 6}},
    })
    assert any("exceeds 100s" in issue for issue in report["issues"])
    assert any("Day chest: 3 effective sets" in issue for issue in report["issues"])


def test_audited_progress_is_not_complete_before_final_audit(tmp_path):
    from workout_generator_pkg.progress import list_available_progress

    directory = tmp_path / "workouts/generation_progress"
    directory.mkdir(parents=True)
    path = directory / "progress_test.json"
    record = {"current_step": 7, "step_data": {"step_1_plan_index": {"auditTargets": {}}}}
    path.write_text(json.dumps(record))
    assert list_available_progress(str(tmp_path))[0]["status"] == "incomplete"
    record["current_step"] = 8
    path.write_text(json.dumps(record))
    assert list_available_progress(str(tmp_path))[0]["status"] == "complete"


def test_superset_timed_work_is_included_in_duration():
    first = {"id": "first", "name": "Bike", "sets": [{"type": "EnduranceSet", "timeInMillis": 60000}]}
    second = {"id": "second", "name": "Row", "sets": [{"type": "EnduranceSet", "timeInMillis": 60000}]}
    report = audit.audit_workout_package(_package({"type": "Superset", "exercises": [first, second], "restSecondsByExercise": {"first": 30, "second": 60}}), {})
    assert report["workouts"][0]["workingSets"] == 0
    assert report["workouts"][0]["timing"]["workSeconds"] == 120
    assert report["workouts"][0]["timing"]["restSeconds"] == 30




def test_load_calibration_flag_and_stale_trial_metadata_do_not_inflate_session_time():
    exercise = _exercise('press', 10, 3)
    exercise.update(requiresLoadCalibration=True, calibrationAttempts=2, calibrationRecoverySeconds=90)
    planned = audit.audit_workout_package(_package(exercise), {'maximumSessionSeconds': 750})
    assert planned['workouts'][0]['timing']['calibrationSeconds'] == 30
    assert planned['workouts'][0]['estimatedSeconds'] == 660
    assert not planned['errors']
    assert 'calibrationAttemptsByExercise' not in planned
    assert 'calibrationRecoverySecondsByExercise' not in planned


def test_calibration_mode_flag_adds_no_timed_trial_to_unilateral_exercise():
    exercise = _exercise('hold', 10, 2, intra=20)
    exercise.update(exerciseType='COUNTDOWN', requiresLoadCalibration=True)
    for item in exercise['sets']:
        if item['type'] == 'WeightSet':
            item.update(type='TimedDurationSet', timeInMillis=30000)
            item.pop('reps')
    report = audit.audit_workout_package(_package(exercise), {})
    assert report['workouts'][0]['timing']['calibrationSeconds'] == 0
    assert report['workouts'][0]['timing']['workSeconds'] == 120
    assert report['workouts'][0]['timing']['restSeconds'] == 130
    assert report['workouts'][0]['workingSets'] == 0


def test_explicit_rep_duration_affects_prescribed_work_and_survives_export():
    exercise = _exercise('slow', 10, 3)
    exercise['requiresLoadCalibration'] = True
    baseline = audit.audit_workout_package(_package(exercise), {'maximumSessionSeconds': 900})
    assert not baseline['errors']
    exercise['repDurationSeconds'] = 6
    planned = audit.audit_workout_package(_package(exercise), {'maximumSessionSeconds': 900})
    day = planned['workouts'][0]
    assert day['timing']['workSeconds'] == 3 * 10 * 6
    assert day['timing']['calibrationSeconds'] == 60
    assert not planned['errors']
    exported = copy.deepcopy(exercise)
    exported.pop('repDurationSeconds')
    actual = audit.audit_workout_package(_package(exported), {'maximumSessionSeconds': 900},
        rep_duration_seconds_by_exercise={'slow': 6})
    assert actual['workouts'] == planned['workouts']
    assert actual['repDurationSecondsByExercise'] == {'slow': 6}
    for invalid in ({'slow': 0}, {'slow': True}, {'slow': float('nan')}, {'slow': float('inf')}, {'other': 6}):
        with pytest.raises(ValueError):
            audit.audit_workout_package(_package(exported), {}, rep_duration_seconds_by_exercise=invalid)
