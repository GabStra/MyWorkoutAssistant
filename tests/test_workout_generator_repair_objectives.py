import copy
import json

import pytest

from workout_generator_pkg import review_assessment as assessment


def objective_review():
    objective = {'kind': 'redistribute_work', 'exerciseRefs': ['EXERCISE_0'], 'minimumSessions': 2}
    review = {'inputHash': 'reviewed-candidate', 'findings': [
        {'severity': 'blocking', 'action': 'repair', 'message': 'Distribute the existing pressing work.',
         'path': '/draft/libraryDefinitions/LIBRARY_0',
         'evidencePaths': ['/draft/libraryDefinitions/LIBRARY_0']}]}
    review['assessment'] = {'version': assessment.VERSION, 'inputHash': assessment.assessment_hash(review),
        'groups': [{'findingIndexes': [0], 'disposition': 'repair', 'repairDimensions': ['prescription'],
            'reason': 'Preserve work while distributing it.', 'repairObjectives': [
                {'kind': 'redistribute_work', 'exerciseRefs': ['EXERCISE_0'], 'minimumSessions': 2}]}],
        'repairPlan': 'Distribute the existing work without removing its source role.'}
    context = {'draft': {'exercises': [{'id': 'EXERCISE_0', 'libraryDefinitionId': 'LIBRARY_0'}],
            'libraryDefinitions': {'LIBRARY_0': {}}, 'workouts': [{}, {}]},
        'redistributionObjectiveChoices': [objective]}
    return review, context


def test_executable_repair_objective_is_bound_to_reviewed_candidate():
    review, context = objective_review()
    assert assessment.validate_assessment(review, context)['groups'][0]['repairObjectives']


def test_fresh_assessment_requests_and_retains_executable_outcome(monkeypatch):
    review, context = objective_review()
    group = copy.deepcopy(review.pop('assessment')['groups'][0])
    group.update(errorKind='none', authorityEvidenceRefs=[], currentDataEvidenceRefs=[])
    group.pop('repairObjectives')
    group['repairObjectiveChoiceIds'] = ['OBJECTIVE_0']

    def respond(_client, request, **options):
        schema = options['output_schema']['properties']['groups']['items']
        assert 'repairObjectives' not in schema['required']
        assert 'repairObjectiveChoiceIds' in schema['required']
        assert 'exerciseRefs' not in str(schema['properties']['repairObjectiveChoiceIds'])
        assert 'minimumSessions' not in str(schema['properties']['repairObjectiveChoiceIds'])
        assert 'supportedRedistributionObjectiveChoices' in json.loads(request[-1]['content'])['context']
        assert 'Do not return exerciseRefs or minimumSessions yourself.' in request[0]['content']
        return json.dumps({'groups': [group], 'repairPlan': 'Distribute the existing work.'}), None, None

    monkeypatch.setattr(assessment, '_review_call', respond)
    result = assessment.assess_findings(None, context, review)
    assert result['groups'][0]['repairObjectives'] == [{'kind': 'redistribute_work',
        'exerciseRefs': ['EXERCISE_0'], 'minimumSessions': 2}]


def test_repair_objective_choice_ids_expand_exact_catalog_values_and_reject_bad_ids():
    choices = [{'kind': 'redistribute_work', 'exerciseRefs': ['EXERCISE_0', 'EXERCISE_2'],
        'minimumSessions': 2}]
    schema = assessment.provider_repair_objective_selection_schema(choices)
    assert schema['items']['enum'] == ['OBJECTIVE_0']
    assert 'exerciseRefs' not in str(schema) and 'minimumSessions' not in str(schema)
    assert assessment.expand_repair_objective_choice_ids(['OBJECTIVE_0'], choices) == choices
    with pytest.raises(ValueError, match='Unknown repair objective choice IDs'):
        assessment.expand_repair_objective_choice_ids(['OBJECTIVE_1'], choices)
    with pytest.raises(ValueError, match='unique'):
        assessment.expand_repair_objective_choice_ids(['OBJECTIVE_0', 'OBJECTIVE_0'], choices)
    assert assessment.provider_repair_objective_selection_schema([]) == {
        'type': 'array', 'items': {'type': 'string'}, 'enum': [[]]}


def test_single_attempt_redistribution_composes_with_menu_and_protected_superset_partner(monkeypatch):
    from test_workout_generator_planning_tools import planning_case
    from workout_generator_pkg.json_patching import apply_json_patch
    from workout_generator_pkg.planning_tools import (coordinated_repair_tool, compile_coordinated_repair,
        uses_menu_selection)

    _, _, stored, draft = planning_case()
    source = draft['workouts'][0]['exercises'][0]
    source.pop('placementNotes', None)
    source.update(numWorkSets=4, superset='PAIR_A', targetSetPrescriptions=[
        {'workSetIndex': index, 'reps': 8 + index, 'weight': 20.0} for index in range(4)])
    partner = copy.deepcopy(source)
    partner.update(definition_id='LIBRARY_1', minReps=10, maxReps=12, numWorkSets=3,
                   superset='PAIR_A')
    partner.pop('targetSetPrescriptions')
    draft['workouts'][0]['exercises'] = [source, partner]
    second = copy.deepcopy(draft['workouts'][0])
    second['name'] = 'Day B'
    second['exercises'] = [copy.deepcopy(source), copy.deepcopy(partner)]
    second['exercises'][0]['superset'] = 'PAIR_B'
    second['exercises'][1]['superset'] = 'PAIR_B'
    draft['workouts'].append(second)
    third = copy.deepcopy(draft['workouts'][0])
    third['name'] = 'Day C'
    third['exercises'] = [copy.deepcopy(partner)]
    third['exercises'][0]['superset'] = None
    draft['workouts'].append(third)
    review = {'inputHash': 'retained-review', 'findings': [{
        'severity': 'blocking', 'action': 'repair', 'message': 'Distribute the current recipe across sessions.',
        'path': '/draft/libraryDefinitions/LIBRARY_0',
        'evidencePaths': ['/draft/libraryDefinitions/LIBRARY_0']}]}
    context = {'draft': {'exercises': [
        {'id': 'EXERCISE_0', 'libraryDefinitionId': 'LIBRARY_0'},
        {'id': 'EXERCISE_1', 'libraryDefinitionId': 'LIBRARY_1'},
        {'id': 'EXERCISE_2', 'libraryDefinitionId': 'LIBRARY_0'},
        {'id': 'EXERCISE_3', 'libraryDefinitionId': 'LIBRARY_1'}],
        'libraryDefinitions': {'LIBRARY_0': {}, 'LIBRARY_1': {}},
        'workouts': draft['workouts']}, 'requirements': {}, 'sourceMessages': {},
        'recipeDefinitions': {'LIBRARY_0': {'exerciseType': 'BODY_WEIGHT'},
            'LIBRARY_1': {'exerciseType': 'BODY_WEIGHT'}}}
    from workout_generator_pkg.repair_contract import redistribution_objective_choices
    context['redistributionObjectiveChoices'] = redistribution_objective_choices(
        draft, context['requirements'], context['recipeDefinitions'])
    objective = {'kind': 'redistribute_work', 'exerciseRefs': ['EXERCISE_0', 'EXERCISE_2'], 'minimumSessions': 3}

    def respond(_client, _request, **options):
        wire = options['output_schema']['properties']['findingAssessments']['properties']['FINDING_0']
        repair_variant = next(item for item in wire['anyOf']
            if item['properties']['disposition']['enum'] == ['repair'])
        assert 'repairObjectiveChoiceIds' in repair_variant['required']
        assert 'repairObjectives' not in repair_variant['properties']
        return json.dumps({'findingAssessments': {'FINDING_0': {
            'disposition': 'repair', 'repairDimensions': ['prescription', 'ordering', 'exercise_selection'],
            'repairObjectiveChoiceIds': ['OBJECTIVE_0'],
            'reason': 'Spread the existing recipe without changing weekly dose.'}},
            'repairPlan': 'Choose a non-redistributed menu and destination sessions; preserve the complete prescription.'}), None, None

    monkeypatch.setattr(assessment, '_review_call', respond)
    checked = assessment.assess_findings(None, context, review, single_attempt=True)
    assert checked['groups'][0]['findingIndexes'] == [0]
    assert checked['groups'][0]['repairObjectives'] == [objective]
    task = {'requirementsId': stored['requirementsId'], 'baseDraftId': 'REVISION_0', 'currentDraft': draft,
        'findingsAssessment': checked, 'requirements': {}, 'recipeDefinitions': {
            'LIBRARY_0': {'exerciseType': 'BODY_WEIGHT'}, 'LIBRARY_1': {'exerciseType': 'BODY_WEIGHT'}}}
    assert uses_menu_selection(task)
    tool = coordinated_repair_tool(task)
    schema = tool['function']['parameters']
    assert 'sessionBlocks' in schema['properties']
    assert schema['properties']['edits']['required'] == ['redistributionTargets']
    member_schema = schema['properties']['sessionBlocks']['items']['properties']['blocks']['items']['properties']['exercises']['items']
    assert 'EXERCISE_0' not in str(member_schema) and 'EXERCISE_2' not in str(member_schema)
    edits_schema = tool['function']['parameters']['properties']['edits']
    assert 'exerciseRedistributions' not in edits_schema['properties']
    target_schema = edits_schema['properties']['redistributionTargets']['properties']['REDISTRIBUTION_0']
    assert target_schema['minItems'] == objective['minimumSessions']
    assert target_schema['items']['enum'] == ['WORKOUT_0', 'WORKOUT_1', 'WORKOUT_2']

    arguments = {'requirementsId': stored['requirementsId'], 'baseDraftId': 'REVISION_0',
        'addressedFindingIndexes': [0],
        'sessionBlocks': [
            {'sessionReference': 'WORKOUT_0', 'blocks': [{'exercises': ['EXERCISE_1']}]},
            {'sessionReference': 'WORKOUT_1', 'blocks': [{'exercises': ['EXERCISE_3']}]},
            {'sessionReference': 'WORKOUT_2', 'blocks': [{'exercises': ['EXERCISE_4']}]}],
        'edits': {'redistributionTargets': {'REDISTRIBUTION_0': ['WORKOUT_0', 'WORKOUT_1', 'WORKOUT_2']}}}
    before_total = sum(exercise['numWorkSets'] for day in draft['workouts'] for exercise in day['exercises'])
    compiled, _ = compile_coordinated_repair(arguments, task, draft)
    repaired = apply_json_patch(draft, compiled['patch'])
    assert sum(exercise['numWorkSets'] for day in repaired['workouts'] for exercise in day['exercises']) == before_total
    assert [len(day['exercises']) for day in repaired['workouts']] == [2, 2, 2]
    redistributed = [item for day in repaired['workouts'] for item in day['exercises']
        if item['definition_id'] == 'LIBRARY_0']
    assert len(redistributed) == 3
    assert sum(item['numWorkSets'] for item in redistributed) == 8
    assert all(item['superset'] is None and item['restBetweenSetsSeconds'] == 90
        for day in repaired['workouts'] for item in day['exercises']
        if item['definition_id'] == 'LIBRARY_1')


def test_explicit_structural_candidate_qualifies_without_repair_assessment(monkeypatch):
    from test_workout_generator_planning_tools import planning_case, requirement_messages
    from workout_generator_pkg import allocation, exercise_library_tools, recipe_contracts
    from workout_generator_pkg.planning_tools import audit_workout_plan, set_workout_requirements
    from workout_generator_pkg.review_assessment import latest_assessment

    equipment, requirements, _, source_draft = planning_case()
    requirements['sessionsPerWeek'] = 2
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 5, 'maximum': 20}
    requirements['auditTargets']['perSessionEffectiveSets'] = {}
    stored = set_workout_requirements(requirements,
        [{'role': 'user', 'content': 'Two sessions; maintain weekly chest work.'}], equipment)
    source_draft['requirementsId'] = stored['requirementsId']
    source_draft['workouts'][0]['exercises'][0].pop('placementNotes', None)
    source_draft['workouts'][0]['exercises'].append(copy.deepcopy(source_draft['workouts'][0]['exercises'][0]))
    second_day = copy.deepcopy(source_draft['workouts'][0])
    second_day['name'] = 'Day B'
    source_draft['workouts'].append(second_day)
    messages = requirement_messages(stored)
    source = audit_workout_plan(source_draft, equipment, messages)
    source['review'] = {'findings': [{'severity': 'advisory', 'message': 'Consider distributing this movement.'}]}
    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': 'source-audit', 'function': {'name': 'audit_workout_plan'}}]},
        {'role': 'tool', 'tool_call_id': 'source-audit', 'content': json.dumps(source)},
    ])
    moved = copy.deepcopy(source_draft)
    moved_item = moved['workouts'][0]['exercises'].pop()
    moved['workouts'][1]['exercises'].append(moved_item)

    monkeypatch.setattr(exercise_library_tools, 'get_exercise_candidates',
        lambda arguments, *_a, **_k: {'exercises': [{'id': reference} for reference in arguments['definition_ids']]})
    monkeypatch.setattr(recipe_contracts, 'qualify_recipe_contracts',
        lambda _client, prepared, *_a, **_k: {'contracts': [
            {'definition_id': reference, 'satisfiesCoverage': []} for reference in prepared['definition_ids']]})

    result, qualification = allocation.qualify_coordinated_candidate(None, moved, equipment, messages)

    assert latest_assessment(messages, source) is None
    assert len(moved['workouts'][0]['exercises']) == 1 and len(moved['workouts'][1]['exercises']) == 3
    assert result['workouts'] == moved['workouts']
    assert qualification['contracts'][0]['definition_id'] == 'LIBRARY_0'


@pytest.mark.parametrize('change', ['unknown_exercise', 'unavailable_session', 'wrong_owner', 'below_minimum'])
def test_executable_objective_rejects_unbound_or_unauthorized_outcomes(change):
    review, context = objective_review()
    group = review['assessment']['groups'][0]
    if change == 'unknown_exercise':
        group['repairObjectives'][0]['exerciseRefs'] = ['EXERCISE_999']
    elif change == 'unavailable_session':
        group['repairObjectives'][0]['minimumSessions'] = 3
    elif change == 'below_minimum':
        group['repairObjectives'][0]['minimumSessions'] = 1
    else:
        group['repairDimensions'] = ['guidance']
    with pytest.raises(ValueError):
        assessment.validate_assessment(review, context)


def test_legacy_semantic_group_does_not_claim_an_executable_outcome():
    review, context = objective_review()
    group = review['assessment']['groups'][0]
    group.pop('repairObjectives')
    assert assessment.validate_assessment(copy.deepcopy(review), context)['groups'][0].get('repairObjectives', []) == []


def test_typed_redistribution_compiles_code_computed_split_without_mutating_source():
    from test_workout_generator_planning_tools import planning_case
    from workout_generator_pkg.json_patching import apply_json_patch
    from workout_generator_pkg.planning_tools import compile_coordinated_repair

    _, _, _, draft = planning_case()
    for workout in draft['workouts']:
        for exercise in workout['exercises']:
            exercise.pop('placementNotes', None)
    target = copy.deepcopy(draft['workouts'][0])
    target['name'] = 'Day B'
    target['exercises'] = []
    draft['workouts'].append(target)
    before = copy.deepcopy(draft)
    task = {'requirementsId': draft['requirementsId'], 'baseDraftId': 'REVISION_0', 'currentDraft': draft}
    declaration = {'exerciseRefs': ['EXERCISE_0'], 'workoutRefs': ['WORKOUT_0', 'WORKOUT_1']}
    proposal_context = {}
    compiled, _, references = compile_coordinated_repair({
        'requirementsId': draft['requirementsId'], 'baseDraftId': 'REVISION_0',
        'edits': {'exerciseRedistributions': [declaration]}}, task, draft,
        return_reference_map=True, proposal_context=proposal_context)
    after = apply_json_patch(draft, compiled['patch'])
    assert [day['exercises'][0]['numWorkSets'] for day in after['workouts']] == [3, 2]
    assert draft == before
    assert proposal_context['submittedEdits']['exerciseRedistributions'] == [declaration]
    assert references['redistributionManifest'][0]['weeklyWorkSets'] == 5


def test_generic_objective_reuse_cannot_drop_a_prior_redistribution_contract():
    from test_workout_generator_planning_tools import planning_case
    from workout_generator_pkg.allocation import reusable_joint_receipt
    from workout_generator_pkg.joint_planning import SELECTION_POLICY_VERSION, joint_objective_input_fingerprint
    from workout_generator_pkg.planning_tools import library_fingerprint

    equipment, requirements, stored, draft = planning_case()
    receipt = {'feasible': True, 'status': 'optimal', 'selectionPolicyVersion': SELECTION_POLICY_VERSION,
        'preserveSourceSelection': True, 'objectivePolicy': 'preserve_candidate_only',
        'approvedObjectiveOrder': None, 'objectiveInputFingerprint': joint_objective_input_fingerprint(
            draft['workouts'], requirements, equipment, preserve_source_selection=True),
        'redistributionOptimization': {'optimal': True}}
    owner = {'requirementsId': stored['requirementsId'], 'libraryFingerprint': library_fingerprint(equipment),
        'historyFingerprint': None, 'coordinatedJointPlanning': receipt}
    assert reusable_joint_receipt(owner, stored['requirementsId'], draft['workouts'], requirements,
        equipment, [], preserve_source_selection=True) is None
    constraints = [{'weeklyWorkSets': 5, 'workoutIndexes': [0]}]
    receipt['objectiveInputFingerprint'] = joint_objective_input_fingerprint(
        draft['workouts'], requirements, equipment, preserve_source_selection=True,
        redistribution_constraints=constraints)
    assert reusable_joint_receipt(owner, stored['requirementsId'], draft['workouts'], requirements,
        equipment, [], preserve_source_selection=True, redistribution_constraints=constraints) is not None
    assert reusable_joint_receipt(owner, stored['requirementsId'], draft['workouts'], requirements,
        equipment, [], preserve_source_selection=True,
        redistribution_constraints=[{'weeklyWorkSets': 6, 'workoutIndexes': [0]}]) is None
    receipt['objectiveInputFingerprint'] = joint_objective_input_fingerprint(
        draft['workouts'], requirements, equipment, preserve_source_selection=True)
    receipt.pop('redistributionOptimization')
    assert reusable_joint_receipt(owner, stored['requirementsId'], draft['workouts'], requirements,
        equipment, [], preserve_source_selection=True) is not None


@pytest.mark.parametrize('qualified', [False, True])
@pytest.mark.parametrize('contract_source', ['admission', 'requirements_record'])
def test_normal_repair_passes_contract_through_solver_and_keeps_it_after_failed_review(monkeypatch, qualified, contract_source):
    from test_workout_generator_planning_tools import planning_case, requirement_messages
    from workout_generator_pkg import allocation, interactive_shell, joint_planning, planning_tools

    equipment, requirements, _, draft = planning_case()
    requirements['sessionsPerWeek'] = 2
    requirements['auditTargets']['perSessionEffectiveSets'] = {}
    stored = planning_tools.set_workout_requirements(requirements,
        [{'role': 'user', 'content': 'Two weekly sessions with 5-6 chest sets total.'}], equipment)
    draft['requirementsId'] = stored['requirementsId']
    second = copy.deepcopy(draft['workouts'][0])
    second['name'] = 'Day B'
    second['exercises'][0]['numWorkSets'] = 1
    draft['workouts'].append(second)
    messages = requirement_messages(stored)
    source = planning_tools.audit_workout_plan(draft, equipment, messages)
    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': 'source', 'function': {'name': 'audit_workout_plan'}}]},
        {'role': 'tool', 'tool_call_id': 'source', 'content': json.dumps(source)}])
    task = {'requirementsId': stored['requirementsId'], 'baseDraftId': source['currentDraftId'], 'currentDraft': draft,
        'findingsAssessment': {'groups': [{'findingIndexes': [0], 'disposition': 'repair',
            'repairDimensions': ['prescription', 'ordering'], 'repairObjectives': [{'kind': 'redistribute_work',
                'exerciseRefs': ['EXERCISE_0', 'EXERCISE_1'], 'minimumSessions': 2}]}]}}
    admitted, context = interactive_shell._admit_repair_scope({
        'requirementsId': stored['requirementsId'], 'baseDraftId': source['currentDraftId'],
        'addressedFindingIndexes': [0],
        'edits': {'redistributionTargets': {'REDISTRIBUTION_0': ['WORKOUT_0', 'WORKOUT_1']}}}, task, draft, messages, 0, 3,
        equipment=equipment, return_context=True)
    if contract_source == 'requirements_record':
        from workout_generator_pkg.json_patching import apply_json_patch
        record_message = next(message for message in messages if message.get('tool_call_id') == 'requirements')
        record = json.loads(record_message['content'])
        record.update(repairContract=copy.deepcopy(context['repairContract']),
            workouts=apply_json_patch(draft, admitted['patch'])['workouts'],
            libraryFingerprint=planning_tools.library_fingerprint(equipment), historyFingerprint=None)
        record_message['content'] = json.dumps(record)
    monkeypatch.setattr(allocation, 'qualify_coordinated_candidate',
        lambda _client, args, *_a, **_k: (args, {'inputHash': 'qualified', 'contracts': []} if qualified else None))
    monkeypatch.setattr(interactive_shell, 'auto_allocate_workout',
        lambda *_a, **_k: pytest.fail('An unconstrained allocator must not handle a redistribution.'))
    calls = []
    original_solve = joint_planning.solve_prescribed_week

    def solve(*args, **kwargs):
        calls.append(kwargs.get('redistribution_constraints'))
        return original_solve(*args, **kwargs)

    monkeypatch.setattr(joint_planning, 'solve_prescribed_week', solve)
    monkeypatch.setattr(interactive_shell, 'review_draft', lambda _client, result, *_a, **_k: {
        **result, 'passed': False, 'review': {'findings': [{'severity': 'blocking', 'message': 'Correct guidance.'}]},
        'errors': [{'code': 'independent_review_finding'}]})
    result = json.loads(interactive_shell.handle_function_call(None, messages, 'audit_workout_plan',
        admitted, equipment, coordinated_repair=context if contract_source == 'admission' else False)['result'])
    assert calls and calls[0][0]['weeklyWorkSets'] == 6
    assert [day['exercises'][0]['numWorkSets'] for day in result['submittedDraft']['workouts']] == [3, 3]
    assert result['repairContract']['redistributions'][0]['weeklyWorkSets'] == 6
    assert result['coordinatedJointPlanning']['redistributionOptimization']['optimal']
    assert not result['passed'] and 'planIndex' not in result
    assert planning_tools.latest_draft_submission(messages, equipment)[1] == source['currentDraftId']
    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': 'repaired', 'function': {'name': 'audit_workout_plan'}}]},
        {'role': 'tool', 'tool_call_id': 'repaired', 'content': json.dumps(result)}])
    resumed = json.loads(interactive_shell.handle_function_call(None, messages, 'audit_workout_plan',
        result['submittedDraft'], equipment, coordinated_repair=True)['result'])
    assert len(calls) == 2 and calls[-1][0]['weeklyWorkSets'] == 6
    assert resumed['repairContract']['redistributions'][0]['weeklyWorkSets'] == 6
    assert not resumed['passed'] and 'planIndex' not in resumed
