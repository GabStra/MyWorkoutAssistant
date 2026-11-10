import copy

import pytest

from workout_generator_pkg import joint_planning as joint
from workout_generator_pkg.allocation import _audit_raw
from workout_generator_pkg.generation_audit import audit_required_exercises
from workout_generator_pkg.planning_tools import PlanningInputError, set_workout_requirements
from workout_generator_pkg.programming_policy import resolve_exercise_choices


def choice_case():
    from test_workout_generator_joint_prescriptions import two_recipe_order_case

    equipment, requirements, sessions = two_recipe_order_case()
    equipment['exerciseDefinitions'][0]['name'] = 'Low Setup Press'
    equipment['exerciseDefinitions'][1]['name'] = 'Preferred Protected Press'
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 4, 'maximum': 4}
    requirements['auditTargets']['perSessionEffectiveSets'] = {}
    requirements['auditTargets']['maximumSessionSeconds'] = 5000
    requirements['requiredCoverage'] = [{'key': 'press', 'scope': 'weekly', 'description': 'Press work'}]
    requirements['executionRules'] = [{'kind': 'workSets', 'coverageKey': None, 'minimumSets': 2, 'maximumSets': 6}]
    requirements['objectiveOrder'] = ['exercise_preference', 'workload_economy', 'duration_economy']
    requirements['exerciseSelection'] = {'preferredMinimum': 0, 'preferredMaximum': 3, 'muscles': ['chest'],
        'preferredByCoverage': {'press': ['Preferred Protected Press']}}
    for item in sessions[0]['exercises']:
        item.update(numWorkSets=2, satisfiesCoverage=['press'])
    return equipment, requirements, sessions


@pytest.mark.parametrize('require_other', [False, True])
def test_solver_respects_required_choice_and_preference_before_setup_cost(require_other):
    equipment, requirements, sessions = choice_case()
    if require_other:
        requirements['exerciseSelection']['requiredNames'] = ['Low Setup Press']
    result = joint.solve_prescribed_week(sessions, requirements, equipment)
    assert result['feasible'], result
    assert not result['audit']['errors']
    items = result['sessions'][0]['exercises']
    assert result['audit']['weeklyWorkingSets'] == 4
    # An unavoidable nonpreferred choice is not improved by adding token preferred work.
    assert {item['definition_id'] for item in items} == ({'LIBRARY_0'} if require_other else {'LIBRARY_1'})
    assert next(stage for stage in result['objectiveProgress'] if stage['goal'] == 'exercise_preference')['value'] == int(require_other)
    definitions = {f'LIBRARY_{index}': definition for index, definition in enumerate(
        sorted(equipment['exerciseDefinitions'], key=lambda item: item['id']))}
    scored = joint._joint_candidate_objective_costs(
        {'workouts': result['sessions'], 'audit': result['audit']}, requirements, {'setupDefinitions': definitions})
    assert scored['exercise_preference'] == int(require_other)


def test_required_choice_audit_rejects_equivalent_muscle_substitute():
    equipment, requirements, sessions = choice_case()
    requirements['exerciseSelection']['requiredNames'] = ['Preferred Protected Press']
    sessions[0]['exercises'] = [sessions[0]['exercises'][0]]
    sessions[0]['exercises'][0]['numWorkSets'] = 4
    _, audit = _audit_raw({'name': 'Choices', 'workouts': sessions}, equipment, requirements, {}, True)
    assert [error['code'] for error in audit['errors']] == ['required_exercise_missing']
    # The emitter guard checks actual definition identity, not display-name copies.
    report = {'issues': [], 'errors': []}
    audit_required_exercises(report, {'workouts': [{'workoutComponents': [{'type': 'Exercise',
        'name': 'Preferred Protected Press', 'exerciseDefinitionId': 'press',
        'sets': [{'subCategory': 'WorkSet'}]}]}]}, requirements, equipment)
    assert report['errors'][0]['code'] == 'required_exercise_missing'


def test_named_choice_rejects_missing_or_ambiguous_library_identity():
    equipment, requirements, _ = choice_case()
    duplicate = copy.deepcopy(equipment['exerciseDefinitions'][1])
    duplicate['id'] = 'different'
    for library in [[], [equipment['exerciseDefinitions'][1], duplicate]]:
        with pytest.raises(PlanningInputError) as error:
            resolve_exercise_choices(requirements, {'exerciseDefinitions': library})
        assert error.value.code == 'exercise_choice_unresolved'


def test_required_choice_missing_from_executable_menu_cannot_pass_solver():
    equipment, requirements, sessions = choice_case()
    requirements['exerciseSelection']['requiredNames'] = ['Preferred Protected Press']
    sessions[0]['exercises'] = sessions[0]['exercises'][:1]
    result = joint.solve_prescribed_week(sessions, requirements, equipment)
    assert not result['feasible'], result


def test_required_choice_cannot_silently_override_exclusion():
    from test_workout_generator_planning_tools import planning_case

    equipment, requirements, _, _ = planning_case()
    requirements['exerciseSelection'] = {'preferredMinimum': 0, 'preferredMaximum': 3,
        'muscles': ['chest'], 'requiredNames': ['Push-Up']}
    requirements['exerciseRestrictions'] = {'excludeNameTerms': ['Push-Up'], 'exceptNameTerms': []}
    with pytest.raises(PlanningInputError) as error:
        set_workout_requirements(requirements, [{'role': 'user', 'content': 'Include and exclude Push-Up.'}], equipment)
    assert error.value.code == 'required_exercise_excluded'
