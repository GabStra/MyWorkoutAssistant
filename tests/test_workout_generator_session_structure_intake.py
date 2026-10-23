import copy

from workout_generator_pkg.programming_guidelines import (
    MINIMUM_WORK_SETS_RULE, SESSION_STRUCTURE_RULE, session_structure_limits,
)
from workout_generator_pkg.planning_tools import (
    _latest_result, requirements_approved, set_workout_requirements, workout_requirements_tool,
)
from workout_generator_pkg.programming_guidelines import render_execution_rule
from test_workout_generator_planning_tools import planning_case, requirement_messages


def test_fresh_requirements_show_and_approve_code_owned_session_structure_bounds():
    equipment, requirements, _, _ = planning_case()
    messages = [{'role': 'user', 'content': 'Plan 5-6 chest sets.'}]

    candidate = set_workout_requirements(requirements, messages, equipment)

    assert candidate['requirements']['executionRules'] == [
        MINIMUM_WORK_SETS_RULE, SESSION_STRUCTURE_RULE]
    assert render_execution_rule(SESSION_STRUCTURE_RULE) in candidate['requirementsPreview']
    assert session_structure_limits(candidate['requirements']) == {
        'maximumExercises': 15, 'maximumSupersetSize': 3}
    assert requirements_approved(requirement_messages(candidate))

    rules_schema = workout_requirements_tool(equipment)['function']['parameters']['properties']['executionRules']
    structure_schema = next(rule for rule in rules_schema['items']['oneOf']
        if rule['properties']['kind'].get('const') == 'sessionStructure')
    assert structure_schema['required'] == ['kind']
    assert {field: structure_schema['properties'][field]['maximum'] for field in (
        'maximumExercises', 'maximumSupersets', 'maximumSupersetSize')} == {
            'maximumExercises': 100, 'maximumSupersets': 50, 'maximumSupersetSize': 100}


def test_explicit_stricter_structure_limits_survive_sparse_update_without_mutating_approved_base():
    equipment, requirements, _, _ = planning_case()
    requirements['executionRules'] = [{'kind': 'sessionStructure',
        'maximumExercises': 10, 'maximumSupersetSize': 2}]
    source = [{'role': 'user', 'content': 'Use no more than ten exercises and two superset members.'}]
    explicit = set_workout_requirements(requirements, source, equipment)
    assert explicit['requirements']['executionRules'] == [
        {'kind': 'sessionStructure', 'maximumExercises': 10, 'maximumSupersetSize': 2},
        MINIMUM_WORK_SETS_RULE]
    assert session_structure_limits(explicit['requirements']) == {
        'maximumExercises': 10, 'maximumSupersetSize': 2}

    # A stored approval from before the new default is introduced remains unchanged.
    legacy_approved = copy.deepcopy(explicit)
    legacy_approved['requirements']['executionRules'] = [MINIMUM_WORK_SETS_RULE]
    legacy_approved['requirementsId'] = 'REQUIREMENTS_PRE_STRUCTURE_DEFAULT'
    from workout_generator_pkg.planning_tools import render_requirements
    legacy_approved['requirementsPreview'] = render_requirements(
        legacy_approved['requirements'], confirmation=True)
    approved_messages = requirement_messages(legacy_approved)
    assert requirements_approved(approved_messages)
    approved_messages.append({'role': 'user', 'content': 'Update the session count to two.'})

    updated = set_workout_requirements({
        'baseRequirementsId': legacy_approved['requirementsId'],
        'updates': {'sessionsPerWeek': 2},
    }, approved_messages, equipment)

    assert updated['requirements']['executionRules'] == [
        MINIMUM_WORK_SETS_RULE, SESSION_STRUCTURE_RULE]
    assert '`/executionRules`' in updated['requirementsPreview']
    _, saved_base = _latest_result(approved_messages, 'set_workout_requirements')
    assert saved_base['requirements']['executionRules'] == [MINIMUM_WORK_SETS_RULE]
    assert requirements_approved(approved_messages)
