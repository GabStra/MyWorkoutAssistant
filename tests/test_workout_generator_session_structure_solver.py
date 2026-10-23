import copy

from workout_generator_pkg import joint_planning
from test_workout_generator_planning_tools import planning_case


def _session_with_duplicate_exercises(count, *, group_size=0):
    equipment, requirements, _, draft = planning_case()
    requirements['sessionsPerWeek'] = 1
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 5, 'maximum': 6}
    requirements['auditTargets']['perSessionEffectiveSets']['chest'] = {'minimum': 5, 'maximum': 6}
    day = copy.deepcopy(draft['workouts'][0])
    day['exercises'] = []
    for index in range(count):
        item = copy.deepcopy(draft['workouts'][0]['exercises'][0])
        item.pop('placementNotes', None)
        item['superset'] = 'PAIR' if index < group_size else None
        day['exercises'].append(item)
    return equipment, requirements, [day]


def test_joint_solver_enforces_approved_session_exercise_limit():
    equipment, requirements, sessions = _session_with_duplicate_exercises(2)
    requirements['executionRules'] = [{'kind': 'sessionStructure', 'maximumExercises': 1}]

    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment)

    assert result['feasible'], result
    assert len(result['sessions'][0]['exercises']) == 1
    assert result['audit']['errors'] == []


def test_joint_solver_filters_oversized_group_but_keeps_standalone_recipe():
    equipment, requirements, sessions = _session_with_duplicate_exercises(5, group_size=4)
    requirements['executionRules'] = [{'kind': 'sessionStructure', 'maximumSupersetSize': 3}]

    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment)

    assert result['feasible'], result
    assert len(result['sessions'][0]['exercises']) == 1
    assert result['sessions'][0]['exercises'][0]['superset'] is None
    assert any(rejected.get('limit') == 'maximumSupersetSize'
        for rejected in result['rejectedOptions'])
    assert result['audit']['errors'] == []


def test_joint_solver_enforces_optional_superset_count_limit():
    equipment, requirements, sessions = _session_with_duplicate_exercises(3, group_size=2)
    requirements['executionRules'] = [{'kind': 'sessionStructure', 'maximumSupersets': 0}]

    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment)

    assert result['feasible'], result
    assert len(result['sessions'][0]['exercises']) == 1
    assert result['sessions'][0]['exercises'][0]['superset'] is None
    assert result['audit']['errors'] == []


def test_joint_solver_does_not_relax_volume_to_meet_exercise_cap():
    equipment, requirements, sessions = _session_with_duplicate_exercises(2)
    requirements['executionRules'] = [
        {'kind': 'sessionStructure', 'maximumExercises': 1},
        {'kind': 'workSets', 'coverageKey': None, 'minimumSets': 2, 'maximumSets': 3},
    ]

    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment)

    assert not result['feasible'], result
    assert requirements['auditTargets']['weeklyEffectiveSets']['chest'] == {'minimum': 5, 'maximum': 6}
