import copy
import time

from workout_generator_pkg import joint_planning as joint
from workout_generator_pkg.domain_ops import build_workout_structure
from workout_generator_pkg.programming_guidelines import (
    prescribe_block_recovery, audit_execution_rules)


def rule(category=None, lower=90, upper=150):
    value = {'kind': 'rest', 'coverageKey': None, 'context': 'exerciseTransition',
        'minimumSeconds': lower, 'maximumSeconds': upper}
    if category:
        value['exerciseCategory'] = category
    return value


def test_between_set_recovery_does_not_invent_a_between_block_rest():
    from test_workout_generator_planning_tools import planning_case
    from workout_generator_pkg.planning_tools import build_draft_plan

    equipment, _, stored, draft = planning_case()
    equipment['exerciseDefinitions'][0]['exerciseCategory'] = 'ISOLATION'
    item = draft['workouts'][0]['exercises'][0]
    draft['workouts'][0]['exercises'] = [copy.deepcopy(item), copy.deepcopy(item)]
    requirements = copy.deepcopy(stored['requirements'])
    assert not any(rule.get('context') == 'exerciseTransition'
                   for rule in requirements['executionRules'])

    plan = build_draft_plan(draft, equipment, requirements)
    assert plan['workouts'][0]['restToNextSeconds'] == [0, 0]
    structure = build_workout_structure(plan['workouts'][0])
    assert [component['componentType'] for component in structure['workoutComponents']] == [
        'Exercise', 'Exercise']

    requirements['executionRules'].append(rule('ISOLATION', 120, 120))
    explicit = build_draft_plan(draft, equipment, requirements)
    assert explicit['workouts'][0]['restToNextSeconds'] == [120, 0]
    structure = build_workout_structure(explicit['workouts'][0])
    assert [component['componentType'] for component in structure['workoutComponents']] == [
        'Exercise', 'Rest', 'Exercise']

    draft['workouts'][0]['exercises'][-1]['restAfterExerciseSeconds'] = 45
    terminal = build_draft_plan(draft, equipment, requirements)
    assert terminal['workouts'][0]['restToNextSeconds'] == [120, 0]
    structure = build_workout_structure(terminal['workouts'][0])
    assert [component['componentType'] for component in structure['workoutComponents']] == [
        'Exercise', 'Rest', 'Exercise']


def test_terminal_rest_value_does_not_emit_a_component_after_the_session():
    structure = build_workout_structure({
        'id': 'WORKOUT_0', 'name': 'Day',
        'exerciseIds': ['EXERCISE_0', 'EXERCISE_1'],
        'restToNextSeconds': [0, 60],
        'supersetGroups': [],
    })
    assert [component['componentType'] for component in structure['workoutComponents']] == [
        'Exercise', 'Exercise']


def test_one_round_superset_recovers_after_whole_block_not_after_session():
    block = [{'definition_id': key, 'superset': 'pair' if key != 'last' else None,
        'numWorkSets': 1, 'satisfiesCoverage': [], 'restAfterExerciseSeconds': 0,
        'restAfterSupersetExerciseSeconds': 0} for key in ['heavy', 'isolation', 'last']]
    day = {'name': 'Day', 'exercises': block}
    definitions = {key: {'exerciseCategory': category} for key, category in [
        ('heavy', 'HEAVY_COMPOUND'), ('isolation', 'ISOLATION'), ('last', 'ISOLATION')]}
    req = {'executionRules': [rule('HEAVY_COMPOUND', 120, 180), rule('ISOLATION', 60, 120)]}
    plan = {'exercises': [{'id': key, **value} for key, value in definitions.items()],
        'workouts': [{'exerciseIds': list(definitions)}]}
    report = {'issues': [], 'errors': []}
    audit_execution_rules({'workouts': [day]}, req, report, plan)
    assert len(report['errors']) == 1
    assert report['errors'][0]['path'].endswith('/1/restAfterExerciseSeconds')
    prescribe_block_recovery(day, req, definitions)
    assert [x['restAfterExerciseSeconds'] for x in block] == [0, 120, 0]
    assert [x['restAfterSupersetExerciseSeconds'] for x in block] == [0, 0, 0]
    report = {'issues': [], 'errors': []}
    audit_execution_rules({'workouts': [day]}, req, report, plan)
    assert not report['errors']
    emitted = build_workout_structure({'id': 'WORKOUT_0', 'name': 'Day',
        'exerciseIds': list(definitions), 'restToNextSeconds': [0, 120, 0],
        'supersetGroups': [{'exerciseIds': ['heavy', 'isolation'],
            'restSecondsByExercise': {'heavy': 0, 'isolation': 0}}]})
    assert [c['componentType'] for c in emitted['workoutComponents']] == ['Superset', 'Rest', 'Exercise']
    assert emitted['workoutComponents'][1]['timeInSeconds'] == 120


def test_transition_recovery_is_emitted_and_terminal_recovery_is_zero():
    from test_workout_generator_joint_prescriptions import two_recipe_order_case
    equipment, requirements, sessions = two_recipe_order_case()
    requirements['executionRules'] = [rule(lower=91, upper=91)]
    result = joint.solve_prescribed_week(sessions, requirements, equipment,
        preserve_source_selection=True, search_deadline=time.monotonic() + 12)
    assert result['feasible'], result
    assert 'splitArchitecture' not in result
    emitted = result['sessions'][0]['exercises']
    assert [e['restAfterExerciseSeconds'] for e in emitted] == [91, 0]
