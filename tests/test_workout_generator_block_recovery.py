import copy
import time

from workout_generator_pkg import joint_planning as joint
from workout_generator_pkg.domain_ops import build_workout_structure
from workout_generator_pkg.programming_guidelines import (
    default_block_recovery_rules, prescribe_block_recovery, audit_execution_rules)


def rule(category=None, lower=90, upper=150):
    value = {'kind': 'rest', 'coverageKey': None, 'context': 'exerciseTransition',
        'minimumSeconds': lower, 'maximumSeconds': upper}
    if category:
        value['exerciseCategory'] = category
    return value


def test_defaults_reuse_authoritative_ranges_and_explicit_override():
    straight = {**rule('HEAVY_COMPOUND', 123, 177), 'context': 'straightSets'}
    assert default_block_recovery_rules([straight]) == [rule('HEAVY_COMPOUND', 123, 177)]
    assert default_block_recovery_rules([straight, rule(lower=0, upper=0)]) == []


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


def test_native_timing_includes_executed_recovery_and_excludes_terminal_recovery():
    from test_workout_generator_joint_prescriptions import two_recipe_order_case
    equipment, requirements, sessions = two_recipe_order_case()
    requirements['executionRules'] = [rule(lower=91, upper=91)]
    requirements['auditTargets']['maximumSessionSeconds'] = 10000
    result = joint.solve_prescribed_week(sessions, requirements, equipment,
        preserve_source_selection=True, search_deadline=time.monotonic() + 12)
    assert result['feasible'], result
    assert 'splitArchitecture' not in result
    emitted = result['sessions'][0]['exercises']
    assert [e['restAfterExerciseSeconds'] for e in emitted] == [91, 0]
    before = copy.deepcopy(result['sessions'])
    for day in before:
        for exercise in day['exercises']:
            exercise['restAfterExerciseSeconds'] = 0
    from workout_generator_pkg.allocation import _audit_raw
    old_requirements = {**requirements, 'executionRules': []}
    _, old = _audit_raw({'name': 'Before', 'workouts': before}, equipment, old_requirements, {}, True)
    actual = result['audit']['workouts'][0]['estimatedSeconds']
    assert actual == old['workouts'][0]['estimatedSeconds'] + 91
    requirements['auditTargets']['maximumSessionSeconds'] = actual - 1
    rejected = joint.solve_prescribed_week(sessions, requirements, equipment,
        preserve_source_selection=True, search_deadline=time.monotonic() + 12)
    assert not rejected['feasible']
