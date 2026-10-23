from copy import deepcopy

from jsonschema import validate

from workout_generator_pkg.programming_guidelines import (
    EXECUTION_RULES_SCHEMA, SESSION_STRUCTURE_RULE, audit_execution_rules,
    execution_rule_errors, render_execution_rule, session_structure_limits,
)


def _audit(exercises, rule=SESSION_STRUCTURE_RULE):
    report = {'issues': [], 'errors': []}
    audit_execution_rules({'workouts': [{'name': 'Session', 'exercises': exercises}]},
                          {'executionRules': [rule]}, report)
    return report['errors']


def test_session_bounds_count_every_member_and_allow_exact_boundaries():
    exercises = [{'superset': 'A'} for _ in range(3)] + [{'superset': None} for _ in range(12)]
    assert not _audit(exercises)
    errors = _audit(exercises + [{'superset': None}])
    assert [(error['limit'], error['actual']) for error in errors] == [('maximumExercises', 16)]
    oversized = deepcopy(exercises)
    oversized[3]['superset'] = 'A'
    errors = _audit(oversized)
    assert [(error['limit'], error['actual']) for error in errors] == [('maximumSupersetSize', 4)]
    assert errors[0]['path'] == '/workouts/0/exercises'
    assert errors[0]['rulePath'] == '/executionRules/0'


def test_explicit_superset_count_and_stricter_bounds_intersect():
    rules = [SESSION_STRUCTURE_RULE, {'kind': 'sessionStructure', 'maximumExercises': 8,
                                   'maximumSupersets': 0}]
    requirements = {'executionRules': rules}
    validate(rules, EXECUTION_RULES_SCHEMA)
    assert not execution_rule_errors(requirements)
    assert session_structure_limits(requirements) == {
        'maximumExercises': 8, 'maximumSupersetSize': 3, 'maximumSupersets': 0}
    assert not _audit([{'superset': None}], rules[1])
    errors = _audit([{'superset': 'A'}, {'superset': 'A'}], rules[1])
    assert [(error['limit'], error['actual']) for error in errors] == [('maximumSupersets', 1)]
    assert execution_rule_errors({'executionRules': [{'kind': 'sessionStructure'}]})
    assert 'including every superset member' in render_execution_rule(SESSION_STRUCTURE_RULE)
