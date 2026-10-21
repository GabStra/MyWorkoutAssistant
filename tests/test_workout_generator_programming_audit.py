import copy
import json

import pytest

from workout_generator_pkg import generation_audit as audit


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
        "rampUpSeconds": 120, "transitionSeconds": 0,
        "calibrationSeconds": 0,
    }
    assert workout["estimatedSeconds"] == 670


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
    assert workout['estimatedSeconds'] == (700 if superset else 460)
    assert any(error['code'] == 'duration_exceeded' for error in report['errors'])


def test_load_calibration_flag_does_not_add_time_or_remove_working_set_credit():
    exercise = _exercise("press", 10, 3)
    exercise["requiresLoadCalibration"] = True
    report = audit.audit_workout_package(_package(exercise), {'maximumSessionSeconds': 700})
    assert report["workouts"][0]["workingSets"] == 3
    assert report["weeklyVolume"]["chest"]["direct"] == 3
    assert report["workouts"][0]["timing"]["calibrationSeconds"] == 0
    assert report["workouts"][0]["estimatedSeconds"] == 570
    assert not report["errors"]


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
    assert report['workouts'][0]['timing']['calibrationSeconds'] == 0


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
    assert day['estimatedSeconds'] == 660


def test_superset_uses_round_rest_and_omits_final_recovery():
    first = _exercise("first", 10, 2)
    second = _exercise("second", 20, 2)
    superset = {"type": "Superset", "exercises": [first, second], "restSecondsByExercise": {"first": 40, "second": 75}}
    report = audit.audit_workout_package(_package(superset), {})
    assert report["workouts"][0]["timing"]["restSeconds"] == 155
    assert report["workouts"][0]["estimatedSeconds"] == 695
    second["sets"].extend([{"type": "RestSet", "timeInSeconds": 90}, {"type": "WeightSet", "reps": 20}])
    report = audit.audit_workout_package(_package(superset), {})
    assert report["workouts"][0]["workingSets"] == 4
    assert "shortest member" in report["issues"][0]


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
        return '{"changes":[{"exerciseId":"EXERCISE_0","numWorkSets":4,"placementNotes":"Four working sets."}]}'

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
        return '{"changes":[{"exerciseId":"EXERCISE_0","numWorkSets":3,"placementNotes":"Still three."}]}'

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


def test_pipeline_returns_audit_to_conversation_before_emission(monkeypatch, tmp_path):
    from dataclasses import replace
    from workout_generator_pkg.deps import resolve_pipeline_deps
    from workout_generator_pkg.generation_pipeline import execute_workout_generation

    events = []

    def repair(*_args, **_kwargs):
        events.append("repair")
        return '{"changes":[{"exerciseId":"EXERCISE_0","numWorkSets":4,"placementNotes":"Four working sets."}]}'

    def emission(items, *_args, **_kwargs):
        events.append("emission")
        assert items[0][1]["plan_index"]["exercises"][0]["numWorkSets"] == 4
        raise RuntimeError("Stopped before model emission")

    monkeypatch.setattr(audit, "json_call_reasoner_only_with_loading", repair)
    deps = replace(
        resolve_pipeline_deps(), test_connection=lambda *_args, **_kwargs: (True, None),
        hash_conversation=lambda *_: "hash", summarize_conversation=lambda *_: "summary",
        generate_index=lambda *_args, **_kwargs: _plan(),
        save_generation_progress=lambda *_args, **_kwargs: ("progress.json", 0),
        parallel_emit_items=emission,
    )
    result = execute_workout_generation(None, [{"role": "user", "content": "CONFIRM GENERATE"}], script_dir=str(tmp_path), deps=deps, force_use_reasoner=False)
    assert events == []
    assert not result["success"] and result["requires_plan_revision"]
    assert "Weekly chest: 3 effective sets" in result["programming_audit"]["issues"][0]


def test_load_calibration_flag_and_stale_trial_metadata_do_not_inflate_session_time():
    exercise = _exercise('press', 10, 3)
    exercise.update(requiresLoadCalibration=True, calibrationAttempts=2, calibrationRecoverySeconds=90)
    planned = audit.audit_workout_package(_package(exercise), {'maximumSessionSeconds': 750})
    assert planned['workouts'][0]['timing']['calibrationSeconds'] == 0
    assert planned['workouts'][0]['estimatedSeconds'] == 570
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
    assert day['timing']['calibrationSeconds'] == 0
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
