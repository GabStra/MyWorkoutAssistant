import copy

import pytest

from workout_generator_pkg.planning_tools import (
    PlanningInputError, build_draft_plan, planning_tool_failure,
)
from test_workout_generator_planning_tools import planning_case


def test_direction_counting_gap_is_a_question_before_prescriptions_are_normalized():
    equipment, requirements, _, draft = planning_case()
    exercise = draft['workouts'][0]['exercises'][0]
    exercise['satisfiesCoverage'] = ['rotational_core']
    exercise['intraSetRestInSeconds'] = 15
    before = copy.deepcopy(draft)

    with pytest.raises(PlanningInputError) as caught:
        build_draft_plan(draft, equipment, requirements)

    assert caught.value.code == 'execution_semantics_unresolved'
    assert draft == before
    result = planning_tool_failure('audit_workout_plan', caught.value, draft)
    assert result['userQuestion']['executionChoices'] == [
        {'definition_id': exercise['definition_id'], 'path': '/workouts/0/exercises/0'}]
    assert len(result['userQuestion']['options']) == 2
    assert 'record_planning_decisions' in result['instruction']


def test_compiled_direction_choice_controls_counting_and_rendered_guidance():
    equipment, requirements, _, draft = planning_case()
    original = copy.deepcopy(equipment)
    item = draft['workouts'][0]['exercises'][0]
    item['satisfiesCoverage'] = ['rotational_core']
    definition = copy.deepcopy(equipment['exerciseDefinitions'][0])
    definition['reviewedExecution'] = {'limbMode': 'bilateral', 'setMode': 'paired_sides'}
    overrides = {definition['id']: definition}

    plan = build_draft_plan(draft, equipment, requirements, execution_definitions=overrides)
    selected = plan['exercises'][0]
    assert selected['satisfiesCoverage'] == ['rotational_core']
    assert selected['intraSetRestInSeconds'] > 0
    assert 'both sides' in selected['notes']
    assert 'Paired-side/direction work' in selected['notes']
    assert equipment == original

    definition['reviewedExecution']['setMode'] = 'single_sequence'
    plan = build_draft_plan(draft, equipment, requirements, execution_definitions=overrides)
    selected = plan['exercises'][0]
    assert selected['intraSetRestInSeconds'] is None
    assert 'total for one complete execution sequence' in selected['notes']
    assert 'both sides' not in selected['notes']
    assert equipment == original
