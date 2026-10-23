import copy
import json
import threading
from types import SimpleNamespace

import pytest

from workout_generator_pkg import session_drafting, plan_review, interactive_shell as shell
from workout_generator_pkg.planner_context import request_planning_state, pending_evidence
from workout_generator_pkg.planning_tools import audit_workout_plan, set_workout_requirements
from test_workout_generator_planning_tools import planning_case, requirement_messages
from test_workout_generator_plan_review import assessment_transport


@pytest.fixture(autouse=True)
def qualified_recipe_fixture(monkeypatch):
    # Recipe qualification has dedicated tests; these tests isolate drafting/repair behavior.
    monkeypatch.setattr('workout_generator_pkg.recipe_contracts.qualify_recipe_contracts',
        lambda *args, **kwargs: {'inputHash': 'qualified-fixture', 'contracts': [], 'capabilities': {}})


def store_tool(messages, name, arguments, result):
    key = 'call_' + str(len(messages))
    messages.extend([{'role': 'assistant', 'tool_calls': [{'id': key, 'function': {
        'name': name, 'arguments': json.dumps(arguments)}}]},
        {'role': 'tool', 'tool_call_id': key, 'content': json.dumps(result)}])


@pytest.fixture(autouse=True)
def reviewed_structure(monkeypatch):
    # The independent structure reviewer has focused contract tests in test_workout_generator_week_structure.
    monkeypatch.setattr(plan_review, 'review_week_structure', lambda *a, **k: {'passed': True, 'findings': []})


def structure(count=5, occurrences=1):
    return [{'definition_id': 'LIBRARY_0', 'numWorkSets': count, 'allocationBounds': {'minimum': 1, 'maximum': 6}, 'superset': None}
            for _ in range(occurrences)]


def week_case(execution_rules=None, occurrences=1, coverage=None):
    equipment, requirements, _, draft = planning_case()
    requirements['sessionsPerWeek'] = 3
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 15, 'maximum': 18}
    if coverage is not None:
        requirements['requiredCoverage'] = coverage
    if execution_rules is not None:
        requirements['executionRules'] = execution_rules
    stored = set_workout_requirements(requirements, [{'role': 'user', 'content': 'Three sessions, 15-18 chest sets weekly.'}], equipment)
    messages = requirement_messages(stored)
    sessions = [{**{key: value for key, value in draft['workouts'][0].items() if key != 'exercises'},
                 'name': f'Session {index}', 'trainingDays': [index * 2], 'exercises': structure(5 if occurrences == 1 else 2, occurrences)}
                for index in range(3)]
    arguments = {'requirementsId': stored['requirementsId'], 'baseDraftId': None,
                 'name': 'Program', 'sessions': sessions}
    if coverage:
        for day in arguments['sessions']:
            for item in day['exercises']:
                item['satisfiesCoverage'] = [rule['key'] for rule in coverage]
    prepared = session_drafting.prepare_workout_sessions(arguments, messages, equipment)
    store_tool(messages, 'prepare_workout_sessions', arguments, prepared)
    for exercise in draft['workouts'][0]['exercises']:
        exercise['allocationBounds'] = copy.deepcopy(prepared['sessions'][0]['exercises'][0]['allocationBounds'])
        exercise['progressionMethod'] = 'reps'
        exercise['repDurationSeconds'] = 3
    return equipment, messages, prepared, draft['workouts'][0]['exercises']


def test_forced_weekly_dose_returns_to_menu_choice_before_workers_and_resumes_started_work():
    from workout_generator_pkg.planner_context import construction_tool_failure
    equipment, messages, prepared, _ = week_case()
    state = request_planning_state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert state['constructionTask']['reviewAllocationBeforeDrafting']
    for name in ('draft_workout_sessions', 'prepare_workout_sessions', 'search_exercise_library'):
        assert construction_tool_failure(name, {}, state) is None
    assert construction_tool_failure('audit_workout_plan', {}, state)
    assert any(item.get('scope') == 'weekly'
               for item in state['parallelPreparation']['setAllocation']['allocationDiagnostics'])
    store_tool(messages, 'draft_workout_sessions', {'preparationId': prepared['preparationId']}, {
        'preparationId': prepared['preparationId'], 'passed': False, 'executionFailure': True,
        'workerResults': {}, 'workerFailures': {}})
    resumed = request_planning_state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert not resumed['constructionTask']['reviewAllocationBeforeDrafting']
    assert construction_tool_failure('prepare_workout_sessions', {}, resumed)


def test_menu_reconsideration_is_compact_and_a_second_preparation_goes_to_workers():
    from workout_generator_pkg.planner_context import _focus_session_preparation, planner_response_profile
    equipment, messages, prepared, _ = week_case()
    state = request_planning_state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    evidence = {'LIBRARY_0': {'name': 'Press', 'status': 'comparable_records', 'totalSessions': 1,
                             'sessions': [{'largeDetail': 'Detailed worker-only history'}]}}
    _focus_session_preparation(state, {}, evidence, False)
    assert state['constructionTask']['reviewAllocationBeforeDrafting']
    assert planner_response_profile(state)['reasoning_effort'] is None
    assert state['trainingEvidence'] == {}
    assert state['trainingEvidenceSummary']['LIBRARY_0']['totalSessions'] == 1
    assert 'Detailed worker-only history' not in json.dumps(state)
    store_tool(messages, 'prepare_workout_sessions', {}, prepared)
    revised = request_planning_state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert revised['constructionTask']['stage'] == 'draft_sessions'
    assert not revised['constructionTask']['reviewAllocationBeforeDrafting']


def test_joint_week_is_solved_before_any_semantic_review(monkeypatch):
    equipment, messages, prepared, exercises = week_case()
    state = request_planning_state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    monkeypatch.setattr(plan_review, 'review_week_structure', lambda *a, **k: pytest.fail('Review must see complete prescriptions'))
    def draft(client, request, **options):
        return json.dumps({'exercises': copy.deepcopy(exercises)}), None, None
    monkeypatch.setattr(session_drafting, 'chat_call', draft)
    result = session_drafting.draft_workout_sessions(None, {'preparationId': prepared['preparationId']}, messages, equipment, state)
    assert result['jointPlanning']['feasible']
    assert result['jointPlanning']['preserveSourceSelection'] is False
    assert 'proposedSubmission' in result


def test_final_menu_selection_keeps_required_coverage_and_fixed_dose(monkeypatch):
    from workout_generator_pkg import joint_planning

    equipment, requirements, _, draft = planning_case()
    optional = copy.deepcopy(equipment['exerciseDefinitions'][0])
    optional.update(id='zz_optional_push', name='Optional Push-Up Variant')
    equipment['exerciseDefinitions'].append(optional)
    requirements.update(sessionsPerWeek=2, objectiveOrder=['progression'])
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 10, 'maximum': 12}
    requirements['requiredCoverage'] = [{'key': 'push', 'description': 'Pressing movement', 'scope': 'eachSession'}]
    stored = set_workout_requirements(requirements,
        [{'role': 'user', 'content': 'Two sessions; include pressing each session and prefer the better progression route.'}], equipment)
    messages = requirement_messages(stored)
    source = {'definition_id': 'LIBRARY_0', 'numWorkSets': 5,
              'allocationBounds': {'minimum': 1, 'maximum': 6},
              'superset': None, 'satisfiesCoverage': ['push']}
    fixed = {**source, 'definition_id': 'LIBRARY_1',
             'allocationBounds': {'minimum': 5, 'maximum': 5}}
    template = copy.deepcopy(draft['workouts'][0]['exercises'][0])
    template['repDurationSeconds'] = 3
    sessions = [{'name': f'Day {index}', 'description': 'Pressing', 'timesCompletedInAWeek': 1,
                 'trainingDays': [index * 3], 'exercises': [copy.deepcopy(source), copy.deepcopy(fixed)]}
                for index in range(2)]
    arguments = {'requirementsId': stored['requirementsId'], 'baseDraftId': None,
                 'name': 'Program', 'sessions': sessions}
    prepared = session_drafting.prepare_workout_sessions(arguments, messages, equipment)
    store_tool(messages, 'prepare_workout_sessions', arguments, prepared)
    state = request_planning_state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    monkeypatch.setattr(joint_planning, 'progression_margin', lambda item, capability: {
        'penalty': 100 if item['definition_id'] == 'LIBRARY_0' else 0})

    def draft(client, request, **options):
        payload = json.loads(request[-1]['content'])
        if 'session' not in payload:
            raise AssertionError('Unexpected repair call')
        selection = payload['session']
        values = []
        for structure in selection['exercises']:
            exercise = copy.deepcopy(template)
            exercise.update({key: copy.deepcopy(structure[key]) for key in
                ('definition_id', 'numWorkSets', 'allocationBounds', 'superset', 'satisfiesCoverage')
                if key in structure})
            values.append(exercise)
        return json.dumps({key: copy.deepcopy(selection[key]) for key in
            ('name', 'description', 'timesCompletedInAWeek', 'trainingDays')} | {'exercises': values}), None, None

    monkeypatch.setattr(session_drafting, 'chat_call', draft)
    result = session_drafting.draft_workout_sessions(None, {'preparationId': prepared['preparationId']},
        messages, equipment, state)

    assert 'jointPlanning' in result, result
    assert result['jointPlanning']['feasible'], result.get('errors')
    assert result['jointPlanning']['preserveSourceSelection'] is False
    assert [item['definition_id'] for day in result['proposedSubmission']['workouts']
            for item in day['exercises']] == ['LIBRARY_1', 'LIBRARY_1']
    assert [item['numWorkSets'] for day in result['proposedSubmission']['workouts']
            for item in day['exercises']] == [5, 5]
    audited = audit_workout_plan(result['proposedSubmission'], equipment, messages)
    assert audited['passed']
    assert audited['audit']['weeklyCoverageSets']['push'] == 10


def test_session_drafting_does_not_require_or_request_app_owned_progression_method(monkeypatch):
    equipment, messages, prepared, exercises = week_case()
    exercises = [{key: value for key, value in item.items() if key != 'progressionMethod'} for item in exercises]
    monkeypatch.setattr('workout_generator_pkg.recipe_contracts.qualify_recipe_contracts',
        lambda *a, **k: {'contracts': [{'definition_id': 'LIBRARY_0', 'satisfiesCoverage': [],
            'progressionPlan': {'kind': 'reps', 'nextDefinitionId': None, 'nextDefinitionName': None,
                'atCeilingAction': 're_audit_higher_reps'}}], 'capabilities': {}})
    state = request_planning_state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    response_schemas = []

    def draft_session(_, request, **__):
        payload = json.loads(request[-1]['content'])
        response_schemas.append(payload['responseSchema'])
        assert 'progressionMethod' not in payload['recipeContracts']['LIBRARY_0']
        return json.dumps({'name': payload['session']['name'], 'description': payload['session']['description'],
            'timesCompletedInAWeek': 1, 'trainingDays': payload['session']['trainingDays'],
            'exercises': copy.deepcopy(exercises)}), None, None

    monkeypatch.setattr(session_drafting, 'chat_call', draft_session)
    result = session_drafting.draft_workout_sessions(None, {'preparationId': prepared['preparationId']}, messages,
        equipment, state)

    assert result['jointPlanning']['feasible'], result
    exercise_schema = response_schemas[0]['properties']['exercises']['items']
    assert 'progressionMethod' not in exercise_schema['properties']
    assert 'progressionMethod' not in exercise_schema['required']
    assert all('progressionMethod' not in item
        for day in result['proposedSubmission']['workouts'] for item in day['exercises'])


def test_qualified_missing_coverage_returns_to_selection_before_workers(monkeypatch):
    equipment, messages, prepared, _ = week_case(coverage=[{
        'key': 'press', 'description': 'Pressing movement', 'scope': 'weekly'}])
    monkeypatch.setattr('workout_generator_pkg.recipe_contracts.qualify_recipe_contracts',
        lambda *a, **k: {'contracts': [{'definition_id': 'LIBRARY_0', 'satisfiesCoverage': [],
            'progressionPlan': {'kind': 'reps', 'nextDefinitionId': None, 'nextDefinitionName': None}}]})
    monkeypatch.setattr(session_drafting, 'chat_call', lambda *a, **k: pytest.fail('Missing coverage must stop before workers'))
    result = session_drafting.draft_workout_sessions(None, {'preparationId': prepared['preparationId']},
        messages, equipment, {})
    assert result['preparationErrors'] and not result.get('executionFailure')
    store_tool(messages, 'draft_workout_sessions', {'preparationId': prepared['preparationId']}, result)
    assert session_drafting.preparation_repair_task(messages)


def test_only_unsupported_approved_warmup_option_returns_to_selection_before_workers(monkeypatch):
    equipment, messages, prepared, _ = week_case(
        execution_rules=[{'kind': 'warmup', 'coverageKey': 'chest'}],
        coverage=[{'key': 'chest', 'description': 'Chest work', 'scope': 'eachSession'}])
    monkeypatch.setattr('workout_generator_pkg.recipe_contracts.qualify_recipe_contracts',
        lambda *a, **k: {'contracts': [{'definition_id': 'LIBRARY_0', 'satisfiesCoverage': ['chest']} ]})
    monkeypatch.setattr(session_drafting, 'chat_call', lambda *a, **k: pytest.fail(
        'Unsupported warm-up capability must return to menu selection before worker drafting'))

    result = session_drafting.draft_workout_sessions(None,
        {'preparationId': prepared['preparationId']}, messages, equipment, {})

    assert not result.get('executionFailure')
    assert result['preparationErrors']
    assert {error['code'] for error in result['preparationErrors']} == {'required_coverage_missing'}
    store_tool(messages, 'draft_workout_sessions',
        {'preparationId': prepared['preparationId']}, result)
    task = session_drafting.preparation_repair_task(messages)
    assert task and task['needsAlternatives']


def test_unsupported_load_suitability_returns_to_scoped_candidate_selection():
    equipment, messages, prepared, _ = week_case(occurrences=2)
    selected = prepared['recipeSessions']
    selected[1]['exercises'][1]['definition_id'] = 'LIBRARY_777'
    proposal = copy.deepcopy(selected[1])
    worker_result = {'preparationId': prepared['preparationId'], 'workerResults': {'0': selected[0], '2': selected[2]},
        'workerFailures': {'1': {'proposal': proposal, 'errors': [{
            'code': 'training_load_suitability_unresolved', 'repairStage': 'candidate_reassessment',
            'path': '/workouts/0/exercises/0', 'exercise': 'Fixed-bodyweight movement',
            'repair': 'Select a suitable supported movement configuration or ask the user.'}],
            'message': 'Session preflight needs correction.'}}, 'passed': False}
    store_tool(messages, 'draft_workout_sessions', {'preparationId': prepared['preparationId']}, worker_result)

    task = session_drafting.preparation_repair_task(messages)
    assert task and task['needsAlternatives']
    assert task['basePreparationId'] == f"PREPARATION_{len(messages) - 1}"
    contract = task['blockRepair']['sessions']['SESSION_1']
    affected = '/sessions/1/exercises/0'
    assert contract['editableOccurrences'] == [affected]

    blocks = []
    for index in range(len(selected[1]['exercises'])):
        member = ({'replaces': f'/sessions/1/exercises/{index}', 'definition_id': 'LIBRARY_999',
                   'satisfiesCoverage': []} if index == 0 else f'/sessions/1/exercises/{index}')
        blocks.append({'exercises': [member]})
    repaired = session_drafting.resolve_preparation_patch({'basePreparationId': task['basePreparationId'],
        'sessionBlocks': [{'sessionReference': 'SESSION_1', 'blocks': blocks}]}, messages)
    assert repaired['sessions'][1]['exercises'][0]['definition_id'] == 'LIBRARY_999'
    assert repaired['sessions'][0] == selected[0] and repaired['sessions'][2] == selected[2]
    no_op_blocks = copy.deepcopy(blocks)
    no_op_blocks[0]['exercises'][0]['definition_id'] = selected[1]['exercises'][0]['definition_id']
    no_op_blocks[0], no_op_blocks[1] = no_op_blocks[1], no_op_blocks[0]
    with pytest.raises(ValueError, match='same movement'):
        session_drafting.resolve_preparation_patch({'basePreparationId': task['basePreparationId'],
            'sessionBlocks': [{'sessionReference': 'SESSION_1', 'blocks': no_op_blocks}]}, messages)


def test_unmarked_history_finding_does_not_reopen_selection():
    equipment, messages, prepared, _ = week_case()
    worker_result = {'preparationId': prepared['preparationId'], 'workerFailures': {'1': {
        'proposal': copy.deepcopy(prepared['recipeSessions'][1]), 'errors': [{
            'code': 'training_load_suitability_unresolved', 'path': '/workouts/0/exercises/0'}]}}, 'passed': False}
    store_tool(messages, 'draft_workout_sessions', {'preparationId': prepared['preparationId']}, worker_result)
    assert session_drafting.preparation_repair_task(messages) is None


def test_history_repair_scope_allows_rep_targets_without_authorizing_load_edits():
    from workout_generator_pkg.json_patching import validate_patch_operations_scope
    finding = {'code': 'training_load_suitability_unresolved', 'repairStage': 'candidate_reassessment',
               'path': '/workouts/0/exercises/2'}
    exercise = {'minReps': 8, 'maxReps': 10, 'workSetTemplate': {'reps': 8, 'additionalWeight': 5}}
    allowed = session_drafting._suitability_repair_paths(finding, exercise)
    assert allowed == [
        '/workouts/0/exercises/2/maxReps', '/workouts/0/exercises/2/minReps',
        '/workouts/0/exercises/2/workSetTemplate/reps']
    validate_patch_operations_scope([{'op': 'replace', 'path': allowed[0], 'value': 12}], set(allowed), set())
    with pytest.raises(ValueError, match='outside|permitted|scope'):
        validate_patch_operations_scope([{'op': 'replace',
            'path': '/workouts/0/exercises/2/workSetTemplate/additionalWeight', 'value': 10}], set(allowed), set())
    exercise = {'minReps': 8, 'maxReps': 10, 'targetSetPrescriptions': [
        {'reps': 8, 'additionalWeight': 5}, {'reps': 10, 'additionalWeight': 5}]}
    allowed = session_drafting._suitability_repair_paths(finding, exercise)
    assert allowed == [
        '/workouts/0/exercises/2/maxReps', '/workouts/0/exercises/2/minReps',
        '/workouts/0/exercises/2/targetSetPrescriptions/0/reps',
        '/workouts/0/exercises/2/targetSetPrescriptions/1/reps']


def test_group_and_history_repairs_compose_without_widening_rep_scope():
    from workout_generator_pkg.json_patching import apply_json_patch
    finding = {'code': 'training_load_suitability_unresolved', 'repairStage': 'candidate_reassessment',
        'path': '/workouts/0/exercises/0', 'permittedPaths': {'exact': [
            '/workouts/0/exercises/0/minReps', '/workouts/0/exercises/0/maxReps',
            '/workouts/0/exercises/0/workSetTemplate/reps'], 'descendants': []}}
    group = {'code': 'execution_supersetNoReconfiguration', 'groupRepairOnly': True,
        'path': '/workouts/0/exercises', 'affectedIndices': [0, 1]}
    before = {'workouts': [{'exercises': [
        {'definition_id': 'LIBRARY_0', 'superset': 'A', 'minReps': 8, 'maxReps': 10,
         'workSetTemplate': {'reps': 8, 'additionalWeight': 0}},
        {'definition_id': 'LIBRARY_1', 'superset': None, 'minReps': 8, 'maxReps': 10,
         'workSetTemplate': {'reps': 8, 'additionalWeight': 0}}]}]}
    patch = [
        {'op': 'replace', 'path': '/workouts/0/exercises/0/maxReps', 'value': 12},
        {'op': 'replace', 'path': '/workouts/0/exercises/0/workSetTemplate/reps', 'value': 10},
        {'op': 'replace', 'path': '/workouts/0/exercises/0/superset', 'value': None},
        {'op': 'move', 'from': '/workouts/0/exercises/1', 'path': '/workouts/0/exercises/0'},
    ]
    after = apply_json_patch(before, patch)['workouts'][0]
    session_drafting._validate_mixed_group_repair(before, after, patch, [group, finding])
    bad_patch = [dict(patch[0]), {'op': 'replace',
        'path': '/workouts/0/exercises/0/workSetTemplate/additionalWeight', 'value': 10}, *patch[1:]]
    bad_after = apply_json_patch(before, bad_patch)['workouts'][0]
    with pytest.raises(ValueError, match='outside the reported findings'):
        session_drafting._validate_mixed_group_repair(before, bad_after, bad_patch, [group, finding])


def test_initial_preparation_omitted_revision_is_null_without_mutating_request():
    equipment, messages, prepared, _ = week_case()
    arguments = {key: copy.deepcopy(prepared[key]) for key in ('requirementsId', 'name', 'sessions')}
    original = copy.deepcopy(arguments)
    result = session_drafting.prepare_workout_sessions(arguments, messages, equipment)
    assert result['baseDraftId'] is None
    assert arguments == original
    arguments['baseDraftId'] = 'REVISION_999'
    with pytest.raises(ValueError, match='stale'):
        session_drafting.prepare_workout_sessions(arguments, messages, equipment)


def test_shared_selection_requires_coverage_before_worker_calls():
    from workout_generator_pkg.planning_tools import PlanningInputError
    equipment, requirements, _, draft = planning_case()
    requirements['sessionsPerWeek'] = 3
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 15, 'maximum': 18}
    requirements['requiredCoverage'] = [
        {'key': 'chest', 'description': 'Chest in every session', 'scope': 'eachSession'},
        {'key': 'push', 'description': 'Upper push weekly', 'scope': 'weekly'}]
    stored = set_workout_requirements(requirements, [{'role': 'user', 'content': 'Chest every session and upper push weekly.'}], equipment)
    messages = requirement_messages(stored)
    arguments = {'requirementsId': stored['requirementsId'], 'baseDraftId': None, 'name': 'Week',
        'sessions': [{'name': f'Day {index}', 'description': 'Full body', 'timesCompletedInAWeek': 1,
                      'exercises': structure()} for index in range(3)]}
    arguments['sessions'][0].update(description='Full body', trainingDays=[0])
    with pytest.raises(PlanningInputError) as failure:
        session_drafting.prepare_workout_sessions(arguments, messages, equipment)
    assert {error['coverageKey'] for error in failure.value.errors if 'coverageKey' in error} == {'chest', 'push'}
    assert {error['path'] for error in failure.value.errors} == {
        '/sessions', '/sessions/0/exercises', '/sessions/1/exercises', '/sessions/2/exercises'}
    arguments['sessions'][0]['description'] = 'Full body'
    for day in arguments['sessions']:
        day['exercises'][0]['satisfiesCoverage'] = ['chest', 'push']
    prepared = session_drafting.prepare_workout_sessions(arguments, messages, equipment)
    assert all(day['exercises'][0]['satisfiesCoverage'] == ['chest', 'push'] for day in prepared['sessions'])


def test_session_preparation_preserves_description_with_schedule():
    equipment, messages, prepared, _ = week_case()
    arguments = copy.deepcopy({key: prepared[key] for key in ('requirementsId', 'baseDraftId', 'name', 'sessions')})
    for day in arguments['sessions']:
        day['description'] = 'Full body'
    result = session_drafting.prepare_workout_sessions(arguments, messages, equipment)
    assert [day['description'] for day in result['sessions']] == [day['description'] for day in arguments['sessions']]


def test_preparation_rejects_coupled_volume_conflict_before_session_workers():
    from workout_generator_pkg.planning_tools import PlanningInputError
    equipment, requirements, _, draft = planning_case()
    equipment['exerciseDefinitions'][0]['muscleGroups'] = ['FRONT_CHEST']
    equipment['exerciseDefinitions'][0]['secondaryMuscleGroups'] = ['FRONT_DELTOIDS']
    requirements['sessionsPerWeek'] = 3
    requirements['auditTargets']['weeklyEffectiveSets'] = {
        'chest':{'minimum':15,'maximum':18},'shoulders':{'minimum':0,'maximum':6}}
    requirements['auditTargets']['perSessionEffectiveSets'] = {}
    stored = set_workout_requirements(requirements,[{'role':'user','content':'Three sessions, chest 15-18 weekly and shoulders at most 6.'}],equipment)
    arguments = {'requirementsId':stored['requirementsId'],'baseDraftId':None,'name':'Week',
        'sessions':[{**{k:v for k,v in draft['workouts'][0].items() if k != 'exercises'},
                     'name':f'Day {i}','exercises': structure()} for i in range(3)]}
    with pytest.raises(PlanningInputError) as error:
        session_drafting.prepare_workout_sessions(arguments,requirement_messages(stored),equipment)
    assert error.value.code == 'infeasible_set_allocation'
    assert {c['target'] for c in error.value.errors[0]['conflictingTargets']} == {'weekly:chest','weekly:shoulders'}


def test_sessions_draft_concurrently_then_merge_once_and_audit_complete_week(monkeypatch):
    equipment, messages, prepared, exercises = week_case()
    state = request_planning_state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert state['constructionTask']['stage'] == 'draft_sessions'
    assert pending_evidence(state) == ['LIBRARY_0']  # Retrieved automatically when a history backup is loaded.
    warnings = [{'path': '/draft/workouts/0', 'evidencePaths': [], 'severity': 'warning', 'message': 'Calibrate session A effort.'},
                {'path': '/draft', 'evidencePaths': [], 'severity': 'warning', 'message': 'Manage weekly recovery.'}]
    monkeypatch.setattr(plan_review, 'review_week_structure', lambda *a, **k: {'passed': True, 'findings': warnings})
    barrier = threading.Barrier(3)
    def draft(client, request, **options):
        from workout_generator_pkg.training_history import PRESCRIPTION_EVIDENCE_INSTRUCTION
        assert PRESCRIPTION_EVIDENCE_INSTRUCTION in request[0]['content']
        assert PRESCRIPTION_EVIDENCE_INSTRUCTION in shell.CANONICAL_PLANNING_INSTRUCTION
        payload = json.loads(request[-1]['content'])
        assert payload['sharedSessionTargets']['chest'] == {'minimum': 5, 'maximum': 6}
        assert len(payload['sharedWeek']) == 3
        assert 'structureReviewFindings' not in payload  # Review follows the complete executable week.
        assert payload['programmingGuidelines'] == session_drafting.GUIDELINE_POLICY
        barrier.wait(timeout=3)
        selection = payload['session']
        return json.dumps({**{k: v for k, v in selection.items() if k not in ('definition_ids', 'structure', 'coverageAssignments')},
                           'exercises': exercises}), None, None
    monkeypatch.setattr(session_drafting, 'chat_call', draft)
    before = copy.deepcopy(messages)
    checkpoints = []
    result = session_drafting.draft_workout_sessions(None, {'preparationId': prepared['preparationId']}, messages,
        equipment, state, checkpoint=lambda result: checkpoints.append(copy.deepcopy(result)))
    assert messages == before and len(checkpoints) == 4
    assert [day['name'] for day in result['proposedSubmission']['workouts']] == ['Session 0', 'Session 1', 'Session 2']
    store_tool(messages, 'draft_workout_sessions', {}, result)
    pending = request_planning_state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert pending['currentDraft'] is None and pending['parallelSubmission'] == result['proposedSubmission']
    assert 'constructionTask' not in pending
    assert shell.construction_tool_failure('audit_workout_plan', pending['parallelSubmission'], pending) is None
    report = audit_workout_plan(pending['parallelSubmission'], equipment, messages)
    assert report['passed'] and report['audit']['weeklyVolume']['chest']['effective'] == 15


def test_worker_cannot_undo_preallocated_counts(monkeypatch):
    from workout_generator_pkg.allocation import auto_allocate_workout
    equipment, messages, prepared, exercises = week_case()
    state = request_planning_state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    def draft(client, request, **options):
        payload = json.loads(request[-1]['content'])
        assert 'allocationBounds' in payload['responseSchema']['properties']['exercises']['items']['required']
        values = copy.deepcopy(exercises)
        for exercise in values:
            exercise.update(numWorkSets=4, allocationBounds={'minimum': 1, 'maximum': 6})
        return json.dumps({**{k:v for k,v in payload['session'].items() if k not in ('definition_ids', 'structure', 'coverageAssignments')}, 'exercises': values}),None,None
    monkeypatch.setattr(session_drafting, 'chat_call', draft)
    workers = session_drafting.draft_workout_sessions(None, {'preparationId': prepared['preparationId']}, messages, equipment, state)
    initial = audit_workout_plan(workers['proposedSubmission'], equipment, messages)
    assert initial['passed']
    allocated = auto_allocate_workout(initial, equipment, messages)
    assert allocated['passed'] and 'automaticAllocation' not in allocated
    assert 15 <= allocated['audit']['weeklyVolume']['chest']['effective'] <= 18
    for before, after in zip(initial['submittedDraft']['workouts'], allocated['submittedDraft']['workouts']):
        assert before['name'] == after['name'] and before['trainingDays'] == after['trainingDays']


def test_metadata_only_preparation_reuses_prescription_workers(monkeypatch):
    equipment, messages, prepared, exercises = week_case()
    state = request_planning_state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    monkeypatch.setattr(session_drafting, 'chat_call', lambda *a, **k: (json.dumps({'exercises': copy.deepcopy(exercises)}), None, None))
    result = session_drafting.draft_workout_sessions(None, {'preparationId': prepared['preparationId']}, messages, equipment, state)
    store_tool(messages, 'draft_workout_sessions', {}, result)
    renamed = copy.deepcopy(prepared)
    renamed['preparationId'] = 'Renamed preparation'
    for collection in ('sessions', 'recipeSessions'):
        renamed[collection][0]['name'] = 'New name'
    store_tool(messages, 'prepare_workout_sessions', {}, renamed)
    monkeypatch.setattr(session_drafting, 'chat_call', lambda *a, **k: pytest.fail('Metadata does not invalidate prescriptions'))
    reused = session_drafting.draft_workout_sessions(None, {'preparationId': renamed['preparationId']}, messages, equipment, state)
    assert reused['proposedSubmission']['workouts'][0]['name'] == 'New name'
    assert reused['workerInputHashes'] == result['workerInputHashes']


def test_workers_materialize_committed_metadata_and_coverage_without_model_repair(monkeypatch):
    equipment,messages,prepared,exercises=week_case(coverage=[{'key':'chest', 'description':'Chest work', 'scope':'weekly'}])
    for day in prepared['recipeSessions']:
        day['exercises'][0]['satisfiesCoverage']=['chest']
    store_tool(messages,'prepare_workout_sessions',{},prepared)
    state=request_planning_state(shell._messages_for_api(messages,True,provided_equipment=equipment))
    calls=[]
    def respond(client,request,**options):
        calls.append(1)
        return json.dumps({'name':'Changed','description':'Changed','trainingDays':[6],
            'timesCompletedInAWeek':7,'exercises':exercises}),None,None
    monkeypatch.setattr(session_drafting,'chat_call',respond)
    result=session_drafting.draft_workout_sessions(None,{'preparationId':prepared['preparationId']},messages,equipment,state)
    assert len(calls)==3
    for expected,actual in zip(prepared['sessions'],result['proposedSubmission']['workouts']):
        assert actual['name']==expected['name'] and actual['trainingDays']==expected['trainingDays']
        assert actual['exercises'][0]['satisfiesCoverage']==['chest']
        assert actual['exercises'][0]['numWorkSets']==exercises[0]['numWorkSets']


def test_worker_movement_mismatch_enters_bounded_preflight_repair(monkeypatch):
    equipment,messages,prepared,exercises=week_case()
    state=request_planning_state(shell._messages_for_api(messages,True,provided_equipment=equipment))
    repairs=[]
    def respond(client,request,**options):
        payload=json.loads(request[-1]['content'])
        if 'permittedPaths' in payload:
            repairs.append(payload)
            return json.dumps({'patch':[{'op':'replace','path':'/workouts/0/exercises/0/definition_id','value':'LIBRARY_0'}]}),None,None
        values=copy.deepcopy(exercises)
        if payload['session']['name']=='Session 1': values[0]['definition_id']='LIBRARY_999'
        return json.dumps({'exercises':values}),None,None
    monkeypatch.setattr(session_drafting,'chat_call',respond)
    result=session_drafting.draft_workout_sessions(None,{'preparationId':prepared['preparationId']},messages,equipment,state)
    assert len(repairs)==1 and repairs[0]['permittedPaths']==['/workouts/0/exercises']
    assert result['proposedSubmission']['workouts'][1]['exercises'][0]['definition_id']=='LIBRARY_0'


def test_failed_session_preserves_completed_workers_and_retries_only_unfinished(monkeypatch):
    equipment, messages, prepared, exercises = week_case()
    state = request_planning_state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    ready = threading.Event()
    calls = []
    def draft(client, request, **options):
        selection = json.loads(request[-1]['content'])['session']
        calls.append(selection['name'])
        if selection['name'] == 'Session 1' and calls.count('Session 1') == 1:
            assert ready.wait(3)
            raise RuntimeError('Worker failed')
        return json.dumps({**{k: v for k, v in selection.items() if k not in ('definition_ids', 'structure', 'coverageAssignments')}, 'exercises': exercises}), None, None
    monkeypatch.setattr(session_drafting, 'chat_call', draft)
    def checkpoint(result):
        if len(result['workerResults']) == 2:
            ready.set()
    arguments = {'preparationId': prepared['preparationId']}
    failed = session_drafting.draft_workout_sessions(None, arguments, messages, equipment, state, checkpoint=checkpoint)
    assert failed['passed'] is False and 'proposedSubmission' not in failed
    assert set(failed['workerResults']) == {'0', '2'}
    store_tool(messages, 'draft_workout_sessions', arguments, failed)
    resumed = session_drafting.draft_workout_sessions(None, arguments, messages, equipment, state)
    assert 'proposedSubmission' in resumed
    assert calls.count('Session 0') == calls.count('Session 2') == 1 and calls.count('Session 1') == 2
    # Old worker proposals must not bypass an updated shared fatigue policy.
    stale = copy.deepcopy(resumed)
    stale['guidelineVersion'] -= 1
    store_tool(messages, 'draft_workout_sessions', arguments, stale)
    session_drafting.draft_workout_sessions(None, arguments, messages, equipment, state)
    assert calls.count('Session 0') == calls.count('Session 2') == 2 and calls.count('Session 1') == 3
    messages.append({'role': 'user', 'content': 'Change the movement allocation.'})
    with pytest.raises(ValueError, match='stale'):
        session_drafting.draft_workout_sessions(None, arguments, messages, equipment, state)


@pytest.mark.parametrize('escape_scope', [False, True])
def test_worker_preflight_repairs_only_invalid_note_before_week_submission(monkeypatch, escape_scope):
    equipment, messages, prepared, exercises = week_case()
    state = request_planning_state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    repairs = []
    def respond(client, request, **options):
        payload = json.loads(request[-1]['content'])
        if 'permittedPaths' in payload:
            repairs.append(payload)
            path = '/workouts/0/exercises/0/' + ('numWorkSets' if escape_scope else 'placementNotes')
            assert options['reasoning_effort'] is None
            return json.dumps({'patch': [{'op': 'replace', 'path': path, 'value': 1 if escape_scope else 'Controlled execution.'}]}), None, None
        selection = payload['session']
        values = copy.deepcopy(exercises)
        if selection['name'] == 'Session 0':
            values[0]['placementNotes'] = 'x' * 501
        return json.dumps({**{k:v for k,v in selection.items() if k not in ('definition_ids', 'structure', 'coverageAssignments')}, 'exercises': values}), None, None
    monkeypatch.setattr(session_drafting, 'chat_call', respond)
    result = session_drafting.draft_workout_sessions(None, {'preparationId': prepared['preparationId']}, messages, equipment, state)
    assert len(repairs) == 1
    assert repairs[0]['permittedPaths'] == ['/workouts/0/exercises/0/placementNotes']
    assert ('proposedSubmission' in result) is not escape_scope
    if not escape_scope:
        assert result['proposedSubmission']['workouts'][0]['exercises'][0]['numWorkSets'] == exercises[0]['numWorkSets']


def test_worker_repairs_grouping_and_non_group_finding_together(monkeypatch):
    equipment, messages, prepared, exercises = week_case()
    prepared['recipeSessions'][0]['exercises'][0]['superset'] = 'singleton'
    messages[-1]['content'] = json.dumps(prepared)
    state = request_planning_state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    repairs = []
    def respond(client, request, **options):
        payload = json.loads(request[-1]['content'])
        if 'permittedPaths' in payload:
            repairs.append(payload)
            assert any(error.get('groupRepairOnly') for error in payload['errors'])
            assert any(error.get('path', '').endswith('/effortAcceptance/acceptanceCriterion') for error in payload['errors'])
            assert 'apply those field edits before any moves' in request[0]['content']
            return json.dumps({'patch': [
                {'op': 'replace', 'path': '/workouts/0/exercises/0/effortAcceptance/acceptanceCriterion', 'value': 'Controlled execution.'},
                {'op': 'replace', 'path': '/workouts/0/exercises/0/superset', 'value': None},
            ]}), None, None
        values = copy.deepcopy(exercises)
        if payload['session']['name'] == 'Session 0':
            values[0].update(superset='singleton', effortAcceptance={
                'kind': 'technical_criteria', 'acceptanceCriterion': 'x' * 241,
                'terminationCriterion': 'Stop before technique degrades.'})
        return json.dumps({**{key: value for key, value in payload['session'].items()
                              if key not in ('definition_ids', 'structure', 'coverageAssignments')},
                           'exercises': values}), None, None
    monkeypatch.setattr(session_drafting, 'chat_call', respond)
    result = session_drafting.draft_workout_sessions(None, {'preparationId': prepared['preparationId']},
        messages, equipment, state)
    assert 'proposedSubmission' in result, json.dumps(result.get('workerFailures', result.get('errors')), indent=2)
    assert len(repairs) == 1
    assert result['workerResults']['0']['exercises'][0]['effortAcceptance']['acceptanceCriterion'] == 'Controlled execution.'
    assert result['workerResults']['0']['exercises'][0]['superset'] is None


def test_worker_applies_native_load_calibration_before_history_suitability(monkeypatch):
    equipment, messages, prepared, exercises = week_case()
    equipment['exerciseDefinitions'][0].update(exerciseType='WEIGHT', equipmentId='EQUIPMENT_0',
                                               bodyWeightPercentage=None)
    equipment['equipments'].append({'id': 'EQUIPMENT_0', 'name': 'Adjustable Dumbbells',
                                    'type': 'DUMBBELLS', 'availableWeights': [{'weight': 5}]})
    preparation_args = {key: copy.deepcopy(prepared[key]) for key in
                        ('requirementsId', 'baseDraftId', 'name', 'sessions')}
    prepared = session_drafting.prepare_workout_sessions(preparation_args, messages, equipment)
    store_tool(messages, 'prepare_workout_sessions', preparation_args, prepared)
    state = request_planning_state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    repairs = []
    def suitability(plan, source_messages, gear):
        assert source_messages is messages and gear is equipment
        assert plan['exercises'][0]['requiresLoadCalibration'] is True
        return []
    def respond(client, request, **options):
        payload = json.loads(request[-1]['content'])
        if 'permittedPaths' in payload:
            repairs.append(payload)
            pytest.fail(json.dumps(payload['errors'], indent=2))
        selection = payload['session']
        values=copy.deepcopy(exercises)
        return json.dumps({**{k:v for k,v in selection.items() if k not in ('definition_ids', 'structure', 'coverageAssignments')}, 'exercises': values}),None,None
    monkeypatch.setattr(session_drafting, 'chat_call', respond)
    result = session_drafting.draft_workout_sessions(None, {'preparationId': prepared['preparationId']}, messages, equipment, state,
        training_history=SimpleNamespace(load_suitability_errors=suitability))
    assert 'proposedSubmission' in result, result.get('errors')
    assert repairs == []


def test_group_preflight_reports_all_interleaved_and_singleton_groups():
    exercises = [{'superset': key} for key in ('A', 'B', 'A', 'C', 'B', 'C', 'D')]
    errors = session_drafting._group_structure_errors(exercises)
    assert [error['affectedIndices'] for error in errors] == [[0, 2], [1, 4], [3, 5], [6]]
    assert all(error['groupRepairOnly'] for error in errors)


def test_group_repair_preserves_numeric_values_and_boolean_types():
    before = {'exercises': [{'definition_id': 'LIBRARY_0', 'superset': 'A',
                            'workSetTemplate': {'weight': 42.0, 'reps': 8}, 'generateWarmUpSets': False}]}
    after = copy.deepcopy(before)
    after['exercises'][0]['workSetTemplate']['weight'] = 42
    session_drafting._validate_group_repair(before, after)
    after['exercises'][0]['generateWarmUpSets'] = 0
    with pytest.raises(ValueError, match='outside grouping'):
        session_drafting._validate_group_repair(before, after)


def test_mixed_group_repair_edits_original_occurrence_before_reordering():
    before = {'workouts': [{'description': 'x' * 501, 'exercises': [
        {'definition_id': 'LIBRARY_0', 'superset': 'A', 'workSetTemplate': {'reps': 8}},
        {'definition_id': 'LIBRARY_1', 'superset': None, 'workSetTemplate': {'reps': 10}},
        {'definition_id': 'LIBRARY_2', 'superset': 'A', 'targetSetPrescriptions': [
            {'workSetIndex': 0, 'reps': 6}], 'workSetTemplate': {'reps': 6}},
    ]}]}
    errors = [
        {'groupRepairOnly': True, 'code': 'invalid_session_group', 'path': '/workouts/0/exercises',
         'affectedIndices': [0, 2]},
        {'code': 'setup_time_required', 'path': '/workouts/0/exercises/2/setupSeconds',
         'permittedPaths': {'exact': ['/workouts/0/exercises/2/setupSeconds'], 'descendants': []}},
        {'code': 'invalid_target_set_prescription_load', 'path': '/workouts/0/exercises/2'},
        {'code': 'invalid_session_field', 'path': '/workouts/0/description',
         'permittedPaths': {'exact': ['/workouts/0/description'], 'descendants': []}},
    ]
    patch = [
        {'op': 'add', 'path': '/workouts/0/exercises/2/setupSeconds', 'value': 45},
        {'op': 'add', 'path': '/workouts/0/exercises/2/targetSetPrescriptions/0/weight', 'value': 20},
        {'op': 'replace', 'path': '/workouts/0/description', 'value': 'Concise session.'},
        {'op': 'move', 'from': '/workouts/0/exercises/2', 'path': '/workouts/0/exercises/1'},
    ]
    after = session_drafting.apply_json_patch(before, patch)['workouts'][0]
    session_drafting._validate_mixed_group_repair(before, after, patch, errors)
    assert after['exercises'][1]['setupSeconds'] == 45
    assert after['exercises'][1]['targetSetPrescriptions'][0]['weight'] == 20
    assert after['description'] == 'Concise session.'
    assert [item['definition_id'] for item in after['exercises']] == ['LIBRARY_0', 'LIBRARY_2', 'LIBRARY_1']


def test_mixed_group_repair_rejects_unreported_sibling_and_array_replacement():
    before = {'workouts': [{'exercises': [
        {'definition_id': 'LIBRARY_0', 'superset': 'A'},
        {'definition_id': 'LIBRARY_1', 'superset': None},
        {'definition_id': 'LIBRARY_2', 'superset': 'A'},
    ]}]}
    errors = [
        {'groupRepairOnly': True, 'code': 'invalid_session_group', 'path': '/workouts/0/exercises',
         'affectedIndices': [0, 2]},
        {'code': 'invalid_target_set_prescription_load', 'path': '/workouts/0/exercises/2'},
    ]
    sibling_patch = [
        {'op': 'add', 'path': '/workouts/0/exercises/1/workSetTemplate', 'value': {'weight': 20}},
        {'op': 'move', 'from': '/workouts/0/exercises/2', 'path': '/workouts/0/exercises/1'},
    ]
    sibling_after = session_drafting.apply_json_patch(before, sibling_patch)['workouts'][0]
    with pytest.raises(ValueError, match='outside the reported findings'):
        session_drafting._validate_mixed_group_repair(before, sibling_after, sibling_patch, errors)

    replacement = [{'op': 'replace', 'path': '/workouts/0/exercises', 'value': before['workouts'][0]['exercises']}]
    with pytest.raises(ValueError, match='preserve exercises'):
        session_drafting._validate_mixed_group_repair(before, before['workouts'][0], replacement, errors)


def test_worker_cannot_replace_accepted_groups_or_counts(monkeypatch):
    equipment, messages, prepared, exercises = week_case(occurrences=3)
    state = request_planning_state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    def respond(client, request, **options):
        payload = json.loads(request[-1]['content'])
        assert 'permittedPaths' not in payload
        values = [copy.deepcopy(exercises[0]) for _ in payload['session']['exercises']]
        for index, value in enumerate(values):
            value.update(numWorkSets=20, superset='Invented' if index in (0, 2) else None)
        return json.dumps({'exercises': values}), None, None
    monkeypatch.setattr(session_drafting, 'chat_call', respond)
    result = session_drafting.draft_workout_sessions(None, {'preparationId': prepared['preparationId']}, messages, equipment, state)
    assert 'proposedSubmission' in result, result.get('errors')
    for index, expected in enumerate(prepared['recipeSessions']):
        day = result['workerResults'][str(index)]
        assert [item['numWorkSets'] for item in day['exercises']] == [item['numWorkSets'] for item in expected['exercises']]
        assert all(item['superset'] is None for item in day['exercises'])
    assert result['jointPlanning']['feasible']


def test_worker_repairs_local_rest_and_oversized_note_together(monkeypatch):
    rules = [{'kind': 'rest', 'coverageKey': None, 'context': 'straightSets', 'minimumSeconds': 90, 'maximumSeconds': 150}]
    equipment, messages, prepared, exercises = week_case(execution_rules=rules)
    state = request_planning_state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    repairs = []
    def respond(client, request, **options):
        payload = json.loads(request[-1]['content'])
        if 'permittedPaths' in payload:
            repairs.append(payload)
            assert any(error.get('code') == 'execution_rest' for error in payload['errors'])
            assert any(error.get('code') == 'export_notes_too_long' for error in payload['errors'])
            return json.dumps({'patch': [
                {'op': 'replace', 'path': '/workouts/0/exercises/0/restBetweenSetsSeconds', 'value': 120},
                {'op': 'replace', 'path': '/workouts/0/exercises/0/placementNotes', 'value': 'Controlled execution.'}]}), None, None
        values = copy.deepcopy(exercises)
        for exercise in values:
            exercise['restBetweenSetsSeconds'] = 120
        if payload['session']['name'] == 'Session 0':
            values[0].update(restBetweenSetsSeconds=75, placementNotes='x' * 501)
        return json.dumps({**{k: v for k, v in payload['session'].items() if k not in ('definition_ids', 'structure', 'coverageAssignments')}, 'exercises': values}), None, None
    monkeypatch.setattr(session_drafting, 'chat_call', respond)
    result = session_drafting.draft_workout_sessions(None, {'preparationId': prepared['preparationId']}, messages, equipment, state)
    assert 'proposedSubmission' in result, result.get('errors')
    assert len(repairs) == 1
    assert result['workerResults']['0']['exercises'][0]['restBetweenSetsSeconds'] == 120
    assert 90 <= result['proposedSubmission']['workouts'][0]['exercises'][0]['restBetweenSetsSeconds'] <= 150


def test_missing_muscle_metadata_is_warning_but_supported_violation_remains_blocking(monkeypatch):
    equipment, _, stored, draft = planning_case()
    findings = [{'severity': 'blocking', 'basis': 'established_violation', 'path': '/draft/exercises/0',
                 'evidencePaths': ['/draft/libraryDefinitions/LIBRARY_0'],
                 'message': 'The claimed regional work is not represented.', 'repair': 'Find another regional exercise.',
                 'muscleTargets': ['lateralDelts']},
                {'severity': 'blocking', 'basis': 'established_violation', 'path': '/draft/exercises/0',
                 'evidencePaths': ['/sourceMessages/SOURCE_0'],
                 'message': 'The execution contradicts an explicit instruction.', 'repair': 'Correct the instruction.',
                 'muscleTargets': []}]
    monkeypatch.setattr(plan_review, 'chat_call', lambda *a, **k: (json.dumps({'findings': findings}), None, None))
    result = json.loads(shell.handle_function_call(None, requirement_messages(stored), 'audit_workout_plan', draft, equipment)['result'])
    assert [item['severity'] for item in result['review']['findings']] == ['warning', 'blocking']
    assert len(result['errors']) == 1 and result['errors'][0]['message'] == findings[1]['message']


def test_execution_repair_keeps_history_summaries_and_retrieves_details_only_on_demand():
    from workout_generator_pkg.planner_context import _focus_repair
    equipment, _, stored, draft = planning_case()
    state = {'requirementsApproved': True, 'requirements': stored['requirements'],
             'currentDraftId': 'REVISION_0', 'currentDraft': copy.deepcopy(draft),
             'lastAudit': {'passed': False, 'errors': [{'code': 'independent_review_finding',
                 'path': '/draft', 'reviewScope': 'execution', 'message': 'Check weekly movement balance.'}]},
             'otherToolResults': {}, 'exerciseCandidates': {'LIBRARY_0': {'name': 'Push-Up'}},
             'trainingEvidence': {'LIBRARY_0': {'reference': 'LIBRARY_0', 'name': 'Push-Up',
                 'status': 'comparable_records', 'sessions': [{'details': 'saved performance ' * 5000}]}}}
    before = copy.deepcopy(state)
    _focus_repair(state, set())
    assert not state['trainingEvidence']
    assert state['trainingEvidenceSummary']['LIBRARY_0']['status'] == 'comparable_records'
    assert len(json.dumps(state)) < len(json.dumps(before)) / 10
    requested = copy.deepcopy(before)
    _focus_repair(requested, set(), fresh_evidence={'LIBRARY_0'})
    assert requested['trainingEvidence'] == before['trainingEvidence']


def test_cancelled_parallel_work_keeps_checkpoints_and_never_publishes_late_results():
    from workout_generator_pkg.parallel_work import parallel_proposals
    from workout_generator_pkg.cancellation import run_cancellable
    cancelled, stopped, release, returned = (threading.Event() for _ in range(4))
    barrier = threading.Barrier(2)
    saved = []
    def fast():
        barrier.wait(3)
        return 'completed'
    def slow():
        barrier.wait(3)
        assert release.wait(3)
        returned.set()
        return 'late'
    def checkpoint(key, value):
        saved.append((key, value))
        cancelled.set()
    def run():
        try:
            return parallel_proposals([('fast', fast), ('slow', slow)], on_result=checkpoint)
        finally:
            stopped.set()
    try:
        with pytest.raises(KeyboardInterrupt):
            run_cancellable(run, cancel_event=cancelled)
        assert stopped.wait(3)
    finally:
        release.set()
    assert returned.wait(3)
    assert saved == [('fast', 'completed')]


def test_failed_independent_job_keeps_other_inflight_results():
    from workout_generator_pkg.parallel_work import parallel_proposals
    failed=threading.Event()
    saved=[]
    def bad():
        failed.set()
        raise ValueError('Invalid proposal')
    def good():
        assert failed.wait(3)
        return 'valid proposal'
    with pytest.raises(ValueError,match='Invalid proposal'):
        parallel_proposals([('bad',bad),('good',good)],on_result=lambda key,value:saved.append((key,value)))
    assert saved==[('good','valid proposal')]


def test_execution_and_evidence_reviews_run_concurrently_and_fail_closed(monkeypatch):
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    raw = audit_workout_plan(draft, equipment, messages)
    context = plan_review._context(raw, messages, equipment, None, len(messages) - 1)
    context['history'] = {'LIBRARY_0': {'sessions': [{'reps': 8}], 'reference': 'LIBRARY_0'}}
    monkeypatch.setattr(plan_review, '_context', lambda *a: copy.deepcopy(context))
    barrier = threading.Barrier(2)
    scopes = []
    execution_done = threading.Event()
    def review(client, request, **kwargs):
        payload = json.loads(request[-1]['content'])
        scope = 'evidence' if 'history' in payload else 'execution'
        scopes.append(scope)
        assert payload['requirements'] and payload['sourceMessages']
        assert len(payload['draft']['exercises']) == len(context['draft']['exercises'])
        if scope == 'execution':
            assert 'weeklyVolume' not in payload['audit']
            assert all('muscleGroups' not in definition for definition in payload['draft']['libraryDefinitions'].values())
        else:
            assert 'weeklyVolume' not in payload['audit']  # Evidence scopes do not depend on global arithmetic.
            assert any('muscleGroups' in definition for definition in payload['draft']['libraryDefinitions'].values())
        barrier.wait(3)
        if scope == 'evidence':
            assert execution_done.wait(3)
            raise RuntimeError('Evidence review unavailable')
        return '{"findings":[]}', None, None
    monkeypatch.setattr(plan_review, 'chat_call', review)
    result = plan_review.review_draft(None, raw, messages, equipment,
        progress=lambda text: execution_done.set() if text == 'Independent review: execution complete' else None)
    assert sorted(scopes) == ['evidence', 'execution']
    assert not result['passed'] and 'preview' not in result
    assert result['errors'][-1]['code'] == 'review_execution_failed'
    assert 'execution' in result['review']['scopeResults']
    store_tool(messages, 'audit_workout_plan', draft, result)
    messages.append({'role': 'user', 'content': '/continue'})
    retried = []
    def retry(client, request, **kwargs):
        retried.append(json.loads(request[-1]['content']))
        return '{"findings":[]}', None, None
    monkeypatch.setattr(plan_review, 'chat_call', retry)
    approved = plan_review.review_draft(None, raw, messages, equipment)
    assert approved['passed'] and len(retried) == 1 and 'history' in retried[0]


def test_evidence_batches_cover_every_occurrence_once_and_retain_comparison_context(monkeypatch):
    equipment, _, stored, draft = planning_case()
    definition = equipment['exerciseDefinitions'][0]
    equipment['exerciseDefinitions'] = [{**copy.deepcopy(definition), 'id': f'd{index}'} for index in range(6)]
    exercise = draft['workouts'][0]['exercises'][0]
    draft['workouts'][0]['exercises'] = [{**copy.deepcopy(exercise), 'definition_id': f'LIBRARY_{index}',
                                         'numWorkSets': 1} for index in range(6)]
    messages = requirement_messages(stored)
    raw = audit_workout_plan(draft, equipment, messages)
    assert raw['passed']
    context = plan_review._context(raw, messages, equipment, None, len(messages) - 1)
    context['history'] = {f'LIBRARY_{index}': {'sessions': [{'reps': 8}], 'reference': f'LIBRARY_{index}'} for index in range(6)}
    monkeypatch.setattr(plan_review, '_context', lambda *a: copy.deepcopy(context))
    barrier = threading.Barrier(3, timeout=3)
    requests = []
    def review(client, request, **options):
        payload = json.loads(request[-1]['content'])
        requests.append(payload)
        barrier.wait()
        return '{"findings":[]}', None, None
    monkeypatch.setattr(plan_review, 'chat_call', review)
    result = plan_review.review_draft(None, raw, messages, equipment)
    assert result['passed'] and len(requests) == 3
    batches = [payload for payload in requests if payload.get('reviewedExerciseIds')]
    assert len(batches) == 2
    reviewed = [identifier for batch in batches for identifier in batch['reviewedExerciseIds']]
    assert len(reviewed) == len(set(reviewed)) == 6
    assert set(reviewed) == {exercise['id'] for exercise in context['draft']['exercises']}
    assert all(len(batch['draft']['exercises']) == 6 for batch in batches)  # Canonical citation indices are stable.
    for batch in batches:
        selected = set(batch['reviewedExerciseIds'])
        assert set(batch['requiredChecks']) == selected
        assert all(checks == ['history_and_load', 'stop_rule']
                   for checks in batch['requiredChecks'].values())
        assert len({e['libraryDefinitionId'] for e in batch['draft']['exercises'] if e['id'] in selected}) <= 4
        assert set(batch['history']) == {e['libraryDefinitionId'] for e in batch['draft']['exercises'] if e['id'] in selected}
        assert all(('detailsOmitted' in e) == (e['id'] not in selected) for e in batch['draft']['exercises'])
    original = copy.deepcopy(context)
    store_tool(messages, 'audit_workout_plan', draft, result)
    context['draft']['exercises'][0]['placementNotes'] = 'Changed execution cue.'
    requests.clear()
    def recheck(client, request, **options):
        requests.append(json.loads(request[-1]['content']))
        return '{"findings":[]}', None, None
    monkeypatch.setattr(plan_review, 'chat_call', recheck)
    revised = plan_review.review_draft(None, raw, messages, equipment)
    assert revised['passed'] and len(requests) == 2  # Whole-week execution + affected evidence batch only.
    assert sum('history' in payload for payload in requests) == 1
    assert all(e == original['draft']['exercises'][i] for i,e in enumerate(context['draft']['exercises']) if i)


def test_numerical_draft_is_checkpointed_before_an_interrupted_review(monkeypatch):
    from workout_generator_pkg.planner_context import pending_reaudit
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    initial = audit_workout_plan(draft, equipment, messages)
    store_tool(messages, 'audit_workout_plan', draft, initial)
    proposal = {'requirementsId': stored['requirementsId'], 'baseDraftId': initial['currentDraftId'], 'patch': [
        {'op': 'replace', 'path': '/workouts/0/exercises/0/numWorkSets', 'value': 6}]}
    def cancel(*args, **kwargs):
        raise KeyboardInterrupt
    monkeypatch.setattr(shell, 'review_draft', cancel)
    saved = []
    with pytest.raises(KeyboardInterrupt):
        shell.handle_function_call(None, messages, 'audit_workout_plan', proposal, equipment, checkpoint=saved.append)
    assert len(saved) == 1 and saved[0]['submittedDraft']['workouts'][0]['exercises'][0]['numWorkSets'] == 6
    assert not saved[0]['passed'] and 'preview' not in saved[0] and 'planIndex' not in saved[0]
    store_tool(messages, 'audit_workout_plan', proposal, saved[0])
    state = request_planning_state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert pending_reaudit(state, '/continue') == {'requirementsId': stored['requirementsId'], 'baseDraftId': saved[0]['currentDraftId'], 'patch': []}


def test_interrupted_review_keeps_finished_scopes_without_approving_incomplete_review(monkeypatch):
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    raw = audit_workout_plan(draft, equipment, messages)
    context = plan_review._context(raw, messages, equipment, None, len(messages) - 1)
    context['history'] = {'LIBRARY_0': {'sessions': [{'reps': 8}], 'reference': 'LIBRARY_0'}}
    monkeypatch.setattr(plan_review, '_context', lambda *a: copy.deepcopy(context))
    completed = threading.Event()
    def review(client, request, **options):
        if 'history' in json.loads(request[-1]['content']):
            assert completed.wait(3)
            raise KeyboardInterrupt
        return '{"findings":[]}', None, None
    monkeypatch.setattr(plan_review, 'chat_call', review)
    saved = []
    def checkpoint(payload):
        saved.append(payload)
        completed.set()
    with pytest.raises(KeyboardInterrupt):
        plan_review.review_draft(None, raw, messages, equipment, on_checkpoint=checkpoint)
    assert not saved[-1]['passed'] and saved[-1]['review']['inProgress']
    with pytest.raises(ValueError, match='missing or stale'):
        plan_review._require_review_receipt({**raw, 'review': saved[-1]['review']}, messages, equipment)
    store_tool(messages, 'audit_workout_plan', draft, saved[-1])
    messages.append({'role': 'user', 'content': '/continue'})
    requests = []
    monkeypatch.setattr(plan_review, 'chat_call', lambda client, request, **options: (
        requests.append(json.loads(request[-1]['content'])) or '{"findings":[]}', None, None))
    resumed = plan_review.review_draft(None, raw, messages, equipment)
    assert resumed['passed'] and len(requests) == 1 and 'history' in requests[0]


def test_shell_prepares_parallel_sessions_and_audits_combined_proposal_without_extra_planner_turn(monkeypatch, tmp_path):
    from test_workout_generator_conversation_sessions import make_shell_deps, FakeToolCall, FakeFunction
    from workout_generator_pkg.conversation_store import load_active_conversation_record
    equipment, messages, prepared, exercises = week_case()
    stored = json.loads(next(m['content'] for m in messages if m.get('tool_call_id') == 'requirements'))
    path = tmp_path / 'library.json'
    path.write_text(json.dumps(equipment), encoding='utf-8')
    arguments = {key: prepared[key] for key in ('requirementsId', 'baseDraftId', 'name', 'sessions')}
    def tool(name, args, key):
        return None, [FakeToolCall(key, 'function', FakeFunction(name, json.dumps(args)))]
    deps = make_shell_deps(tmp_path, chat_results=[
        tool('set_workout_requirements', stored['requirements'], 'requirements'),
        tool('search_exercise_library', {'queries': ['Push-Up']}, 'search'),
        tool('prepare_workout_sessions', arguments, 'prepare')], generation_results=[], generation_calls=[])
    chat = deps.chat_call_with_loading
    requests = []
    def capture(client, messages, tools, logger, **options):
        state = request_planning_state(messages)
        requests.append(state.get('constructionTask', {}).get('stage'))
        result = chat(client, messages, tools, logger, **options)
        for call in result[1] or []:
            if call.function.name == 'prepare_workout_sessions':
                assert 'prepare_workout_sessions' in [tool['function']['name'] for tool in tools]
                args = json.loads(call.function.arguments)
                args['requirementsId'] = state['requirementsId']
                call.function.arguments = json.dumps(args)
        return result
    deps.chat_call_with_loading = capture
    def worker(client, request, **kwargs):
        selection = json.loads(request[-1]['content'])['session']
        return json.dumps({**{key: value for key, value in selection.items() if key not in ('definition_ids', 'structure', 'coverageAssignments')},
                           'exercises': exercises}), None, None
    monkeypatch.setattr(session_drafting, 'chat_call', worker)
    monkeypatch.setattr('sys.argv', ['workout_generator.py', '--exercise-library-file', str(path)])
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test-key')
    inputs = iter(['Plan three sessions, 5-6 chest sets each and 15-18 weekly.', 'CONFIRM REQUIREMENTS', '/exit'])
    monkeypatch.setattr('builtins.input', lambda prompt='': next(inputs))
    shell.main(deps=deps)
    saved = load_active_conversation_record(str(tmp_path))['messages']
    audits = [json.loads(m['content']) for m in saved if m.get('role') == 'tool' and '"auditVersion"' in m.get('content', '')]
    assert len(requests) == 3
    assert len(audits) == 1 and audits[0]['passed']
    assert len(audits[0]['submittedDraft']['workouts']) == 3
