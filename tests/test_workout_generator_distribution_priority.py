import copy

from workout_generator_pkg import joint_planning
from test_workout_generator_joint_prescriptions import _distribution_solver_case


def _set_count(item, count):
    item.update(numWorkSets=count, targetSetPrescriptions=[
        {'workSetIndex': index, 'reps': 8} for index in range(count)])


def test_distribution_optimizes_worst_targeted_muscle_before_aggregate_and_locks_doses():
    equipment, requirements, sessions, _ = _distribution_solver_case([4, 4, 4])
    requirements['objectiveOrder'] = ['workload_economy', 'distribution']
    requirements['auditTargets']['weeklyEffectiveSets']['back'] = {'minimum': 7, 'maximum': 7}
    definition = copy.deepcopy(equipment['exerciseDefinitions'][0])
    definition.update(id='row', name='Row', muscleGroups=['BACK_UPPER_BACK'], secondaryMuscleGroups=[])
    equipment['exerciseDefinitions'].append(definition)
    for day, count in zip(sessions, [3, 2, 2], strict=True):
        row = copy.deepcopy(day['exercises'][0])
        row.update(definition_id='LIBRARY_1')
        _set_count(row, count)
        day['exercises'].append(row)

    result = joint_planning.solve_prescribed_week(
        sessions, requirements, equipment, preserve_source_selection=True)

    assert result['feasible'], result
    stages = result['objectiveProgress']
    goals = [stage['goal'] for stage in stages]
    assert goals.index('workload_economy') < goals.index('distribution_worst') < goals.index('distribution')
    assert stages[goals.index('distribution')]['weeklyDosesLocked'] is True
    deviations = []
    for muscle in ('chest', 'back'):
        weekly = result['audit']['weeklyVolume'][muscle]['effective']
        deviations.extend(abs(2 * 3 * day['volume'][muscle]['effective'] - 2 * weekly)
            for day in result['audit']['workouts'])
    worst_stage = stages[goals.index('distribution_worst')]
    assert worst_stage['value'] == max(deviations) / 6
    assert worst_stage['solverObjectiveValue'] == max(deviations)
    assert stages[goals.index('distribution')]['value'] == sum(deviations)


def test_distribution_children_stay_at_the_approved_distribution_rank():
    approved_order = ['duration_balance', 'source_balance', 'workload_economy', 'distribution',
        'movement_overlap', 'duration_economy', 'setup_economy', 'exercise_distribution']
    available = {name: True for name in approved_order}
    available['distribution_worst'] = True

    result = joint_planning._ordered_joint_objective_names(
        {'objectiveOrder': approved_order}, available)

    assert result == ['duration_balance', 'source_balance', 'workload_economy',
        'distribution_worst', 'distribution', 'movement_overlap', 'duration_economy',
        'setup_economy', 'exercise_distribution']
