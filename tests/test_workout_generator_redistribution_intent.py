import copy

import pytest
from jsonschema import Draft7Validator, ValidationError

from workout_generator_pkg.json_patching import apply_json_patch
from workout_generator_pkg.planning_tools import (PlanningInputError, compile_coordinated_repair,
    coordinated_repair_tool)
from workout_generator_pkg.repair_contract import RepairContractError, build_repair_contract


def intent_case():
    from test_workout_generator_planning_tools import planning_case
    _, _, _, draft = planning_case()
    draft['workouts'][0]['exercises'][0].pop('placementNotes', None)
    second = copy.deepcopy(draft['workouts'][0])
    second['name'] = 'Day B'
    second['exercises'][0]['numWorkSets'] = 1
    draft['workouts'].append(second)
    objective = {'kind': 'redistribute_work', 'exerciseRefs': ['EXERCISE_0', 'EXERCISE_1'], 'minimumSessions': 2}
    task = {'requirementsId': draft['requirementsId'], 'baseDraftId': 'REVISION_0', 'currentDraft': draft,
        'findingsAssessment': {'inputHash': 'reviewed-source', 'groups': [
            {'findingIndexes': [0], 'disposition': 'repair', 'repairDimensions': ['prescription', 'ordering'],
                'repairObjectives': [objective]}]}}
    arguments = {'requirementsId': task['requirementsId'], 'baseDraftId': task['baseDraftId'],
        'addressedFindingIndexes': [0], 'edits': {'redistributionTargets': {
            'REDISTRIBUTION_0': ['WORKOUT_0', 'WORKOUT_1']}}}
    return draft, task, arguments, objective


def test_assessed_tool_requires_only_destinations_and_codegen_conserves_prescriptions():
    from workout_generator_pkg.user_interaction import repair_workout_alternative_tool
    draft, task, arguments, objective = intent_case()
    before = copy.deepcopy(draft)
    tool = coordinated_repair_tool(task)
    edits = tool['function']['parameters']['properties']['edits']
    assert edits['required'] == ['redistributionTargets']
    assert 'exerciseRedistributions' not in edits['properties']
    assert all(key not in edits['properties'] for key in ('exerciseMoves', 'exerciseRemovals'))
    assert 'numWorkSets' not in edits['properties']['exerciseUpdates']['items']['properties']['setFields']['properties']
    group = edits['properties']['redistributionTargets']['properties']['REDISTRIBUTION_0']
    assert group['minItems'] == 2 and group['uniqueItems']
    assert group['items']['enum'] == ['WORKOUT_0', 'WORKOUT_1']
    assert 'EXERCISE_0, EXERCISE_1' in group['description']
    assert 'For a redistribute_work objective, use exerciseRedistributions' not in tool['function']['description']
    alternative = repair_workout_alternative_tool({**task,
        'repairCandidateId': 'ALT', 'originalRequirementsId': task['requirementsId']})
    assert alternative['function']['parameters']['properties']['edits'] == edits
    context = {}
    compiled, _, refs = compile_coordinated_repair(arguments, task, draft,
        return_reference_map=True, proposal_context=context)
    result = apply_json_patch(draft, compiled['patch'])
    assert [day['exercises'][0]['numWorkSets'] for day in result['workouts']] == [3, 3]
    for source, target in zip(draft['workouts'], result['workouts']):
        preserved = copy.deepcopy(target['exercises'][0])
        preserved['numWorkSets'] = source['exercises'][0]['numWorkSets']
        assert preserved == source['exercises'][0]
    assert context['submittedEdits'] == arguments['edits']
    assert draft == before
    contract = build_repair_contract([objective], draft, {'sessionsPerWeek': 2}, refs['redistributionManifest'])
    assert contract['redistributions'][0]['weeklyWorkSets'] == 6


def test_assessed_tool_stops_before_model_when_source_minimum_makes_spread_impossible():
    draft, task, _, objective = intent_case()
    source = draft['workouts'][0]['exercises'][0]
    source.pop('targetSetPrescriptions', None)
    source.update(numWorkSets=2, allocationBounds={'minimum': 2, 'maximum': 20})
    draft['workouts'][1]['exercises'] = []
    objective['exerciseRefs'] = ['EXERCISE_0']
    task['currentDraft'] = draft

    with pytest.raises(RepairContractError) as error:
        coordinated_repair_tool(task)

    assert error.value.code == 'redistribution_no_feasible_destinations'


@pytest.mark.parametrize('bypass', ['missing_intent', 'raw_redistribution', 'move', 'remove', 'order', 'clone', 'generated_order'])
def test_manual_bookkeeping_cannot_bypass_assessed_intent(bypass):
    draft, task, arguments, _ = intent_case()
    edits = arguments['edits']
    if bypass == 'missing_intent':
        edits.pop('redistributionTargets')
        edits['programGuidance'] = 'A guidance change cannot satisfy redistribution.'
    elif bypass == 'raw_redistribution':
        edits['exerciseRedistributions'] = [{'exerciseRefs': ['EXERCISE_0', 'EXERCISE_1'],
            'workoutRefs': ['WORKOUT_0', 'WORKOUT_1']}]
    elif bypass == 'update':
        edits['exerciseUpdates'] = [{'exerciseRef': 'EXERCISE_0', 'setFields': {'numWorkSets': 3}}]
    elif bypass == 'move':
        edits['exerciseMoves'] = [{'exerciseRef': 'EXERCISE_0', 'workoutRef': 'WORKOUT_1'}]
    elif bypass == 'remove':
        edits['exerciseRemovals'] = ['EXERCISE_0']
    elif bypass == 'order':
        edits['exerciseOrders'] = [{'workoutRef': 'WORKOUT_1', 'exerciseRefs': ['EXERCISE_0']}]
    elif bypass == 'clone':
        edits['exerciseAdditions'] = [{'temporaryId': 'NEW_EXERCISE_MANUAL', 'workoutRef': 'WORKOUT_1',
            'exercise': copy.deepcopy(draft['workouts'][0]['exercises'][0])}]
    else:
        edits['exerciseOrders'] = [{'workoutRef': 'WORKOUT_1', 'exerciseRefs': ['NEW_EXERCISE_REDIST_0_1']}]
    before = copy.deepcopy(draft)
    with pytest.raises((ValidationError, PlanningInputError)):
        compile_coordinated_repair(arguments, task, draft)
    assert draft == before


def test_retry_compiles_intent_against_unchanged_baseline_and_keeps_rejected_manual_proposal_separate():
    draft, task, arguments, _ = intent_case()
    rejected = {'exerciseMoves': [{'exerciseRef': 'EXERCISE_0', 'workoutRef': 'WORKOUT_1'}],
        'programGuidance': 'Keep all other required corrections.'}
    task['rejectedCoordinatedRepair'] = {'requirementsId': task['requirementsId'],
        'baseDraftId': task['baseDraftId'], 'submittedEdits': rejected,
        'assessmentInputHash': task['findingsAssessment']['inputHash']}
    arguments['edits']['programGuidance'] = rejected['programGuidance']
    context = {}
    compiled, _ = compile_coordinated_repair(arguments, task, draft, proposal_context=context)
    after = apply_json_patch(draft, compiled['patch'])
    assert [day['exercises'][0]['numWorkSets'] for day in after['workouts']] == [3, 3]
    assert after['programGuidance'] == rejected['programGuidance']
    assert context['replacedSubmittedEdits'] == rejected
    assert context['submittedEdits'] == arguments['edits']
    assert [day['exercises'][0]['numWorkSets'] for day in draft['workouts']] == [5, 1]


def test_missing_group_or_insufficient_destinations_fail_the_model_input_schema():
    draft, task, arguments, objective = intent_case()
    draft['workouts'][1]['exercises'][0].update(minReps=6, numWorkSets=2)
    second = copy.deepcopy(objective)
    second['exerciseRefs'] = ['EXERCISE_1']
    task['findingsAssessment']['groups'][0]['repairObjectives'].append(second)
    schema = coordinated_repair_tool(task)['function']['parameters']
    assert 'editableFields' not in coordinated_repair_tool(task)['function']['description']
    assert list(Draft7Validator(schema).iter_errors(arguments))
    arguments['edits']['redistributionTargets']['REDISTRIBUTION_1'] = ['WORKOUT_0']
    assert list(Draft7Validator(schema).iter_errors(arguments))


def test_destination_input_order_does_not_control_code_owned_splits():
    draft, task, arguments, _ = intent_case()
    draft['workouts'][1]['exercises'][0]['numWorkSets'] = 2
    forward, _ = compile_coordinated_repair(arguments, task, draft)
    arguments['edits']['redistributionTargets']['REDISTRIBUTION_0'].reverse()
    reversed_targets, _ = compile_coordinated_repair(arguments, task, draft)
    assert reversed_targets['patch'] == forward['patch']


def test_rejected_destination_intent_is_amended_without_reintroducing_manual_operation_fields():
    draft, task, arguments, _ = intent_case()
    previous = copy.deepcopy(arguments['edits'])
    previous['programGuidance'] = 'Saved proposal guidance.'
    task['rejectedCoordinatedRepair'] = {'requirementsId': task['requirementsId'],
        'baseDraftId': task['baseDraftId'], 'assessmentInputHash': task['findingsAssessment']['inputHash'],
        'submittedEdits': previous}
    arguments['edits']['programGuidance'] = 'Corrected proposal guidance.'
    context = {}
    compiled, _ = compile_coordinated_repair(arguments, task, draft, proposal_context=context)
    result = apply_json_patch(draft, compiled['patch'])
    assert [day['exercises'][0]['numWorkSets'] for day in result['workouts']] == [3, 3]
    assert context['submittedEdits'] == arguments['edits']
    assert 'exerciseRedistributions' not in context['submittedEdits']
    assert result['programGuidance'] == arguments['edits']['programGuidance']

def test_mixed_assessed_sources_compile_as_separate_conserved_recipe_groups():
    draft, task, arguments, objective = intent_case()
    draft['workouts'][1]['exercises'][0].update(minReps=6, numWorkSets=3)
    properties = coordinated_repair_tool(task)['function']['parameters']['properties']['edits']['properties']
    choices = properties['redistributionTargets']['properties']
    assert set(choices) == {'REDISTRIBUTION_0', 'REDISTRIBUTION_1'}
    arguments['edits']['redistributionTargets']['REDISTRIBUTION_1'] = ['WORKOUT_0', 'WORKOUT_1']
    compiled, _, refs = compile_coordinated_repair(arguments, task, draft, return_reference_map=True)
    after = apply_json_patch(draft, compiled['patch'])
    assert sorted(group['weeklyWorkSets'] for group in refs['redistributionManifest']) == [3, 5]
    assert {reps: sum(e['numWorkSets'] for day in after['workouts'] for e in day['exercises']
                     if e['minReps'] == reps) for reps in (6, 8)} == {6: 3, 8: 5}
    contract = build_repair_contract([objective], draft, {'sessionsPerWeek': 2}, refs['redistributionManifest'])
    assert len(contract['redistributions']) == 2

def test_superset_restructuring_and_redistribution_preserve_dose_atomically():
    draft, task, arguments, objective = intent_case()
    first = draft['workouts'][0]['exercises'][0]
    first.update(superset='PAIR', restBetweenSetsSeconds=0, restAfterSupersetExerciseSeconds=90)
    partner = copy.deepcopy(first)
    partner.update(definition_id='LIBRARY_1', minReps=6)
    draft['workouts'][0]['exercises'].append(partner)
    objective['exerciseRefs'] = ['EXERCISE_0', 'EXERCISE_2']
    before = copy.deepcopy(draft)
    compiled, _, refs = compile_coordinated_repair(arguments, task, draft, return_reference_map=True)
    after = apply_json_patch(draft, compiled['patch'])
    assert draft == before
    assert all(e['superset'] is None for day in after['workouts'] for e in day['exercises'])
    assert sum(e['numWorkSets'] for day in after['workouts'] for e in day['exercises']
               if e['definition_id'] == 'LIBRARY_0') == 6
    assert sum(e['numWorkSets'] for day in after['workouts'] for e in day['exercises']
               if e['definition_id'] == 'LIBRARY_1') == 5
    from workout_generator_pkg.repair_contract import repair_contract_errors
    contract = build_repair_contract([objective], draft, {'sessionsPerWeek': 2}, refs['redistributionManifest'])
    assert not repair_contract_errors(contract, after)
    # Rest is checked by the executable audit; it is not the conserved training dose.
    after['workouts'][0]['exercises'][0]['restBetweenSetsSeconds'] = 150
    assert not repair_contract_errors(contract, after)
    after['workouts'][0]['exercises'][0]['numWorkSets'] -= 1
    assert any(error['code'] == 'redistribution_weekly_sets_changed'
               for error in repair_contract_errors(contract, after))

def test_progression_correction_follows_every_redistributed_occurrence_and_clone():
    draft, task, arguments, objective = intent_case()
    task['findingsAssessment']['groups'][0]['repairDimensions'].append('progression')
    third = copy.deepcopy(draft['workouts'][0]); third['exercises'] = []; third['name'] = 'Day C'
    draft['workouts'].append(third)
    arguments['edits']['redistributionTargets']['REDISTRIBUTION_0'].append('WORKOUT_2')
    policy = {'kind': 'reps', 'nextDefinitionId': None, 'nextDefinitionName': None,
              'atCeilingAction': 're_audit_higher_reps'}
    arguments['edits']['exerciseUpdates'] = [{'exerciseRef': 'EXERCISE_0', 'setFields': {'progressionPlan': policy, 'superset': None,
        'restBetweenSetsSeconds': 140, 'restAfterSupersetExerciseSeconds': 0}}]
    original = copy.deepcopy(draft)
    compiled, _, refs = compile_coordinated_repair(arguments, task, draft, return_reference_map=True)
    after = apply_json_patch(draft, compiled['patch'])
    assert draft == original
    assert [e['numWorkSets'] for day in after['workouts'] for e in day['exercises']] == [2, 2, 2]
    assert all(e['progressionPlan'] == policy and e['restBetweenSetsSeconds'] == 140
               for day in after['workouts'] for e in day['exercises'])
    from workout_generator_pkg.repair_contract import repair_contract_errors
    contract = build_repair_contract([objective], draft, {'sessionsPerWeek': 3}, refs['redistributionManifest'])
    assert not repair_contract_errors(contract, after)
    arguments['edits']['exerciseUpdates'].append({'exerciseRef': 'EXERCISE_1',
        'setFields': {'progressionPlan': {**policy, 'kind': 'load'}}})
    with pytest.raises(PlanningInputError) as rejected:
        compile_coordinated_repair(arguments, task, draft)
    assert rejected.value.code == 'redistribution_manual_conflict'


def test_reviewed_redistribution_rejects_non_authoritative_count_edits():
    draft, task, arguments, _ = intent_case()
    arguments['edits']['exerciseUpdates'] = [
        {'exerciseRef': 'EXERCISE_0', 'setFields': {'numWorkSets': 20}},
        {'exerciseRef': 'EXERCISE_1', 'setFields': {'numWorkSets': 1}}]
    before = copy.deepcopy(draft)
    with pytest.raises(ValidationError, match='numWorkSets'):
        compile_coordinated_repair(arguments, task, draft)
    assert draft == before
    arguments['edits'].pop('exerciseUpdates')
    compiled, _ = compile_coordinated_repair(arguments, task, draft)
    result = apply_json_patch(draft, compiled['patch'])
    assert [day['exercises'][0]['numWorkSets'] for day in result['workouts']] == [3, 3]


def test_reviewed_repair_selects_enumerated_redistribution_without_executable_objectives():
    draft, task, arguments, _ = intent_case()
    task['findingsAssessment']['groups'][0].pop('repairObjectives')
    arguments['edits'] = {'exerciseRedistributions': [
        {'exerciseRefs': ['EXERCISE_0', 'EXERCISE_1'], 'workoutRefs': ['WORKOUT_0', 'WORKOUT_1']}]}
    before = copy.deepcopy(draft)
    schema = coordinated_repair_tool(task)['function']['parameters']
    assert schema['properties']['edits']['properties']['exerciseRedistributions']['items']['enum'] == arguments['edits']['exerciseRedistributions']
    compiled, _ = compile_coordinated_repair(arguments, task, draft)
    result = apply_json_patch(draft, compiled['patch'])
    assert [day['exercises'][0]['numWorkSets'] for day in result['workouts']] == [3, 3]
    assert draft == before
    arguments['edits']['exerciseRedistributions'][0]['exerciseRefs'] = ['EXERCISE_0']
    with pytest.raises(ValidationError):
        compile_coordinated_repair(arguments, task, draft)


def test_selected_redistribution_allows_ordering_retained_occurrences_only():
    draft, task, arguments, _ = intent_case()
    task['findingsAssessment']['groups'][0].pop('repairObjectives')
    arguments['edits'] = {'exerciseRedistributions': [
        {'exerciseRefs': ['EXERCISE_0', 'EXERCISE_1'], 'workoutRefs': ['WORKOUT_0', 'WORKOUT_1']}],
        'exerciseOrders': [{'workoutRef': 'WORKOUT_0', 'exerciseRefs': ['EXERCISE_0']},
                           {'workoutRef': 'WORKOUT_1', 'exerciseRefs': ['EXERCISE_1']}]}
    compiled, _ = compile_coordinated_repair(arguments, task, draft)
    result = apply_json_patch(draft, compiled['patch'])
    assert [day['exercises'][0]['numWorkSets'] for day in result['workouts']] == [3, 3]
    arguments['edits']['exerciseOrders'][1]['exerciseRefs'] = ['EXERCISE_0']
    with pytest.raises(PlanningInputError) as error:
        compile_coordinated_repair(arguments, task, draft)
    assert error.value.code == 'redistribution_order_reference_conflict'


def test_redistribution_destinations_are_capped_by_source_sets():
    draft, task, arguments, _ = intent_case()
    for day in draft['workouts']:
        day['exercises'][0]['numWorkSets'] = 1
    third = copy.deepcopy(draft['workouts'][0])
    third['exercises'] = []
    draft['workouts'].append(third)
    schema = coordinated_repair_tool(task)['function']['parameters']
    Draft7Validator(schema).validate(arguments)
    arguments['edits']['redistributionTargets']['REDISTRIBUTION_0'].append('WORKOUT_2')
    with pytest.raises(ValidationError):
        Draft7Validator(schema).validate(arguments)
