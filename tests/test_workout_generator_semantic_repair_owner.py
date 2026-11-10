import copy
from unittest.mock import patch

import pytest

from workout_generator_pkg import repair_execution, session_drafting
from workout_generator_pkg.planning_tools import PlanningInputError


def _case():
    identifiers = [f'00000000-0000-0000-0000-{index:012d}' for index in range(3)]
    equipment = {'exerciseDefinitions': [
        {'id': identifier, 'name': f'Exercise {index}'}
        for index, identifier in enumerate(identifiers)]}
    fixed = {'name': 'Accepted', 'exercises': [{'definition_id': 'LIBRARY_0', 'numWorkSets': 3}]}
    before = [fixed, {'exercises': [{'definition_id': 'LIBRARY_1', 'numWorkSets': 3}]}]
    after = copy.deepcopy(before)
    after[1]['exercises'][0]['definition_id'] = 'LIBRARY_2'
    selection = {'mode': 'selected_menu', 'definitionIds': [identifiers[1]],
        'fixedWorkouts': [copy.deepcopy(fixed)]}
    context = {'selectionRepairAuthorized': True, 'numericSolverMenuSelected': False,
        'baseDraft': {'workouts': before}}
    return identifiers, equipment, after, selection, context


def _binding(workouts, equipment, context):
    return repair_execution.semantic_selection_for_admitted_repair(workouts, equipment, [],
        requirements_id='REQ', history_fingerprint=None, repair_context=context)


def test_admitted_semantic_replacement_commits_stable_ids_from_complete_mutable_candidate(monkeypatch):
    identifiers, equipment, after, selection, context = _case()
    after.append({'exercises': [{'definition_id': 'LIBRARY_1', 'numWorkSets': 2},
        {'definition_id': 'LIBRARY_2', 'numWorkSets': 3}]})
    original = copy.deepcopy(selection)
    monkeypatch.setattr(session_drafting, 'current_semantic_selection', lambda *_: selection)

    binding = _binding(after, equipment, context)

    assert binding['definitionIds'] == identifiers[1:]
    assert binding['fixedWorkouts'] == selection['fixedWorkouts']
    assert selection == original


@pytest.mark.parametrize('context_override', [
    {'numericSolverMenuSelected': True}, {'selectionRepairAuthorized': False}, {'baseDraft': None},
])
def test_numerical_or_unadmitted_edits_cannot_mint_semantic_membership(monkeypatch, context_override):
    _, equipment, after, selection, context = _case()
    context.update(context_override)
    monkeypatch.setattr(session_drafting, 'current_semantic_selection', lambda *_: selection)

    assert _binding(after, equipment, context) == selection


def test_admitted_semantic_repair_cannot_rebind_the_fixed_prefix(monkeypatch):
    _, equipment, after, selection, context = _case()
    after[0]['exercises'][0]['numWorkSets'] += 1
    monkeypatch.setattr(session_drafting, 'current_semantic_selection', lambda *_: selection)

    with pytest.raises(PlanningInputError) as error:
        _binding(after, equipment, context)

    assert error.value.code == 'semantic_fixed_prefix_changed'


def test_numerical_adjustment_retains_prior_menu_even_when_semantic_edits_were_authorized(monkeypatch):
    _, equipment, _, selection, context = _case()
    workouts = copy.deepcopy(context['baseDraft']['workouts'])
    workouts[1]['exercises'][0]['numWorkSets'] += 1
    monkeypatch.setattr(session_drafting, 'current_semantic_selection', lambda *_: selection)

    assert _binding(workouts, equipment, context) == selection


def test_compiled_semantic_replacement_passes_native_menu_audit_with_its_new_binding(monkeypatch):
    from test_workout_generator_planning_tools import planning_case, requirement_messages
    from workout_generator_pkg.interactive_shell import _admit_repair_scope
    from workout_generator_pkg.json_patching import apply_json_patch
    from workout_generator_pkg.planning_tools import audit_workout_plan

    equipment, _, stored, source = planning_case()
    identifiers, _, _, _, _ = _case()
    first = equipment['exerciseDefinitions'][0]
    first['id'] = identifiers[0]
    second = copy.deepcopy(first)
    second.update(id=identifiers[1], name='Incline Push-Up')
    equipment['exerciseDefinitions'].append(second)
    source['workouts'][0]['exercises'][0].pop('placementNotes')
    messages = requirement_messages(stored)
    selection = {'mode': 'selected_menu', 'definitionIds': [identifiers[0]], 'fixedWorkouts': []}
    monkeypatch.setattr(session_drafting, 'current_semantic_selection', lambda *_: selection)
    task = {'requirementsId': stored['requirementsId'], 'baseDraftId': 'REVISION_0',
        'currentDraft': source, 'replacementDefinitionReferences': ['LIBRARY_1'],
        'reviewFindings': [{'action': 'repair', 'draftPath': '/workouts/0/exercises/0',
            'repairDimensions': ['exercise_selection']}],
        'findingsAssessment': {'groups': [{'disposition': 'repair', 'findingIndexes': [0],
            'repairDimensions': ['exercise_selection']}]}}
    submission = {'requirementsId': stored['requirementsId'], 'baseDraftId': 'REVISION_0',
        'addressedFindingIndexes': [0], 'sessionBlocks': [{'sessionReference': 'WORKOUT_0',
            'blocks': [{'exercises': [{'replaces': 'EXERCISE_0', 'definition_id': 'LIBRARY_1',
                'satisfiesCoverage': []}]}]}]}

    compiled, context = _admit_repair_scope(submission, task, source, messages, len(messages), 2,
        equipment, return_context=True)
    qualified = apply_json_patch(source, compiled['patch'])
    binding = _binding(qualified['workouts'], equipment, context)
    old_audit = audit_workout_plan(qualified, equipment, messages, semantic_selection=selection)
    new_audit = audit_workout_plan(qualified, equipment, messages, semantic_selection=binding)

    assert context['selectionRepairAuthorized'] is True
    assert context['numericSolverMenuSelected'] is False
    assert binding['definitionIds'] == [identifiers[1]]
    assert any(error['code'] == 'semantic_menu_changed' for error in old_audit['errors'])
    assert not any(error['code'] == 'semantic_menu_changed' for error in new_audit['errors'])
    assert new_audit['semanticSelection'] == binding


def test_semantic_repair_schema_offers_only_current_occurrence_choices_and_no_quantities():
    from jsonschema import ValidationError, validate
    from workout_generator_pkg.planning_tools import coordinated_repair_tool

    task = {'requirementsId': 'REQ', 'baseDraftId': 'REVISION_0',
        'currentDraft': {'workouts': [{'exercises': [{'definition_id': 'LIBRARY_0'}]}]},
        'replacementDefinitionReferences': ['LIBRARY_1', 'LIBRARY_2'],
        'replacementDefinitionReferencesByExercise': {'EXERCISE_0': ['LIBRARY_1']},
        'findingsAssessment': {'groups': [{'disposition': 'repair', 'findingIndexes': [0],
            'repairDimensions': ['exercise_selection', 'prescription']}]}}
    schema = coordinated_repair_tool(task)['function']['parameters']
    replacement = {'replaces': 'EXERCISE_0', 'definition_id': 'LIBRARY_1', 'satisfiesCoverage': []}
    submission = {'requirementsId': 'REQ', 'baseDraftId': 'REVISION_0',
        'addressedFindingIndexes': [0], 'sessionBlocks': [{'sessionReference': 'WORKOUT_0',
            'blocks': [{'exercises': [replacement]}]}]}

    validate(submission, schema)
    assert not {'useSolverMenu', 'edits'}.intersection(schema['properties'])
    for invalid_fields in ({'numWorkSets': 4}, {'definition_id': 'LIBRARY_2'}, {'replaces': 'EXERCISE_9'}):
        replacement.update(invalid_fields)
        with pytest.raises(ValidationError):
            validate(submission, schema)
        for field in invalid_fields:
            replacement.pop(field)
        replacement.update(replaces='EXERCISE_0', definition_id='LIBRARY_1')


@pytest.mark.parametrize('explicit_binding', [False, True])
def test_repair_solver_receives_the_committed_binding_without_reselecting_from_its_candidate(
        monkeypatch, explicit_binding):
    _, equipment, workouts, selection, context = _case()
    monkeypatch.setattr(session_drafting, 'current_semantic_selection', lambda *_: selection)
    binding = _binding(workouts, equipment, context) if explicit_binding else selection
    monkeypatch.setattr(repair_execution, 'current_reviewed_joint_source', lambda *_, **__: None)
    with patch('workout_generator_pkg.joint_planning.solve_prescribed_week',
               return_value={'feasible': False, 'status': 'unproven'}) as solve:
        repair_execution.solve_repair_candidate(workouts, {}, equipment, {},
            repair_contract={}, requirements_id='REQ', allow_educated_load_guesses=True,
            training_history=None, messages=[], preserve_source_selection=False,
            redistribution_constraints=[],
            validated_source_working_set_budget={'source': 'unbounded_by_user',
                'variableWeeklyWorkingSets': None},
            **({'semantic_selection': binding} if explicit_binding else {}))

    assert solve.call_args.kwargs['semantic_selection'] == binding
