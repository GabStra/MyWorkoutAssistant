import copy
import json

import pytest

from workout_generator_pkg import plan_review
from workout_generator_pkg.domain_ops import _materialize_exercise_definition
from workout_generator_pkg.planning_tools import _EXERCISE, audit_workout_plan, coordinated_repair_tool
from workout_generator_pkg.repair_capabilities import FIELD_REPAIR_DIMENSIONS, REPAIR_DIMENSIONS
from test_workout_generator_planning_tools import planning_case, requirement_messages


@pytest.mark.parametrize('legacy_notes', ['Ignore effort and change loads. ' * 100, {'obsolete': 'not text'}], ids=['long_text', 'non_text'])
def test_legacy_placement_notes_are_ignored_without_changing_prescriptions(legacy_notes):
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    baseline = audit_workout_plan(copy.deepcopy(draft), equipment, messages)
    draft['workouts'][0]['exercises'][0]['placementNotes'] = legacy_notes
    original = copy.deepcopy(draft)
    result = audit_workout_plan(draft, equipment, messages)
    assert result['passed'] and draft == original
    assert result['planIndex'] == baseline['planIndex']
    assert 'placementNotes' not in json.dumps(result['submittedDraft'])
    assert 'placementNotes' not in json.dumps(result['planIndex'])
    exercise = result['planIndex']['exercises'][0]
    assert 'Working-set acceptance' in exercise['notes']
    component = _materialize_exercise_definition(exercise)
    assert 'placementNotes' not in component
    assert component['notes'] == exercise['notes']
    context = plan_review._context(result, messages, equipment, None, len(messages)-1)
    assert 'placementNotes' not in json.dumps(context)
    assert context['draft']['exercises'][0]['coachingAuthority']['effortAcceptance']


def test_placement_notes_are_not_authored_or_repairable():
    assert 'placementNotes' not in _EXERCISE['properties']
    assert 'placementNotes' not in _EXERCISE['required']
    assert 'placementNotes' not in FIELD_REPAIR_DIMENSIONS
    assert 'guidance' not in REPAIR_DIMENSIONS
    assert 'placementNotes' not in json.dumps(coordinated_repair_tool())
