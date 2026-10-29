from workout_generator_pkg.allocation import _milp_solve
from workout_generator_pkg.generation_audit import audit_exercise_exposure
from workout_generator_pkg.programming_guidelines import (
    EXECUTION_RULES_SCHEMA, exercise_exposure_counts, execution_rule_errors,
)


def test_exposure_counts_merge_variants_and_count_duplicate_occurrences_once_per_session():
    draft = {'workouts': [
        {'timesCompletedInAWeek': 2, 'exercises': [
            {'definition_id': 'LIBRARY_0', 'numWorkSets': 3},
            {'definition_id': 'LIBRARY_1', 'numWorkSets': 2}]},
        {'timesCompletedInAWeek': 1, 'exercises': [
            {'definition_id': 'LIBRARY_1', 'numWorkSets': 4}]},
    ]}
    plan = {'exercises': [
        {'id': 'LIBRARY_0', 'libraryDefinitionId': 'canonical-a'},
        {'id': 'LIBRARY_1', 'libraryDefinitionId': 'canonical-a'},
    ]}

    counts, unknown = exercise_exposure_counts(draft, plan)

    assert not unknown
    assert counts == {
        'canonical-a': {'weeklyWorkingSets': 14, 'weeklySessions': 3},
    }


def test_zero_set_menu_occurrence_does_not_count_toward_session_cap():
    counts, unknown = exercise_exposure_counts({'workouts': [{'timesCompletedInAWeek': 1,
        'exercises': [{'definition_id': 'canonical-a', 'numWorkSets': 0}]}]})
    assert not unknown and counts == {}


def test_exposure_rule_schema_requires_a_cap_and_rejects_duplicates():
    from jsonschema import ValidationError, validate
    import pytest

    validate([{'kind': 'exerciseExposure', 'maximumSessionsPerWeek': 2,
        'maximumWeeklySets': 12}], EXECUTION_RULES_SCHEMA)
    with pytest.raises(ValidationError):
        validate([{'kind': 'exerciseExposure'}], EXECUTION_RULES_SCHEMA)
    assert not execution_rule_errors({'requiredCoverage': [], 'executionRules': [
        {'kind': 'exerciseExposure', 'maximumWeeklySets': 12}]})
    errors = execution_rule_errors({'requiredCoverage': [], 'executionRules': [
        {'kind': 'exerciseExposure', 'maximumWeeklySets': 12},
        {'kind': 'exerciseExposure', 'maximumSessionsPerWeek': 2}]})
    assert errors[0]['code'] == 'duplicate_exercise_exposure_rule'


def test_export_audit_uses_canonical_exercise_definition_id_and_skips_disabled_items():
    package = {'workouts': [
        {'timesCompletedInAWeek': 2, 'workoutComponents': [
            {'type': 'Exercise', 'libraryDefinitionId': 'canonical-a', 'numWorkSets': 5},
            {'type': 'Exercise', 'exerciseDefinitionId': 'canonical-a', 'numWorkSets': 2},
            {'type': 'Exercise', 'exerciseDefinitionId': 'unknown-occurrence-id', 'numWorkSets': 8,
             'enabled': False}]},
        {'timesCompletedInAWeek': 1, 'workoutComponents': [
            {'type': 'Exercise', 'exerciseDefinitionId': 'canonical-a', 'numWorkSets': 3}]},
        {'enabled': False, 'timesCompletedInAWeek': 1, 'workoutComponents': [
            {'type': 'Exercise', 'exerciseDefinitionId': 'unknown-disabled-workout', 'numWorkSets': 9}]},
    ]}
    report = {'errors': [], 'issues': []}
    requirements = {'executionRules': [{'kind': 'exerciseExposure',
        'maximumSessionsPerWeek': 2, 'maximumWeeklySets': 19}]}

    audit_exercise_exposure(report, package, requirements, {'canonical-a': 'canonical-a'})

    assert report['weeklyExerciseExposure'] == {
        'canonical-a': {'weeklyWorkingSets': 17, 'weeklySessions': 3}}
    assert {item['code'] for item in report['errors']} == {
        'exercise_sessions_above_maximum'}


def test_export_audit_fails_closed_when_active_identity_is_unmapped():
    report = {'errors': [], 'issues': []}
    audit_exercise_exposure(report, {'workouts': [{'workoutComponents': [
        {'type': 'Exercise', 'id': 'fresh-occurrence', 'numWorkSets': 2}]}]},
        {'executionRules': [{'kind': 'exerciseExposure', 'maximumWeeklySets': 5}]}, {})
    assert report['errors'][0]['code'] == 'exercise_exposure_identity_unknown'


def test_presence_cap_counts_distinct_sessions_not_duplicate_exercises():
    variables = [
        {'lower': 1, 'upper': 1, 'minimumWhenSelected': 1, 'members': [], 'current': []},
        {'lower': 1, 'upper': 1, 'minimumWhenSelected': 1, 'members': [], 'current': []},
    ]
    required = [(('first',), 1, 1, 0, [1, 0]), (('second',), 1, 1, 0, [0, 1])]

    same_session, counts = _milp_solve(variables, required, presence_caps=[{
        'definitionId': 'canonical-a', 'maximum': 1, 'groups': [([0, 1], 1)]}])
    assert same_session == 'optimal' and counts == [1, 1]

    separate_sessions, counts = _milp_solve(variables, required, presence_caps=[{
        'definitionId': 'canonical-a', 'maximum': 1, 'groups': [([0], 1), ([1], 1)]}])
    assert separate_sessions == 'infeasible' and counts is None


def test_prepared_menu_solver_enforces_per_definition_weekly_set_cap():
    from workout_generator_pkg.allocation import allocate_prepared_sets

    sessions = [{'name': 'Day A', 'timesCompletedInAWeek': 1, 'exercises': [
        {'definition_id': 'LIBRARY_0', 'numWorkSets': 2,
         'allocationBounds': {'minimum': 1, 'maximum': 3}, 'superset': None, 'satisfiesCoverage': []},
        {'definition_id': 'LIBRARY_1', 'numWorkSets': 2,
         'allocationBounds': {'minimum': 1, 'maximum': 3}, 'superset': None, 'satisfiesCoverage': []},
    ]}]
    candidates = {reference: {'creditsPerWorkingSet': {'chest': {'direct': 1, 'indirect': 0}}}
        for reference in ('LIBRARY_0', 'LIBRARY_1')}
    requirements = {'auditTargets': {'weeklyEffectiveSets': {'chest': {'minimum': 3, 'maximum': 3}},
        'perSessionEffectiveSets': {}}, 'executionRules': [{'kind': 'exerciseExposure',
            'maximumWeeklySets': 2}]}
    equipment = {'exerciseDefinitions': [{'id': 'definition-a'}, {'id': 'definition-b'}]}

    result = allocate_prepared_sets(sessions, candidates, requirements, equipment=equipment,
        select_movements=True)

    assert result['feasible']
    assert sum(item['numWorkSets'] for item in result['sessions'][0]['exercises']) == 3
    assert all(item['numWorkSets'] <= 2 for item in result['sessions'][0]['exercises'])


def test_joint_selection_spreads_one_definition_across_distinct_session_cap():
    import copy
    from test_workout_generator_joint_prescriptions import two_recipe_order_case
    from workout_generator_pkg import joint_planning

    equipment, requirements, sessions = two_recipe_order_case()
    requirements['sessionsPerWeek'] = 2
    requirements['objectiveOrder'] = []
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 10, 'maximum': 10}
    requirements['auditTargets'].pop('perSessionEffectiveSets', None)
    requirements['auditTargets']['maximumSessionSeconds'] = None
    requirements['requiredCoverage'] = []
    requirements['executionRules'] = [{'kind': 'exerciseExposure', 'maximumSessionsPerWeek': 1}]
    for day in sessions:
        for item in day['exercises']:
            item['satisfiesCoverage'] = []
    second = copy.deepcopy(sessions[0])
    second.update(name='Day B', trainingDays=[2])
    sessions.append(second)

    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment)

    assert result['feasible'], result
    by_day = [{item['definition_id']: item['numWorkSets'] for item in day['exercises']}
        for day in result['sessions']]
    assert [set(day) for day in by_day] == [{'LIBRARY_0'}, {'LIBRARY_1'}]
    exposure = result['audit']['weeklyExerciseExposure']
    assert {item['weeklySessions'] for item in exposure.values()} == {1}
    assert sum(item['weeklyWorkingSets'] for item in exposure.values()) == 10
