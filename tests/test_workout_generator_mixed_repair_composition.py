import copy

import pytest
from jsonschema import ValidationError

from workout_generator_pkg.json_patching import apply_json_patch
from workout_generator_pkg.planning_tools import (
    PlanningInputError,
    compile_coordinated_repair,
    coordinated_repair_tool,
    repair_exercise_domain,
    uses_menu_selection,
)
from workout_generator_pkg.repair_contract import build_repair_contract, repair_contract_errors
from test_workout_generator_planning_tools import planning_case


def mixed_task():
    _, _, stored, draft = planning_case()
    source = draft['workouts'][0]['exercises'][0]
    source.update(numWorkSets=5, targetSetPrescriptions=[
        {'workSetIndex': index, 'reps': 8 + index, 'weight': 20.0} for index in range(5)])
    other = copy.deepcopy(source)
    other.update(definition_id='LIBRARY_2', numWorkSets=3)
    other.pop('targetSetPrescriptions')
    draft['workouts'][0]['exercises'].append(other)
    second = copy.deepcopy(draft['workouts'][0])
    second['name'] = 'Day B'
    second['exercises'] = [copy.deepcopy(source)]
    draft['workouts'].append(second)
    task = {
        'requirementsId': stored['requirementsId'],
        'baseDraftId': 'REVISION_0',
        'currentDraft': draft,
        'requirements': {'requiredCoverage': []},
        'recipeDefinitions': {
            'LIBRARY_0': {'exerciseType': 'BODY_WEIGHT'},
            'LIBRARY_1': {'exerciseType': 'BODY_WEIGHT'},
            'LIBRARY_2': {'exerciseType': 'BODY_WEIGHT'},
        },
        'replacementDefinitionReferences': ['LIBRARY_1'],
        'findingsAssessment': {'groups': [{
            'disposition': 'repair',
            'findingIndexes': [0],
            'repairDimensions': ['exercise_selection', 'prescription'],
            'repairObjectives': [{
                'kind': 'redistribute_work',
                'exerciseRefs': ['EXERCISE_0', 'EXERCISE_2'],
                'minimumSessions': 2,
            }],
        }]},
    }
    return draft, task


def test_mixed_menu_and_redistribution_compile_with_disjoint_ownership():
    draft, task = mixed_task()
    domain = repair_exercise_domain(task, draft)
    tool = coordinated_repair_tool(task)
    schema = tool['function']['parameters']

    assert uses_menu_selection(task)
    assert domain['all'] == ['EXERCISE_0', 'EXERCISE_1', 'EXERCISE_2']
    assert domain['protected'] == ['EXERCISE_0', 'EXERCISE_2']
    assert domain['editable'] == ['EXERCISE_1']
    assert schema['properties']['sessionBlocks']['minItems'] == 2
    assert schema['properties']['sessionBlocks']['items']['properties']['sessionReference']['enum'] == ['WORKOUT_0', 'WORKOUT_1']
    member_options = schema['properties']['sessionBlocks']['items']['properties']['blocks']['items']['properties']['exercises']['items']['oneOf']
    menu_references = set(member_options[0]['enum']) | {
        choice['properties']['replaces']['const'] for choice in member_options if choice['type'] == 'object'}
    assert menu_references == set(domain['editable'])
    assert 'EXERCISE_0' not in str(member_options)
    assert 'EXERCISE_2' not in str(member_options)
    assert schema['properties']['edits']['required'] == ['redistributionTargets']

    arguments = {
        'requirementsId': task['requirementsId'],
        'baseDraftId': task['baseDraftId'],
        'addressedFindingIndexes': [0],
        'sessionBlocks': [{
            'sessionReference': 'WORKOUT_0',
            'blocks': [{'exercises': [{
                'replaces': 'EXERCISE_1',
                'definition_id': 'LIBRARY_1',
                'satisfiesCoverage': [],
            }]}],
        }, {
            'sessionReference': 'WORKOUT_1',
            'blocks': [{'exercises': ['EXERCISE_1']}],
        }],
        'edits': {'redistributionTargets': {'REDISTRIBUTION_0': ['WORKOUT_0', 'WORKOUT_1']}},
    }
    original = copy.deepcopy(draft)
    compiled, _ = compile_coordinated_repair(arguments, task, draft)
    repaired = apply_json_patch(draft, compiled['patch'])

    assert draft == original
    protected = [day['exercises'][0] for day in repaired['workouts']]
    assert [item['definition_id'] for item in protected] == ['LIBRARY_0', 'LIBRARY_0']
    assert [item['numWorkSets'] for item in protected] == [5, 5]
    assert [item['workSetIndex'] for item in protected[0]['targetSetPrescriptions']] == list(range(5))
    assert repaired['workouts'][0]['exercises'][1]['definition_id'] == 'LIBRARY_1'
    assert repaired['workouts'][0]['exercises'][1]['numWorkSets'] == 3


def test_compiler_rejects_manual_move_of_protected_redistribution_source():
    draft, task = mixed_task()
    arguments = {
        'requirementsId': task['requirementsId'],
        'baseDraftId': task['baseDraftId'],
        'edits': {'exerciseMoves': [{'exerciseRef': 'EXERCISE_0', 'workoutRef': 'WORKOUT_1'}]},
    }

    with pytest.raises(PlanningInputError) as error:
        compile_coordinated_repair(arguments, task, draft)

    assert error.value.code == 'redistribution_manual_conflict'


def test_incomplete_task_does_not_enable_menu_selection_for_missing_source_domain():
    _, task = mixed_task()
    task.pop('currentDraft')

    domain = repair_exercise_domain(task)

    assert domain['protected'] == ['EXERCISE_0', 'EXERCISE_2']
    assert domain['editable'] == []
    assert not uses_menu_selection(task)


def test_mixed_menu_ignores_protected_string_refs_and_compiles_their_code_owned_spread():
    draft, task = mixed_task()
    arguments = {
        'requirementsId': task['requirementsId'],
        'baseDraftId': task['baseDraftId'],
        'addressedFindingIndexes': [0],
        'sessionBlocks': [{
            'sessionReference': 'WORKOUT_0',
            'blocks': [{'exercises': ['EXERCISE_0', 'EXERCISE_2']}],
        }, {
            'sessionReference': 'WORKOUT_1',
            'blocks': [{'exercises': ['EXERCISE_2', 'EXERCISE_1', 'EXERCISE_0']}],
        }],
        'edits': {'redistributionTargets': {'REDISTRIBUTION_0': ['WORKOUT_0', 'WORKOUT_1']}},
    }
    original = copy.deepcopy(draft)
    objective = task['findingsAssessment']['groups'][0]['repairObjectives'][0]
    compiled, _, references = compile_coordinated_repair(arguments, task, draft,
        return_reference_map=True)
    repaired = apply_json_patch(draft, compiled['patch'])

    assert draft == original
    redistributed = [exercise for day in repaired['workouts'] for exercise in day['exercises']
                     if exercise['definition_id'] == 'LIBRARY_0']
    assert len(redistributed) == 2
    assert sum(exercise['numWorkSets'] for exercise in redistributed) == 10
    contract = build_repair_contract([objective], draft, task['requirements'],
        references['redistributionManifest'], requirements_id=task['requirementsId'])
    assert contract['redistributions'][0]['weeklyWorkSets'] == 10
    assert not repair_contract_errors(contract, repaired)
    assert not any(exercise['definition_id'] == 'LIBRARY_2' for exercise in repaired['workouts'][0]['exercises'])
    assert sum(exercise['definition_id'] == 'LIBRARY_2'
        for exercise in repaired['workouts'][1]['exercises']) == 1


def test_protected_menu_normalization_keeps_unknown_refs_and_missing_targets_strict():
    draft, task = mixed_task()
    arguments = {
        'requirementsId': task['requirementsId'],
        'baseDraftId': task['baseDraftId'],
        'addressedFindingIndexes': [0],
        'sessionBlocks': [
            {'sessionReference': 'WORKOUT_0', 'blocks': [{'exercises': ['EXERCISE_999']} ]},
            {'sessionReference': 'WORKOUT_1', 'blocks': []},
        ],
        'edits': {'redistributionTargets': {'REDISTRIBUTION_0': ['WORKOUT_0', 'WORKOUT_1']}},
    }
    with pytest.raises(ValidationError) as error:
        compile_coordinated_repair(arguments, task, draft)
    assert 'EXERCISE_999' in error.value.message

    for malformed in ({'exercises': []}, {'exercises': ['EXERCISE_0'], 'unexpected': True}):
        arguments['sessionBlocks'][0]['blocks'] = [malformed]
        with pytest.raises(ValidationError):
            compile_coordinated_repair(arguments, task, draft)

    arguments['sessionBlocks'][0]['blocks'] = [{'exercises': ['EXERCISE_0']}]
    arguments.pop('edits')
    with pytest.raises((PlanningInputError, ValidationError)):
        compile_coordinated_repair(arguments, task, draft)


def test_menu_selection_requires_each_session_once():
    draft, task = mixed_task()
    arguments = {
        'requirementsId': task['requirementsId'],
        'baseDraftId': task['baseDraftId'],
        'addressedFindingIndexes': [0],
        'sessionBlocks': [
            {'sessionReference': 'WORKOUT_0', 'blocks': [{'exercises': ['EXERCISE_1']}]},
            {'sessionReference': 'WORKOUT_0', 'blocks': []},
        ],
        'edits': {'redistributionTargets': {'REDISTRIBUTION_0': ['WORKOUT_0', 'WORKOUT_1']}},
    }
    with pytest.raises(PlanningInputError, match='each session only once'):
        compile_coordinated_repair(arguments, task, draft)


def test_protected_replacement_reports_the_replacement_reference_error():
    draft, task = mixed_task()
    arguments = {
        'requirementsId': task['requirementsId'],
        'baseDraftId': task['baseDraftId'],
        'addressedFindingIndexes': [0],
        'sessionBlocks': [
            {'sessionReference': 'WORKOUT_0', 'blocks': [{'exercises': [{
                'replaces': 'EXERCISE_0', 'definition_id': 'LIBRARY_1', 'satisfiesCoverage': [],
            }]}]},
            {'sessionReference': 'WORKOUT_1', 'blocks': []},
        ],
        'edits': {'redistributionTargets': {'REDISTRIBUTION_0': ['WORKOUT_0', 'WORKOUT_1']}},
    }

    with pytest.raises(ValidationError) as error:
        compile_coordinated_repair(arguments, task, draft)

    assert list(error.value.absolute_path)[-1] == 'replaces'


def test_mixed_redistribution_detaches_its_source_and_preserves_menu_regrouping():
    draft, task = mixed_task()
    protected_source, unprotected_partner = draft['workouts'][0]['exercises']
    protected_source.update(superset=0, restBetweenSetsSeconds=0, restAfterSupersetExerciseSeconds=90)
    unprotected_partner.update(superset=0, restBetweenSetsSeconds=0, restAfterSupersetExerciseSeconds=90)
    extra = copy.deepcopy(unprotected_partner)
    extra.update(numWorkSets=2, superset=None, restBetweenSetsSeconds=90,
                 restAfterSupersetExerciseSeconds=0)
    draft['workouts'][1]['exercises'].append(extra)
    # The added movement has its own source identity and remains menu-selectable.
    task['findingsAssessment']['groups'][0]['repairObjectives'][0]['exerciseRefs'] = ['EXERCISE_0', 'EXERCISE_2']
    arguments = {
        'requirementsId': task['requirementsId'],
        'baseDraftId': task['baseDraftId'],
        'addressedFindingIndexes': [0],
        'sessionBlocks': [{
            'sessionReference': 'WORKOUT_0',
            'blocks': [{'exercises': ['EXERCISE_1', 'EXERCISE_3']}],
        }, {
            'sessionReference': 'WORKOUT_1',
            'blocks': [{'exercises': ['EXERCISE_3']}],
        }],
        'edits': {'redistributionTargets': {'REDISTRIBUTION_0': ['WORKOUT_0', 'WORKOUT_1']}},
    }

    compiled, _ = compile_coordinated_repair(arguments, task, draft)
    repaired = apply_json_patch(draft, compiled['patch'])

    redistributed = [exercise for day in repaired['workouts'] for exercise in day['exercises']
                     if exercise['definition_id'] == 'LIBRARY_0']
    assert len(redistributed) == 2
    assert sum(exercise['numWorkSets'] for exercise in redistributed) == 10
    assert {exercise.get('superset') for exercise in redistributed} == {None}

    first_day = repaired['workouts'][0]['exercises']
    regrouped = [exercise for exercise in first_day if exercise['definition_id'] == 'LIBRARY_2']
    assert len(regrouped) == 2
    assert regrouped[0]['superset'] is not None
    assert regrouped[0]['superset'] == regrouped[1]['superset']
    assert all(exercise['restBetweenSetsSeconds'] == 0 for exercise in regrouped)
    assert all(exercise['restAfterSupersetExerciseSeconds'] > 0 for exercise in regrouped)
