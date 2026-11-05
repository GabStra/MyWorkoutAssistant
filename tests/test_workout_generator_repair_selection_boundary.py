import copy

import pytest

from workout_generator_pkg import alternative_repair
from test_workout_generator_alternative_repair import _repair_scope_case, _stub_repair_preconditions


@pytest.mark.parametrize('dimension', ['prescription', 'ordering', 'exercise_selection', 'session_timing'])
def test_nonmetadata_repair_without_solver_candidate_has_only_the_none_choice(dimension):
    from workout_generator_pkg.planning_tools import coordinated_repair_tool

    task = {'requirementsId': 'REQ', 'baseDraftId': 'DRAFT', 'preferSparseEdits': True,
        'currentDraft': {'workouts': [{'exercises': [{'definition_id': 'LIBRARY_0'}]}]},
        'findingsAssessment': {'groups': [{'disposition': 'repair',
            'findingIndexes': [0], 'repairDimensions': [dimension]}]}}
    schema = coordinated_repair_tool(task)['function']['parameters']
    assert schema['properties']['useSolverMenu']['const'] is False
    assert not {'edits', 'sessionBlocks', 'workoutUpdates'}.intersection(schema['properties'])
    assert 'useSolverMenu' in schema['required']


@pytest.mark.parametrize('selection', [False, 'legacy_edits'])
def test_alternative_repair_uses_current_code_menu_or_stops_before_any_mutation(monkeypatch, selection):
    _stub_repair_preconditions(monkeypatch)
    candidate, arguments = _repair_scope_case()
    candidate['solverMenu'] = {'feasible': False}
    before = copy.deepcopy(candidate)
    if selection is False:
        arguments.pop('edits')
        arguments['useSolverMenu'] = False
    monkeypatch.setattr(alternative_repair, '_audit_candidate',
        lambda *_: pytest.fail('An unselected or legacy repair must not enter native audit.'))

    result = alternative_repair.execute_repair(arguments, candidate, [], {}, None, True, None)

    assert candidate == before
    assert not result['passed'] and result['failureStage'] == 'repair_admission'
    if selection is False:
        assert result['errors'][0]['code'] == 'solver_menu_declined'
        assert result['userQuestion']['question']
    else:
        assert result['errors'][0]['code'] == 'invalid_arguments'
        assert result['candidateSnapshot'] == candidate


def test_active_repair_cannot_bypass_public_selection_by_submitting_legacy_edits(monkeypatch):
    from jsonschema import ValidationError
    from workout_generator_pkg import interactive_shell, planning_tools

    task = {'requirementsId': 'REQ', 'baseDraftId': 'DRAFT'}
    draft = {'requirementsId': 'REQ', 'name': 'Saved workout', 'workouts': []}
    before = copy.deepcopy(draft)
    monkeypatch.setattr(planning_tools, 'compile_coordinated_repair',
        lambda *_args, **_kwargs: pytest.fail('Unselected model edits cannot reach the internal compiler.'))
    with pytest.raises(ValidationError):
        interactive_shell._admit_repair_scope(
            {**task, 'edits': {'workoutOrder': []}}, task, draft, [], 0, 2, {})
    assert draft == before
