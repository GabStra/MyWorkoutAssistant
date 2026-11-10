import copy
import json

import pytest

from workout_generator_pkg.generation_audit import (
    audit_workout_package,
    plan_audit_package,
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


@pytest.mark.parametrize('exact', [False, True])
def test_plan_and_emitted_audits_keep_prescriptions_without_session_estimates(exact):
    from workout_generator_pkg.constants import BASE_SYSTEM_PROMPT

    assert 'Estimate session duration' not in BASE_SYSTEM_PROMPT
    plan = _plan(exact=exact)
    package = plan_audit_package(plan)
    emitted = _emitted_package([8, 9] if exact else [6, 6])
    emitted['workouts'][0]['workoutComponents'].append({
        'id': 'TIMER_UUID', 'type': 'Exercise', 'name': 'Hold', 'exerciseType': 'COUNTDOWN',
        'sets': [{'type': 'TimedDurationSet', 'timeInMillis': 30000}],
        'muscleGroups': [], 'secondaryMuscleGroups': [],
    })
    original = copy.deepcopy(emitted)
    reports = [audit_workout_package(package, {'maximumSessionSeconds': None}),
        audit_workout_package(emitted, {})]
    assert reports[0]['workouts'][0]['workingSets'] == 2
    assert reports[1]['workouts'][0]['workingSets'] == 2
    assert all(report['weeklyVolume']['chest']['effective'] == 2 for report in reports)
    for report in reports:
        encoded = json.dumps(report)
        for removed in ('estimatedSeconds', 'timing', 'setupEstimates', 'secondsPerRep',
                'calibrationTiming', 'maximumSessionSeconds'):
            assert removed not in encoded
    assert emitted == original
    assert package['workouts'][0]['workoutComponents'][0]['sets'][1] == {
        'type': 'RestSet', 'timeInSeconds': 90}


def test_obsolete_session_cap_is_rejected_instead_of_silently_ignored():
    from workout_generator_pkg.plan_contract import ContractValidationError
    with pytest.raises(ContractValidationError, match='Session-duration estimation is unavailable'):
        audit_workout_package(_emitted_package([6, 6]), {'maximumSessionSeconds': 3600})
