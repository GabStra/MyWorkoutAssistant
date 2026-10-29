import copy

import pytest

from workout_generator_pkg import joint_planning
from test_workout_generator_planning_tools import planning_case


def duration_case():
    equipment, requirements, _, draft = planning_case()
    requirements.update(sessionsPerWeek=2, objectiveOrder=['duration_balance', 'distribution'])
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 10, 'maximum': 10}
    requirements['auditTargets']['perSessionEffectiveSets']['chest'] = {'minimum': 2, 'maximum': 8}
    sessions = []
    for index, rest in enumerate((30, 90)):
        day = copy.deepcopy(draft['workouts'][0])
        day.update(name=f'Day {index}', trainingDays=[index * 2])
        exercise = day['exercises'][0]
        exercise.pop('placementNotes', None)
        exercise.update(minReps=10, maxReps=10, workSetTemplate={'reps': 10},
                        restBetweenSetsSeconds=rest, allocationBounds={'minimum': 2, 'maximum': 8})
        sessions.append(day)
    return equipment, requirements, sessions


@pytest.mark.parametrize('duration_first, counts, gap', [(True, [6, 4], 60), (False, [5, 5], 240)])
def test_duration_preference_uses_audited_time_and_respects_approved_priority_order(duration_first, counts, gap):
    equipment, requirements, sessions = duration_case()
    if not duration_first:
        requirements['objectiveOrder'].reverse()
    original = copy.deepcopy(sessions)

    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment,
                                                 preserve_source_selection=True)

    assert result['feasible'], result
    assert [day['exercises'][0]['numWorkSets'] for day in result['sessions']] == counts
    seconds = [day['estimatedSeconds'] for day in result['audit']['workouts']]
    assert max(seconds) - min(seconds) == gap
    stage = next(item for item in result['objectiveProgress'] if item['goal'] == 'duration_balance')
    assert stage['status'] == 'optimal' and stage['value'] == gap
    assert result['audit']['weeklyVolume']['chest']['effective'] == 10
    assert all(value <= requirements['auditTargets']['maximumSessionSeconds'] for value in seconds)
    assert sessions == original


def test_duration_balance_retains_fractional_seconds_without_rounding_or_changing_prescriptions():
    equipment, requirements, sessions = duration_case()
    requirements['objectiveOrder'] = ['duration_balance']
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 6, 'maximum': 6}
    requirements['auditTargets']['perSessionEffectiveSets']['chest'] = {'minimum': 3, 'maximum': 3}
    for day, rep_seconds in zip(sessions, (0.5, 1)):
        day['exercises'][0].update(numWorkSets=3, minReps=1, maxReps=1,
            workSetTemplate={'reps': 1}, repDurationSeconds=rep_seconds,
            restBetweenSetsSeconds=0, allocationBounds={'minimum': 3, 'maximum': 3})

    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment,
                                                 preserve_source_selection=True)

    assert result['feasible'], result
    seconds = [day['estimatedSeconds'] for day in result['audit']['workouts']]
    assert max(seconds) - min(seconds) == 1.5
    assert result['objectiveProgress'][0]['value'] == pytest.approx(1.5)
    assert [day['exercises'][0]['numWorkSets'] for day in result['sessions']] == [3, 3]


def test_approved_duration_tolerance_allows_lower_priority_balance_to_reduce_set_imbalance():
    equipment, requirements, sessions = duration_case()
    requirements['durationBalanceToleranceSeconds'] = 240

    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment,
                                                 preserve_source_selection=True)

    assert result['feasible'], result
    assert [day['exercises'][0]['numWorkSets'] for day in result['sessions']] == [5, 5]
    seconds = [day['estimatedSeconds'] for day in result['audit']['workouts']]
    assert max(seconds) - min(seconds) == 240
    assert result['objectiveProgress'][0]['goal'] == 'duration_balance'
    assert result['objectiveProgress'][0]['status'] == 'optimal'
    assert result['objectiveProgress'][0]['value'] == pytest.approx(0)
    assert result['audit']['weeklyVolume']['chest']['effective'] == 10
    assert all(value <= requirements['auditTargets']['maximumSessionSeconds'] for value in seconds)


def test_duration_balance_includes_fixed_existing_sessions():
    equipment, requirements, sessions = duration_case()
    requirements.update(sessionsPerWeek=3, objectiveOrder=['duration_balance'])
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 12, 'maximum': 12}
    fixed = copy.deepcopy(sessions[0])
    fixed.update(name='Fixed day', trainingDays=[4])
    fixed['exercises'][0].update(numWorkSets=2, restBetweenSetsSeconds=30)

    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment,
        existing={'name': 'Existing', 'workouts': [fixed]}, preserve_source_selection=True)

    assert result['feasible'], result
    seconds = [day['estimatedSeconds'] for day in result['audit']['workouts']]
    assert len(seconds) == 3
    assert 390 in seconds  # Five-minute warm-up, two 30-second sets and one 30-second rest.
    assert result['objectiveProgress'][0]['value'] == pytest.approx(max(seconds) - min(seconds))


def test_duration_only_preference_reaches_joint_solver_when_numeric_audit_already_passes(monkeypatch):
    from workout_generator_pkg.allocation import auto_allocate_workout
    from workout_generator_pkg.planning_tools import audit_workout_plan, set_workout_requirements
    from test_workout_generator_planning_tools import requirement_messages

    equipment, requirements, sessions = duration_case()
    requirements['objectiveOrder'] = ['duration_balance']
    stored = set_workout_requirements(requirements, [{'role': 'user',
        'content': 'Two sessions, ten weekly chest sets; prefer similar durations.'}], equipment)
    messages = requirement_messages(stored)
    audited = audit_workout_plan({'requirementsId': stored['requirementsId'],
        'name': 'Program', 'workouts': sessions}, equipment, messages)
    assert audited['passed'], audited['errors']
    calls = []

    def solve(workouts, approved, *_args, **_kwargs):
        calls.append(approved['objectiveOrder'])
        return {'feasible': False, 'status': 'unproven', 'instruction': 'Controlled solver stop.'}

    monkeypatch.setattr(joint_planning, 'solve_prescribed_week', solve)
    result = auto_allocate_workout(audited, equipment, messages)

    assert calls == [['duration_balance']]
    assert result['jointPlanningStopped']
