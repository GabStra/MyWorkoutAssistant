import copy

import pytest

from workout_generator_pkg import joint_planning as joint
from workout_generator_pkg.generation_audit import audit_semantic_selection
from test_workout_generator_exercise_choices import choice_case


def test_numeric_preferences_cannot_replace_semantically_selected_main_work():
    equipment, requirements, sessions = choice_case()
    selection = {'mode': 'selected_menu', 'definitionIds': ['press']}
    result = joint.solve_prescribed_week(sessions, requirements, equipment, semantic_selection=selection)
    assert result['feasible'], result
    assert {item['definition_id'] for day in result['sessions'] for item in day['exercises']} == {'LIBRARY_0'}
    assert result['audit']['weeklyWorkingSets'] == 4
    assert result['semanticSelection']['definitionIds'] == ['press']


def test_selected_menu_keeps_every_member_but_allows_weekly_placement():
    equipment, requirements, sessions = choice_case()
    requirements['sessionsPerWeek'] = 2
    sessions[0]['trainingDays'] = [0]
    sessions.append(copy.deepcopy(sessions[0]))
    sessions[1].update(name='Second session', trainingDays=[2])
    selection = {'mode': 'selected_menu', 'definitionIds': ['press', 'row']}
    result = joint.solve_prescribed_week(sessions, requirements, equipment, semantic_selection=selection)
    assert result['feasible'], result
    assert result['audit']['weeklyWorkingSets'] == 4
    assert sorted(len(day['exercises']) for day in result['sessions']) == [1, 1]
    assert {item['definition_id'] for day in result['sessions'] for item in day['exercises']} == {'LIBRARY_0', 'LIBRARY_1'}


def test_selected_member_missing_from_executable_options_is_not_dropped():
    equipment, requirements, sessions = choice_case()
    sessions[0]['exercises'] = sessions[0]['exercises'][:1]
    result = joint.solve_prescribed_week(sessions, requirements, equipment,
        semantic_selection={'mode': 'selected_menu', 'definitionIds': ['press', 'row']})
    assert not result['feasible'], result


def test_semantic_menu_audit_checks_real_identity_and_ignores_fixed_prefix():
    equipment, _, sessions = choice_case()
    selection = {'mode': 'selected_menu', 'definitionIds': ['row'], 'fixedWorkouts': [sessions[0]]}
    report = {'issues': [], 'errors': []}
    package = {'workouts': [sessions[0], {'exercises': [sessions[0]['exercises'][1]]}]}
    audit_semantic_selection(report, package, selection, equipment)
    assert not report['errors']
    package['workouts'][1]['exercises'] = [sessions[0]['exercises'][0]]
    audit_semantic_selection(report, package, selection, equipment)
    assert report['errors'][0]['code'] == 'semantic_menu_changed'
    assert report['errors'][0]['missingDefinitionIds'] == ['row']
    assert report['errors'][0]['unexpectedDefinitionIds'] == ['press']


def test_solver_problem_identity_carries_the_semantic_choice():
    equipment, requirements, sessions = choice_case()
    fingerprints = [joint.joint_problem_fingerprint(sessions, requirements, equipment,
        semantic_selection={'mode': 'selected_menu', 'definitionIds': [identifier]})
        for identifier in ('press', 'row')]
    assert fingerprints[0] != fingerprints[1]


@pytest.mark.parametrize('full_week_call', [False, True])
def test_shared_semantic_scope_preserves_fixed_prefix(full_week_call):
    equipment, requirements, sessions = choice_case()
    third = copy.deepcopy(equipment['exerciseDefinitions'][0])
    third.update(id='zzz', name='Retained movement')
    equipment['exerciseDefinitions'].append(third)
    fixed = copy.deepcopy(sessions[0])
    fixed.update(name='Fixed session', trainingDays=[0])
    fixed['exercises'] = [copy.deepcopy(sessions[0]['exercises'][0])]
    fixed['exercises'][0].update(definition_id='LIBRARY_2', numWorkSets=2)
    sessions[0]['trainingDays'] = [2]
    sessions.append(copy.deepcopy(sessions[0]))
    sessions[1].update(name='Variable second', trainingDays=[4])
    requirements['sessionsPerWeek'] = 3
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 6, 'maximum': 6}
    selection = {'mode': 'selected_menu', 'definitionIds': ['press', 'row'], 'fixedWorkouts': [fixed]}
    existing = {'name': 'Retained workouts', 'workouts': [fixed]}
    expected_fp = joint.joint_problem_fingerprint(sessions, requirements, equipment, existing=existing,
        semantic_selection=selection)
    full_fp = joint.joint_problem_fingerprint([fixed, *sessions], requirements, equipment, semantic_selection=selection)
    assert full_fp == expected_fp
    result = joint.solve_prescribed_week([fixed, *sessions] if full_week_call else sessions,
        requirements, equipment, semantic_selection=selection, **({} if full_week_call else {'existing': existing}))
    assert result['feasible'], result
    assert result['audit']['weeklyWorkingSets'] == 6
    assert result['problemFingerprint'] == expected_fp
    if full_week_call:
        assert result['sessions'][0] == fixed
        assert result['occurrenceLineage'][0] == [[0, 0]]
    variable = result['sessions'][1:] if full_week_call else result['sessions']
    assert {item['definition_id'] for day in variable for item in day['exercises']} == {'LIBRARY_0', 'LIBRARY_1'}


def test_semantic_audit_rejects_changed_fixed_prescriptions():
    equipment, _, sessions = choice_case()
    selection = {'mode': 'selected_menu', 'definitionIds': ['row'], 'fixedWorkouts': [sessions[0]]}
    package = {'workouts': [copy.deepcopy(sessions[0]), {'exercises': [sessions[0]['exercises'][1]]}]}
    package['workouts'][0]['exercises'][0]['numWorkSets'] += 1
    report = {'issues': [], 'errors': []}
    audit_semantic_selection(report, package, selection, equipment)
    assert report['errors'][0]['code'] == 'semantic_fixed_prefix_changed'
