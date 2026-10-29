import copy

import pytest

from workout_generator_pkg.generation_audit import (
    CONSERVATIVE_REP_TIMING_BASIS,
    audit_workout_package,
    plan_audit_package,
    plan_timing_reps_by_exercise,
)


def _plan(*, exact=False):
    exercise = {
        'id': 'EXERCISE_0', 'name': 'Press', 'exerciseType': 'WEIGHT',
        'equipmentId': 'EQUIPMENT_0', 'bodyWeightPercentage': None,
        'requiredAccessoryEquipmentIds': [], 'intraSetRestInSeconds': None,
        'muscleGroups': ['FRONT_CHEST'], 'secondaryMuscleGroups': [],
        'exerciseCategory': 'MODERATE_COMPOUND', 'numWorkSets': 2,
        'minReps': 6, 'maxReps': 10, 'restBetweenSetsSeconds': 90,
        'generateWarmUpSets': False, 'requiresLoadCalibration': True,
    }
    if exact:
        exercise['targetSetPrescriptions'] = [
            {'workSetIndex': 0, 'reps': 8}, {'workSetIndex': 1, 'reps': 9},
        ]
    return {
        'auditTargets': {}, 'exercises': [exercise],
        'workouts': [{'id': 'WORKOUT_0', 'name': 'Day',
                      'exerciseIds': ['EXERCISE_0'], 'restToNextSeconds': [0]}],
    }


def _emitted_package(reps):
    return {'workouts': [{'id': 'WORKOUT_UUID', 'name': 'Day', 'workoutComponents': [{
        'id': 'EXERCISE_UUID', 'type': 'Exercise', 'name': 'Press', 'exerciseType': 'WEIGHT',
        'equipmentId': 'EQUIPMENT_UUID', 'requiresLoadCalibration': True,
        'intraSetRestInSeconds': None, 'generateWarmUpSets': False,
        'muscleGroups': ['FRONT_CHEST'], 'secondaryMuscleGroups': [],
        'sets': [
            {'type': 'WeightSet', 'reps': reps[0], 'subCategory': 'WorkSet'},
            {'type': 'RestSet', 'timeInSeconds': 90},
            {'type': 'WeightSet', 'reps': reps[1], 'subCategory': 'WorkSet'},
        ],
    }]}]}


@pytest.mark.parametrize(('exact', 'expected_timing_reps'), [(False, [10, 10]), (True, [8, 9])])
def test_final_timing_reuses_planned_rep_basis_and_preserves_emitted_sets(exact, expected_timing_reps):
    plan = _plan(exact=exact)
    reps_by_plan_id = plan_timing_reps_by_exercise(plan)
    assert reps_by_plan_id == {'EXERCISE_0': expected_timing_reps}

    exported = _emitted_package([6, 6] if not exact else [8, 9])
    original = copy.deepcopy(exported)
    mapped_reps = {'EXERCISE_UUID': reps_by_plan_id['EXERCISE_0']}
    conservative = audit_workout_package(exported, {}, timing_reps_by_exercise=mapped_reps)
    emitted = audit_workout_package(exported, {})

    expected_work = sum(expected_timing_reps) * 3
    expected_calibration = expected_timing_reps[0] * 3
    assert conservative['workouts'][0]['timing']['workSeconds'] == expected_work
    assert conservative['workouts'][0]['timing']['calibrationSeconds'] == expected_calibration
    assert emitted['workouts'][0]['timing']['workSeconds'] == sum(
        [6, 6] if not exact else [8, 9]) * 3
    assert conservative['timingRepBasis'] == CONSERVATIVE_REP_TIMING_BASIS
    assert exported == original


def test_timing_rep_override_rejects_wrong_identity_length_and_values():
    package = _emitted_package([6, 6])
    for invalid in (
        {'OTHER_UUID': [10, 10]},
        {'EXERCISE_UUID': [10]},
        {'EXERCISE_UUID': [10, True]},
        {'EXERCISE_UUID': [10, 0]},
    ):
        with pytest.raises(ValueError):
            audit_workout_package(package, {}, timing_reps_by_exercise=invalid)


def test_plan_rep_timing_projection_ignores_non_rep_based_exercises():
    plan = _plan()
    plan['exercises'].extend([
        {'id': 'EXERCISE_1', 'name': 'Run', 'exerciseType': 'RUNNING', 'numWorkSets': 1,
         'restBetweenSetsSeconds': 0, 'generateWarmUpSets': False},
        {'id': 'EXERCISE_2', 'name': 'Hold', 'exerciseType': 'COUNTDOWN', 'numWorkSets': 1,
         'timeInMillis': 30000, 'restBetweenSetsSeconds': 0, 'generateWarmUpSets': False},
    ])
    plan['workouts'][0]['exerciseIds'].extend(['EXERCISE_1', 'EXERCISE_2'])
    plan['workouts'][0]['restToNextSeconds'].extend([0, 0])
    assert plan_timing_reps_by_exercise(plan) == {'EXERCISE_0': [10, 10]}
    timed_report = audit_workout_package(plan_audit_package(plan), {})
    assert timed_report['workouts'][0]['timing']['workSeconds'] == 90


def test_planned_and_emitted_timing_match_when_exact_targets_are_present():
    plan = _plan(exact=True)
    planned = audit_workout_package(plan_audit_package(plan), {})
    final = audit_workout_package(_emitted_package([8, 9]), {},
        timing_reps_by_exercise={'EXERCISE_UUID': [8, 9]})
    assert final['workouts'][0]['timing'] == planned['workouts'][0]['timing']
