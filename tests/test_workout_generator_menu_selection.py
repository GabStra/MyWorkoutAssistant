import copy
import json

import pytest
from jsonschema import ValidationError, validate

from workout_generator_pkg.planning_tools import (
    PlanningInputError, audit_workout_plan, compile_coordinated_repair, coordinated_repair_tool,
    set_workout_requirements, validate_repair_scope,
)
from workout_generator_pkg.json_patching import apply_json_patch
from workout_generator_pkg.interactive_shell import _admit_repair_scope, _retrieved_replacement_definition_references
from test_workout_generator_planning_tools import planning_case, requirement_messages


def menu_case():
    _, _, stored, draft = planning_case()
    source = draft['workouts'][0]['exercises'][0]
    source.pop('placementNotes', None)
    source['workSetTemplate'] = {'reps': 8, 'additionalWeight': 0}
    other = copy.deepcopy(source)
    other.update(definition_id='LIBRARY_1', minReps=10, maxReps=15, numWorkSets=3,
                 restBetweenSetsSeconds=120)
    other.pop('workSetTemplate')
    draft['workouts'][0]['exercises'].append(other)
    task = {'requirementsId': stored['requirementsId'], 'baseDraftId': 'REVISION_0',
            'currentDraft': draft, 'candidateMenuExpansionTask': {'sourceProblemFingerprint': 'source'}}
    return draft, task


def arguments(task, edits):
    return {'requirementsId': task['requirementsId'], 'baseDraftId': task['baseDraftId'], 'edits': edits}


def test_atomic_update_then_removal_preserves_survivor_identity():
    draft, task = menu_case()
    task.pop('candidateMenuExpansionTask')
    original = copy.deepcopy(draft)
    compiled, _ = compile_coordinated_repair(arguments(task, {
        'exerciseUpdates': [
            {'exerciseRef': 'EXERCISE_0', 'setFields': {'restBetweenSetsSeconds': 90}},
            {'exerciseRef': 'EXERCISE_1', 'setFields': {'restBetweenSetsSeconds': 90}},
        ], 'exerciseRemovals': ['EXERCISE_0']}), task, draft)
    final = apply_json_patch(draft, compiled['patch'])['workouts'][0]['exercises']
    assert len(final) == 1 and final[0]['definition_id'] == original['workouts'][0]['exercises'][1]['definition_id']
    assert final[0]['restBetweenSetsSeconds'] == 90
    assert draft == original
    with pytest.raises((PlanningInputError, ValidationError)):
        compile_coordinated_repair(arguments(task, {'exerciseRemovals': ['EXERCISE_0', 'EXERCISE_0']}), task, draft)


def test_definition_substitution_drops_inherited_load_but_keeps_explicit_replacement():
    equipment, requirements, _, draft = planning_case()
    equipment_id = 'EQUIPMENT_0'
    equipment['equipments'] = [{'id': equipment_id, 'name': 'Barbell', 'type': 'BARBELL',
                                'barWeight': 20.0, 'availablePlates': []}]
    equipment['exerciseDefinitions'] = [
        {'id': 'bench', 'name': 'Barbell Bench Press', 'exerciseType': 'WEIGHT', 'equipmentId': equipment_id,
         'bodyWeightPercentage': None, 'requiredAccessoryEquipmentIds': [], 'muscleGroups': ['FRONT_CHEST'],
         'secondaryMuscleGroups': [], 'exerciseCategory': 'MODERATE_COMPOUND'},
        {'id': 'row', 'name': 'Barbell Row', 'exerciseType': 'WEIGHT', 'equipmentId': equipment_id,
         'bodyWeightPercentage': None, 'requiredAccessoryEquipmentIds': [], 'muscleGroups': ['BACK_LATS'],
         'secondaryMuscleGroups': [], 'exerciseCategory': 'MODERATE_COMPOUND'},
    ]
    requirements['auditTargets'].update(weeklyEffectiveSets={}, perSessionEffectiveSets={}, maximumSessionSeconds=2000)
    stored = set_workout_requirements(requirements, [{'role': 'user', 'content': 'Create a general strength plan.'}], equipment)
    draft['requirementsId'] = stored['requirementsId']
    source = draft['workouts'][0]['exercises'][0]
    source.update(definition_id='LIBRARY_0', targetSetPrescriptions=[
        {'workSetIndex': index, 'reps': 10, 'weight': 20.0} for index in range(source['numWorkSets'])])
    source.pop('workSetTemplate', None)
    task = {'requirementsId': stored['requirementsId'], 'baseDraftId': 'REVISION_0', 'currentDraft': draft}
    update = {'exerciseUpdates': [{'exerciseRef': 'EXERCISE_0', 'setFields': {'definition_id': 'LIBRARY_1'}}]}

    compiled, _ = compile_coordinated_repair(arguments(task, update), task, draft)
    replaced = apply_json_patch(draft, compiled['patch'])
    replaced_exercise = replaced['workouts'][0]['exercises'][0]
    assert replaced_exercise['definition_id'] == 'LIBRARY_1'
    assert replaced_exercise['numWorkSets'] == source['numWorkSets']
    assert replaced_exercise['restBetweenSetsSeconds'] == source['restBetweenSetsSeconds']
    assert replaced_exercise['targetSetPrescriptions'] == [
        {'workSetIndex': index, 'reps': 10} for index in range(source['numWorkSets'])]
    assert audit_workout_plan(draft, equipment, requirement_messages(stored))['passed']
    assert audit_workout_plan(replaced, equipment, requirement_messages(stored))['passed']

    explicit_targets = [{'workSetIndex': index, 'reps': 10, 'weight': 20.0}
                        for index in range(source['numWorkSets'])]
    explicit_update = {'exerciseUpdates': [{'exerciseRef': 'EXERCISE_0', 'setFields': {
        'definition_id': 'LIBRARY_1', 'targetSetPrescriptions': explicit_targets}}]}
    explicit, _ = compile_coordinated_repair(arguments(task, explicit_update), task, draft)
    explicit_result = apply_json_patch(draft, explicit['patch'])
    assert explicit_result['workouts'][0]['exercises'][0]['targetSetPrescriptions'] == explicit_targets


@pytest.mark.parametrize('ordered', [['EXERCISE_1', 'EXERCISE_0'], ['EXERCISE_0']])
def test_atomic_order_projects_away_explicitly_removed_occurrences(ordered):
    draft, task = menu_case()
    task.pop('candidateMenuExpansionTask')
    compiled, _ = compile_coordinated_repair(arguments(task, {
        'exerciseRemovals': ['EXERCISE_0'],
        'exerciseOrders': [{'workoutRef': 'WORKOUT_0', 'exerciseRefs': ordered}],
    }), task, draft)
    final = apply_json_patch(draft, compiled['patch'])['workouts'][0]['exercises']
    assert final == [draft['workouts'][0]['exercises'][1]]
    with pytest.raises((PlanningInputError, ValidationError)):
        compile_coordinated_repair(arguments(task, {
            'exerciseRemovals': ['EXERCISE_0'],
            'exerciseOrders': [{'workoutRef': 'WORKOUT_0', 'exerciseRefs': ['EXERCISE_999']}],
        }), task, draft)


@pytest.mark.parametrize('fields', [{'numWorkSets': 2}, {'restBetweenSetsSeconds': 60},
                                  {'definition_id': 'LIBRARY_1', 'minReps': 20}])
def test_menu_stage_excludes_model_prescriptions_but_general_repair_keeps_them(fields):
    draft, task = menu_case()
    submission = arguments(task, {'exerciseUpdates': [{'exerciseRef': 'EXERCISE_0', 'setFields': fields}]})
    with pytest.raises(ValidationError):
        compile_coordinated_repair(submission, task, draft)
    generic = {key: value for key, value in task.items() if key != 'candidateMenuExpansionTask'}
    validate(submission, coordinated_repair_tool(generic)['function']['parameters'])


def selection(task, references):
    request = {'requirementsId': task['requirementsId'], 'baseDraftId': task['baseDraftId'],
               'sessionBlocks': [{'sessionReference': 'WORKOUT_0',
                                  'blocks': [{'exercises': [reference]} for reference in references]}]}
    assessment = task.get('findingsAssessment')
    if isinstance(assessment, dict):
        request['addressedFindingIndexes'] = sorted({index for group in assessment.get('groups', [])
            if group.get('disposition') == 'repair' for index in group.get('findingIndexes', [])})
    return request


def test_assessed_menu_repair_owns_choices_not_prescriptions():
    draft, task = menu_case()
    task.pop('candidateMenuExpansionTask')
    task['findingsAssessment'] = {'groups': [
        {'findingIndexes': [0], 'disposition': 'repair',
         'repairDimensions': ['ordering', 'prescription'], 'repairObjectives': []},
        {'findingIndexes': [1], 'disposition': 'repair',
         'repairDimensions': ['exercise_selection', 'coverage'], 'repairObjectives': []}]}
    schema = coordinated_repair_tool(task)['function']['parameters']
    assert 'sessionBlocks' in schema['properties']
    assert 'edits' not in schema['properties']
    request = selection(task, ['EXERCISE_1', 'EXERCISE_0'])
    compiled, _ = compile_coordinated_repair(request, task, draft)
    final = apply_json_patch(draft, compiled['patch'])
    assert final['workouts'][0]['exercises'][0]['definition_id'] == 'LIBRARY_1'
    assert compiled['addressedFindingIndexes'] == [0, 1]
    with pytest.raises(ValidationError):
        compile_coordinated_repair(arguments(task, {'exerciseUpdates': [
            {'exerciseRef': 'EXERCISE_0', 'setFields': {'numWorkSets': 4}}]}), task, draft)


def test_menu_repair_can_correct_labels_without_reopening_prescription_edits():
    draft, task = menu_case()
    task.pop('candidateMenuExpansionTask')
    task['findingsAssessment'] = {'groups': [
        {'findingIndexes': [0], 'disposition': 'repair', 'repairDimensions': ['ordering']},
        {'findingIndexes': [1], 'disposition': 'repair', 'repairDimensions': ['session_labels']}]}
    request = selection(task, ['EXERCISE_1', 'EXERCISE_0'])
    request['workoutUpdates'] = [{'workoutRef': 'WORKOUT_0', 'setFields': {'description': 'Push and pull'}}]
    schema = coordinated_repair_tool(task)['function']['parameters']
    assert 'sessionBlocks' in schema['properties'] and 'edits' not in schema['properties']
    compiled, _ = compile_coordinated_repair(request, task, draft)
    final = apply_json_patch(draft, compiled['patch'])
    assert final['workouts'][0]['description'] == 'Push and pull'
    assert final['workouts'][0]['exercises'][0]['definition_id'] == 'LIBRARY_1'
    request['workoutUpdates'][0]['setFields']['timesCompletedInAWeek'] = 2
    with pytest.raises(ValidationError):
        compile_coordinated_repair(request, task, draft)


@pytest.mark.parametrize('dimensions,objectives', [
    (['prescription'], []), (['session_labels'], []),
    (['exercise_selection'], [{'kind': 'redistribute_work', 'exerciseRefs': ['EXERCISE_0'],
                              'minimumSessions': 1}])])
def test_non_menu_repairs_keep_their_existing_typed_surface(dimensions, objectives):
    draft, task = menu_case()
    task.pop('candidateMenuExpansionTask')
    task['findingsAssessment'] = {'groups': [{'findingIndexes': [0], 'disposition': 'repair',
        'repairDimensions': dimensions, 'repairObjectives': objectives}]}
    assert 'sessionBlocks' not in coordinated_repair_tool(task)['function']['parameters']['properties']


def test_menu_replacement_copies_known_recipe_without_transferring_old_targets():
    draft, task = menu_case()
    original = copy.deepcopy(draft)
    compiled, _ = compile_coordinated_repair(selection(task, ['EXERCISE_1']), task, draft)
    candidate = apply_json_patch(draft, compiled['patch'])
    assert candidate['workouts'][0]['exercises'] == [draft['workouts'][0]['exercises'][1]]
    assert draft == original


def test_complete_menu_selection_supersedes_pending_edits_without_changing_session_metadata():
    draft, task = menu_case()
    task['rejectedCoordinatedRepair'] = {'status': 'rejected_before_materialization',
        'requirementsId': task['requirementsId'], 'baseDraftId': task['baseDraftId'],
        'currentDraftId': task['baseDraftId'], 'assessmentInputHash': None,
        'submittedEdits': {'workoutUpdates': [{'workoutRef': 'WORKOUT_0', 'setFields': {'name': 'Pending'}}]}}
    ownership = {}
    compiled, _ = compile_coordinated_repair(selection(task, ['EXERCISE_1']), task, draft, proposal_context=ownership)
    candidate = apply_json_patch(draft, compiled['patch'])
    assert candidate['workouts'][0]['name'] == draft['workouts'][0]['name']
    assert ownership['replacedSubmittedEdits'] == task['rejectedCoordinatedRepair']['submittedEdits']
    assert candidate['workouts'][0]['exercises'] == [draft['workouts'][0]['exercises'][1]]


def test_menu_noop_rejected_before_any_candidate_is_applied():
    draft, task = menu_case()
    with pytest.raises(PlanningInputError) as rejected:
        compile_coordinated_repair(selection(task, ['EXERCISE_0', 'EXERCISE_1']), task, draft)
    assert rejected.value.code == 'empty_coordinated_edits'


def test_menu_selection_retains_identity_and_clones_only_additional_occurrences():
    draft, task = menu_case()
    draft['workouts'].append({**copy.deepcopy(draft['workouts'][0]), 'name': 'Day B', 'exercises': []})
    request = {'requirementsId': task['requirementsId'], 'baseDraftId': task['baseDraftId'],
        'sessionBlocks': [
            {'sessionReference': 'WORKOUT_0', 'blocks': [{'exercises': ['EXERCISE_0']}]},
            {'sessionReference': 'WORKOUT_1', 'blocks': [
                {'exercises': ['EXERCISE_0']}, {'exercises': ['EXERCISE_1']}]}]}
    compiled, _, references = compile_coordinated_repair(request, task, draft, return_reference_map=True)
    edits = references['composedEdits']
    assert not edits.get('exerciseRemovals')
    assert len(edits['exerciseAdditions']) == 1
    assert edits['exerciseMoves'] == [{'exerciseRef': 'EXERCISE_1', 'workoutRef': 'WORKOUT_1'}]
    final = apply_json_patch(draft, compiled['patch'])
    assert [e['definition_id'] for e in final['workouts'][0]['exercises']] == ['LIBRARY_0']
    assert [e['definition_id'] for e in final['workouts'][1]['exercises']] == ['LIBRARY_0', 'LIBRARY_1']


def test_menu_replacement_is_bound_to_retrieved_recipe_and_drops_inherited_targets():
    draft, task = menu_case()
    source = draft['workouts'][0]['exercises'][0]
    source['targetSetPrescriptions'] = [{'workSetIndex': index, 'reps': 8, 'additionalWeight': 0}
                                       for index in range(source['numWorkSets'])]
    task.update(replacementDefinitionReferences=['LIBRARY_1'], requirements={'requiredCoverage': []},
        recipeDefinitions={'LIBRARY_0': {'exerciseType': 'BODY_WEIGHT', 'exerciseCategory': 'MODERATE_COMPOUND'},
                           'LIBRARY_1': {'exerciseType': 'WEIGHT', 'exerciseCategory': 'MODERATE_COMPOUND'}})
    request = selection(task, [{'replaces': 'EXERCISE_0', 'definition_id': 'LIBRARY_1', 'satisfiesCoverage': []}])
    schema = coordinated_repair_tool(task)['function']['parameters']
    validate(request, schema)

    compiled, _ = compile_coordinated_repair(request, task, draft)
    final = apply_json_patch(draft, compiled['patch'])['workouts'][0]['exercises']
    replacement = next(item for item in final if item['definition_id'] == 'LIBRARY_1')
    assert replacement['numWorkSets'] == source['numWorkSets']
    assert 'workSetTemplate' not in replacement
    assert 'targetSetPrescriptions' not in replacement

    for invalid in (
        {'replaces': 'EXERCISE_0', 'definition_id': 'LIBRARY_99', 'satisfiesCoverage': []},
        {'replaces': 'EXERCISE_0', 'definition_id': 'LIBRARY_1', 'satisfiesCoverage': ['invented']},
    ):
        with pytest.raises(ValidationError):
            validate(selection(task, [invalid]), schema)

    same_definition = selection(task, [
        {'replaces': 'EXERCISE_0', 'definition_id': 'LIBRARY_0', 'satisfiesCoverage': []},
        'EXERCISE_1'])
    validate(same_definition, schema)
    with pytest.raises(PlanningInputError, match='selection leaves the exercise menu unchanged'):
        compile_coordinated_repair(same_definition, task, draft)


def test_replacement_menu_includes_current_eligible_cached_candidates():
    state = {'exerciseCandidates': {
        'LIBRARY_2': {'id': 'LIBRARY_2'},
        'LIBRARY_3': {'id': 'LIBRARY_4'},
        'not-a-library-reference': {'id': 'not-a-library-reference'},
    }, 'cachedCandidateIndex': {
        'LIBRARY_82': {'name': 'Eligible indexed candidate'},
        'LIBRARY_178': {'name': 'Eligible indexed candidate'},
        'LIBRARY_295': {'name': 'Eligible indexed candidate'},
        'LIBRARY_239': {'name': 'Eligible indexed candidate'},
        'invalid': {'name': 'Malformed reference'},
        'LIBRARY_6': None,
    }}
    assert _retrieved_replacement_definition_references(state) == [
        'LIBRARY_178', 'LIBRARY_2', 'LIBRARY_239', 'LIBRARY_295', 'LIBRARY_82']

    draft, task = menu_case()
    task.update(replacementDefinitionReferences=_retrieved_replacement_definition_references(state),
        requirements={'requiredCoverage': []},
        recipeDefinitions={'LIBRARY_0': {'exerciseType': 'BODY_WEIGHT', 'exerciseCategory': 'MODERATE_COMPOUND'},
            'LIBRARY_1': {'exerciseType': 'BODY_WEIGHT', 'exerciseCategory': 'MODERATE_COMPOUND'},
            'LIBRARY_82': {'exerciseType': 'WEIGHT', 'exerciseCategory': 'MODERATE_COMPOUND'}})
    request = selection(task, [{'replaces': 'EXERCISE_0', 'definition_id': 'LIBRARY_82', 'satisfiesCoverage': []}])
    schema = coordinated_repair_tool(task)['function']['parameters']
    validate(request, schema)
    compiled, _ = compile_coordinated_repair(request, task, draft)
    selected = apply_json_patch(draft, compiled['patch'])['workouts'][0]['exercises']
    assert [item['definition_id'] for item in selected] == ['LIBRARY_82']
    assert 'workSetTemplate' not in selected[0]
    assert 'targetSetPrescriptions' not in selected[0]


def test_replacement_menu_limits_choices_to_prescription_compatible_types():
    draft, task = menu_case()
    task.update(replacementDefinitionReferences=['LIBRARY_1', 'LIBRARY_2'],
        replacementDefinitionTypes={'LIBRARY_0': 'WEIGHT', 'LIBRARY_1': 'BODY_WEIGHT',
                                    'LIBRARY_2': 'COUNTDOWN'},
        recipeDefinitions={'LIBRARY_0': {'exerciseType': 'WEIGHT'},
                           'LIBRARY_1': {'exerciseType': 'BODY_WEIGHT'},
                           'LIBRARY_2': {'exerciseType': 'COUNTDOWN'}})
    schema = coordinated_repair_tool(task)['function']['parameters']
    choices = schema['properties']['sessionBlocks']['items']['properties']['blocks']['items']['properties']['exercises']['items']['oneOf']
    replacement = next(choice for choice in choices if choice['type'] == 'object')
    assert replacement['properties']['definition_id']['enum'] == ['LIBRARY_1']

    timed_request = selection(task, [{'replaces': 'EXERCISE_0', 'definition_id': 'LIBRARY_2',
                                      'satisfiesCoverage': []}])
    with pytest.raises(ValidationError):
        compile_coordinated_repair(timed_request, task, draft)


def test_unilateral_replacements_get_code_owned_rest_before_plan_preflight():
    from workout_generator_pkg.planning_tools import build_draft_plan

    _, requirements, _, draft = planning_case()
    equipment_id = 'EQUIPMENT_0'
    equipment = {'equipments': [{'id': equipment_id, 'name': 'Dumbbell', 'type': 'DUMBBELL',
                                 'availablePlates': []}], 'accessoryEquipments': [],
        'exerciseDefinitions': [
            {'id': 'calf', 'name': 'Single-Leg Dumbbell Calf Raise', 'exerciseType': 'WEIGHT',
             'equipmentId': equipment_id, 'bodyWeightPercentage': None, 'requiredAccessoryEquipmentIds': [],
             'muscleGroups': ['BACK_CALVES'], 'secondaryMuscleGroups': [], 'exerciseCategory': 'ISOLATION'},
            {'id': 'nordic', 'name': 'Single-Leg Nordic Curl', 'exerciseType': 'BODY_WEIGHT',
             'equipmentId': None, 'bodyWeightPercentage': 80.0, 'requiredAccessoryEquipmentIds': [],
             'muscleGroups': ['BACK_HAMSTRING'], 'secondaryMuscleGroups': [], 'exerciseCategory': 'HEAVY_COMPOUND'},
            {'id': 'z-bilateral-calf', 'name': 'Dumbbell Calf Raise', 'exerciseType': 'WEIGHT',
             'equipmentId': equipment_id, 'bodyWeightPercentage': None, 'requiredAccessoryEquipmentIds': [],
             'muscleGroups': ['BACK_CALVES'], 'secondaryMuscleGroups': [], 'exerciseCategory': 'ISOLATION'},
        ]}
    first = draft['workouts'][0]['exercises'][0]
    first.update(definition_id='LIBRARY_0', numWorkSets=3, minReps=10, maxReps=15,
                 restBetweenSetsSeconds=90, generateWarmUpSets=False, setupSeconds=60)
    second = copy.deepcopy(first)
    second.update(definition_id='LIBRARY_1', numWorkSets=5, minReps=6, maxReps=8,
                  restBetweenSetsSeconds=120, setupSeconds=120)
    draft['workouts'][0]['exercises'] = [first, second]

    plan = build_draft_plan(draft, equipment, requirements)
    assert [exercise['intraSetRestInSeconds'] for exercise in plan['exercises']] == [30, 30]
    assert [(exercise['numWorkSets'], exercise['minReps'], exercise['maxReps'])
            for exercise in plan['exercises']] == [(3, 10, 15), (5, 6, 8)]
    assert [exercise['generateWarmUpSets'] for exercise in plan['exercises']] == [False, False]

    first['intraSetRestInSeconds'] = 45
    plan = build_draft_plan(draft, equipment, requirements)
    assert plan['exercises'][0]['intraSetRestInSeconds'] == 45

    first['definition_id'] = 'LIBRARY_2'
    plan = build_draft_plan(draft, equipment, requirements)
    assert plan['exercises'][0]['intraSetRestInSeconds'] is None


def test_selected_superset_uses_approved_rests_without_model_prescriptions():
    draft, task = menu_case()
    task['requirements'] = {'executionRules': [
        {'kind': 'rest', 'context': context, 'coverageKey': None, 'minimumSeconds': lower, 'maximumSeconds': upper}
        for context, lower, upper in [('supersetTransition', 15, 30), ('supersetRound', 90, 120)]]}
    request = selection(task, [])
    request['sessionBlocks'][0]['blocks'] = [{'exercises': ['EXERCISE_0', 'EXERCISE_1']}]
    compiled, _ = compile_coordinated_repair(request, task, draft)
    items = apply_json_patch(draft, compiled['patch'])['workouts'][0]['exercises']
    assert [item['restBetweenSetsSeconds'] for item in items] == [0, 0]
    assert [item['restAfterSupersetExerciseSeconds'] for item in items] == [15, 90]
    assert items[0]['superset'] == items[1]['superset']

def test_solver_menu_selection_copies_only_code_owned_candidate():
    draft, task = menu_case()
    original = copy.deepcopy(draft)
    solved = copy.deepcopy(draft['workouts'])
    solved[0]['exercises'] = [solved[0]['exercises'][1]]
    solved[0]['exercises'][0]['numWorkSets'] = 4
    task['solverMenu'] = {'feasible': True, 'sessions': solved}
    request = {'requirementsId': task['requirementsId'], 'baseDraftId': task['baseDraftId'], 'useSolverMenu': True}
    compiled, _ = compile_coordinated_repair(request, task, draft)
    assert apply_json_patch(draft, compiled['patch'])['workouts'] == solved
    assert draft == original
    with pytest.raises(ValidationError):
        compile_coordinated_repair({**request, 'sessionBlocks': []}, task, draft)
    with pytest.raises(ValidationError):
        compile_coordinated_repair({**request, 'useSolverMenu': False}, task, draft)


def test_feasible_solver_menu_does_not_remove_semantic_choice_without_a_blocker():
    draft, task = menu_case()
    task['solverMenu'] = {'feasible': True, 'sessions': copy.deepcopy(draft['workouts'])}
    schema = coordinated_repair_tool(task)['function']['parameters']
    request = {'requirementsId': task['requirementsId'], 'baseDraftId': task['baseDraftId'],
               'useSolverMenu': True}

    validate(request, schema)
    validate(selection(task, ['EXERCISE_0']), schema)
    compiled, _ = compile_coordinated_repair(selection(task, ['EXERCISE_0']), task, draft)
    assert len(apply_json_patch(draft, compiled['patch'])['workouts'][0]['exercises']) == 1
    with pytest.raises(ValidationError):
        validate({**selection(task, ['EXERCISE_0']), 'useSolverMenu': True}, schema)


@pytest.mark.parametrize('assessment,review_findings', [
    ({'groups': [{'findingIndexes': [0], 'disposition': 'repair',
                  'repairDimensions': ['exercise_selection']}]},
     [{'action': 'repair', 'draftPath': '/draft/workouts/0/exercises/0', 'message': 'Replace movement.'}]),
    (None, [{'action': 'repair'}]),
])
def test_actionable_review_repair_preserves_semantic_menu_choice(assessment, review_findings):
    draft, task = menu_case()
    task.update(solverMenu={'feasible': True, 'sessions': copy.deepcopy(draft['workouts'])},
                findingsAssessment=assessment, reviewFindings=review_findings)
    if assessment is None:
        task.pop('findingsAssessment')
    schema = coordinated_repair_tool(task)['function']['parameters']

    validate(selection(task, ['EXERCISE_1']), schema)
    solver_selection = {'requirementsId': task['requirementsId'], 'baseDraftId': task['baseDraftId'],
                        'useSolverMenu': True}
    if assessment is not None:
        solver_selection['addressedFindingIndexes'] = [0]
    validate(solver_selection, schema)
    assert 'sessionBlocks' in schema['properties']
    if assessment is not None:
        compiled, _ = compile_coordinated_repair(selection(task, ['EXERCISE_1']), task, draft)
        assert compiled['addressedFindingIndexes'] == [0]


def test_numerical_fallback_does_not_force_planner_to_abandon_selected_recipe():
    draft, task = menu_case()
    original = copy.deepcopy(draft)
    solved = copy.deepcopy(draft['workouts'])
    solved[0]['exercises'] = [solved[0]['exercises'][0]]
    task['solverMenu'] = {'feasible': True, 'sessions': solved}
    task['reviewFindings'] = [{'action': 'repair', 'message': 'Use the selected replacement exercise.'}]
    # The numerical proposal omits the replacement needed by the semantic repair.
    compiled, _ = compile_coordinated_repair(selection(task, ['EXERCISE_1']), task, draft)
    candidate = apply_json_patch(draft, compiled['patch'])
    assert candidate['workouts'][0]['exercises'] == [draft['workouts'][0]['exercises'][1]]
    assert draft == original
    assert task['solverMenu']['sessions'] == solved


def test_solver_menu_admission_uses_full_candidate_but_manual_edits_still_require_hidden_sessions():
    equipment, requirements, _, _ = planning_case()
    requirements['sessionsPerWeek'] = 3
    stored = set_workout_requirements(requirements, [{'role': 'user', 'content': 'Plan three sessions.'}])
    draft, task = menu_case()
    draft['requirementsId'] = stored['requirementsId']
    draft['workouts'].extend([copy.deepcopy(draft['workouts'][0]), copy.deepcopy(draft['workouts'][0])])
    for index, day in enumerate(draft['workouts']):
        day['name'] = f'Day {index + 1}'
    solved = copy.deepcopy(draft['workouts'])
    solved[0]['exercises'] = [copy.deepcopy(solved[0]['exercises'][1])]
    task.update(requirementsId=stored['requirementsId'], baseDraftId='REVISION_0', currentDraft=draft,
                candidateMenuExpansionTask={'sourceProblemFingerprint': 'source'},
                solverMenu={'feasible': True, 'sessions': solved},
                omittedWorkoutReferences=['WORKOUT_1', 'WORKOUT_2'])
    messages = [
        {'role': 'assistant', 'tool_calls': [{'id': 'requirements', 'function': {
            'name': 'set_workout_requirements', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'requirements', 'content': json.dumps({
            'requirementsId': stored['requirementsId'], 'requirements': stored['requirements']})},
    ]
    arguments = {'requirementsId': stored['requirementsId'], 'baseDraftId': 'REVISION_0', 'useSolverMenu': True}

    admitted = _admit_repair_scope(arguments, task, draft, messages, 0, 2, equipment)
    assert admitted['patch']
    candidate = apply_json_patch(draft, admitted['patch'])
    assert candidate['workouts'][1:] == solved[1:]
    with pytest.raises(PlanningInputError, match='Read omitted sessions') as error:
        validate_repair_scope({'requirementsId': stored['requirementsId'], 'baseDraftId': 'REVISION_0',
            'patch': [{'op': 'replace', 'path': '/workouts/1/name', 'value': 'Changed'}]},
            {'omittedWorkoutReferences': ['WORKOUT_1']}, draft)
    assert error.value.code == 'draft_details_required'


def _superset_repair_case(required_dimensions):
    current = {'workouts': [{'name': 'Session A', 'exercises': [
        {'definition_id': 'LIBRARY_A', 'superset': 'PAIR', 'restAfterSupersetExerciseSeconds': 20},
        {'definition_id': 'LIBRARY_B', 'superset': 'PAIR', 'restAfterSupersetExerciseSeconds': 90},
        {'definition_id': 'LIBRARY_C', 'superset': None, 'restAfterSupersetExerciseSeconds': 0},
    ]}]}
    task = {'requirementsId': 'REQ', 'baseDraftId': 'REVISION_1',
        'findingsAssessment': {'groups': [{'findingIndexes': [0], 'disposition': 'repair',
        'repairDimensions': required_dimensions}]},
        'reviewFindings': [{'draftPath': '/workouts/0/exercises/0/superset'}]}
    return current, task


def test_superset_group_rename_and_recovery_edits_do_not_count_as_membership_repair():
    current, task = _superset_repair_case(['superset'])
    request = {'requirementsId': 'REQ', 'baseDraftId': 'REVISION_1',
        'addressedFindingIndexes': [0], 'patch': [
        {'op': 'replace', 'path': '/workouts/0/exercises/0/superset', 'value': 'RENAMED'},
        {'op': 'replace', 'path': '/workouts/0/exercises/1/superset', 'value': 'RENAMED'},
        {'op': 'replace', 'path': '/workouts/0/exercises/0/restAfterSupersetExerciseSeconds', 'value': 30},
        {'op': 'replace', 'path': '/workouts/0/exercises/1/restAfterSupersetExerciseSeconds', 'value': 105},
    ]}

    with pytest.raises(PlanningInputError, match='matching structured field'):
        validate_repair_scope(request, task, current)


def test_superset_repair_credits_actual_membership_change_and_recovery_only_remains_timing():
    current, task = _superset_repair_case(['superset'])
    regroup = {'requirementsId': 'REQ', 'baseDraftId': 'REVISION_1',
        'addressedFindingIndexes': [0], 'patch': [
        {'op': 'replace', 'path': '/workouts/0/exercises/0/superset', 'value': None},
        {'op': 'replace', 'path': '/workouts/0/exercises/1/superset', 'value': None},
        {'op': 'replace', 'path': '/workouts/0/exercises/0/superset', 'value': 'NEW_PAIR'},
        {'op': 'replace', 'path': '/workouts/0/exercises/2/superset', 'value': 'NEW_PAIR'},
    ]}
    validate_repair_scope(regroup, task, current)

    timing_only_task = copy.deepcopy(task)
    timing_only_task['findingsAssessment']['groups'][0]['repairDimensions'] = ['session_timing']
    timing_only_task['reviewFindings'][0]['draftPath'] = (
        '/workouts/0/exercises/0/restAfterSupersetExerciseSeconds')
    timing_only = {'requirementsId': 'REQ', 'baseDraftId': 'REVISION_1',
        'addressedFindingIndexes': [0], 'patch': [
        {'op': 'replace', 'path': '/workouts/0/exercises/0/restAfterSupersetExerciseSeconds', 'value': 30},
    ]}
    validate_repair_scope(timing_only, timing_only_task, current)


def test_cross_session_move_counts_when_it_changes_cited_superset_membership():
    current = {'workouts': [
        {'name': 'Session A', 'exercises': [
            {'definition_id': 'LIBRARY_A', 'superset': 'PAIR'},
            {'definition_id': 'LIBRARY_B', 'superset': 'PAIR'},
        ]},
        {'name': 'Session B', 'exercises': [
            {'definition_id': 'LIBRARY_C', 'superset': None},
        ]},
    ]}
    task = {'requirementsId': 'REQ', 'baseDraftId': 'REVISION_1',
        'findingsAssessment': {'groups': [{'findingIndexes': [0], 'disposition': 'repair',
            'repairDimensions': ['superset']}]},
        'reviewFindings': [{'draftPath': '/workouts/0/exercises/0/superset'}]}
    request = {'requirementsId': 'REQ', 'baseDraftId': 'REVISION_1',
        'addressedFindingIndexes': [0], 'patch': [
            {'op': 'move', 'from': '/workouts/0/exercises/1', 'path': '/workouts/1/exercises/-'},
        ]}

    validate_repair_scope(request, task, current)


def _later_session_superset_repair_case():
    current = {'workouts': [
        {'name': f'Session {index}', 'exercises': [
            {'definition_id': 'LIBRARY_A', 'superset': f'PAIR_{index}'},
            {'definition_id': 'LIBRARY_B', 'superset': f'PAIR_{index}'},
        ]}
        for index in range(3)
    ]}
    task = {'requirementsId': 'REQ', 'baseDraftId': 'REVISION_1',
        'findingsAssessment': {'groups': [{'findingIndexes': [0], 'disposition': 'repair',
            'repairDimensions': ['superset']}]},
        'reviewFindings': [{'draftPath': '/workouts/1/exercises/0/superset'}]}
    request = {'requirementsId': 'REQ', 'baseDraftId': 'REVISION_1',
        'addressedFindingIndexes': [0], 'patch': [
            {'op': 'replace', 'path': '/workouts/1/exercises/0/superset', 'value': None},
            {'op': 'replace', 'path': '/workouts/1/exercises/1/superset', 'value': None},
        ]}
    return current, task, request


def test_later_session_superset_membership_change_is_credited():
    current, task, request = _later_session_superset_repair_case()
    validate_repair_scope(request, task, current)


def test_later_session_superset_group_rename_is_not_credited():
    current, task, request = _later_session_superset_repair_case()
    request['patch'] = [
        {'op': 'replace', 'path': '/workouts/1/exercises/0/superset', 'value': 'RENAMED'},
        {'op': 'replace', 'path': '/workouts/1/exercises/1/superset', 'value': 'RENAMED'},
    ]
    with pytest.raises(PlanningInputError, match='matching structured field'):
        validate_repair_scope(request, task, current)
