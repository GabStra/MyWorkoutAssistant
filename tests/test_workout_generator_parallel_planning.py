import copy
import hashlib
import json
import threading
from types import SimpleNamespace

import pytest

from workout_generator_pkg import session_drafting, plan_review, interactive_shell as shell
from workout_generator_pkg.planner_context import request_planning_state, pending_evidence
from workout_generator_pkg.planning_tools import PlanningInputError, audit_workout_plan, set_workout_requirements
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


def week_case(execution_rules=None, occurrences=1, coverage=None, working_set_rir=None):
    equipment, requirements, _, draft = planning_case()
    requirements['sessionsPerWeek'] = 3
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 15, 'maximum': 18}
    if working_set_rir is not None:
        requirements['workingSetRIR'] = working_set_rir
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


def test_development_intent_opens_one_bounded_menu_review_without_allocation_diagnostics():
    from workout_generator_pkg.planner_context import construction_tool_failure, request_planning_state
    coverage = [{'key': 'upper_push', 'description': 'Upper push development',
                 'scope': 'weekly', 'intent': 'development'}]
    equipment, messages, prepared, _ = week_case(coverage=coverage)
    prepared['setAllocation']['allocationDiagnostics'] = []
    messages[-1]['content'] = json.dumps(prepared)
    allocation = prepared['setAllocation']
    assert allocation['feasible']
    assert not allocation['allocationDiagnostics']

    state = request_planning_state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert state['constructionTask']['reviewAllocationBeforeDrafting']
    assert 'exerciseDemandEvidence' in state and 'volumeCreditCoupling' in state
    assert construction_tool_failure('search_exercise_library', {}, state) is None
    assert construction_tool_failure('prepare_workout_sessions', {}, state) is None

    store_tool(messages, 'prepare_workout_sessions', {}, prepared)
    revised = request_planning_state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert revised['constructionTask']['stage'] == 'draft_sessions'
    assert not revised['constructionTask']['reviewAllocationBeforeDrafting']


def test_accepted_development_menu_resumes_exact_preparation_and_new_instruction_supersedes_it():
    from workout_generator_pkg.user_interaction import answer_question

    coverage = [{'key': 'upper_push', 'description': 'Upper push development',
                 'scope': 'weekly', 'intent': 'development'}]
    equipment, messages, prepared, _ = week_case(coverage=coverage)
    question = {'kind': 'clarification', 'question': 'Revise this menu or accept the limits?',
                'options': ['Revise the menu.', 'Accept the disclosed limits.']}
    evidence = {'status': 'proven_upper_bounds', 'roleUpperBounds': {'upper_push': 3}}
    store_tool(messages, 'draft_workout_sessions', {'preparationId': prepared['preparationId']}, {
        'preparationId': prepared['preparationId'], 'passed': False,
        'menuReview': {'evidence': evidence, 'question': question, 'accepted': False},
        'userQuestion': question, 'errors': []})
    messages.extend([
        {'role': 'assistant', 'content': question['question']},
        {'role': 'user', 'content': answer_question(question, '2')},
    ])

    state = request_planning_state(shell._messages_for_api(messages, True, provided_equipment=equipment))

    assert state['acceptedMenuPreparationId'] == prepared['preparationId']
    assert state['parallelPreparation']['preparationId'] == prepared['preparationId']
    assert state['parallelPreparation']['sourceWorkingSetBudget'] == prepared['sourceWorkingSetBudget']
    assert state['constructionTask']['stage'] == 'draft_sessions'
    assert state['constructionTask']['reviewAllocationBeforeDrafting'] is False
    assert state['newInstructionPending'] is False

    messages.append({'role': 'user', 'content': 'Change the selected menu before drafting.'})
    superseded = request_planning_state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert superseded.get('acceptedMenuPreparationId') is None
    assert superseded['newInstructionPending'] is True
    assert superseded['constructionTask']['stage'] in ('discover_movements', 'choose_movements')
    assert superseded.get('parallelPreparation') is None


def test_explicit_loaded_setup_is_rejected_before_cache_or_set_allocation(monkeypatch):
    equipment, messages, prepared, _ = week_case()
    call = next(call for message in messages for call in message.get('tool_calls', [])
        if call['function']['name'] == 'prepare_workout_sessions')
    arguments = json.loads(call['function']['arguments'])
    history = SimpleNamespace(fingerprint=None, evidence=lambda args, _equipment: {
        'exercises': [{'reference': reference, 'loadSuitabilityConcerns': [
            {'code': 'recorded_loaded_setup_requires_reassessment'}]}
            for reference in args['definition_ids']]})
    monkeypatch.setattr(session_drafting, '_cached_preparation',
        lambda *args, **kwargs: pytest.fail('History must be checked before cached preparation reuse.'))
    monkeypatch.setattr('workout_generator_pkg.allocation.allocate_prepared_sets',
        lambda *args, **kwargs: pytest.fail('Explicit setup concerns must stop before allocation.'))

    with pytest.raises(Exception) as raised:
        session_drafting.prepare_workout_sessions(arguments, messages, equipment, training_history=history)

    error = raised.value
    assert error.code == 'training_load_suitability_unresolved'
    assert error.errors[0]['code'] == 'prepared_design_finding'
    assert error.errors[0]['concerns'][0]['code'] == 'recorded_loaded_setup_requires_reassessment'
    assert error.errors[0]['permittedPaths']['exact'] == ['/sessions/0/exercises/0']
    assert not any('minReps' in path or 'maxReps' in path for path in error.errors[0]['permittedPaths']['exact'])
    store_tool(messages, 'prepare_workout_sessions', arguments, {
        'preparationArguments': error.preparation_arguments, 'errors': error.errors})
    task = session_drafting.preparation_repair_task(messages, equipment)
    assert task and task['needsAlternatives']
    assert task['blockRepair']['sessions']['SESSION_0']['editableOccurrences'] == ['/sessions/0/exercises/0']
    assert task['errors'][0]['sourceCode'] == 'training_load_suitability_unresolved'
    with pytest.raises(PlanningInputError) as rejected:
        session_drafting.resolve_preparation_patch({'basePreparationId': task['basePreparationId'],
            'sessionBlocks': [{'sessionReference': 'SESSION_0', 'replacements': [{
                'replaces': '/sessions/0/exercises/0', 'definition_id': 'LIBRARY_0',
                'satisfiesCoverage': [], 'numWorkSets': 99}]}]}, messages, equipment)
    assert rejected.value.code == 'preparation_patch_rejected'
    assert rejected.value.preparation_repair_task['errors'][0]['sourceCode'] == 'training_load_suitability_unresolved'


def test_blocked_supplemental_setup_is_removed_and_invalidates_cached_menu(monkeypatch):
    equipment, messages, cached, _ = week_case()
    supplemental = copy.deepcopy(equipment['exerciseDefinitions'][0])
    supplemental.update(id='zz_assisted_push_up', name='Assisted Push-Up')
    equipment['exerciseDefinitions'].append(supplemental)
    arguments = next(json.loads(call['function']['arguments'])
        for message in messages for call in message.get('tool_calls', [])
        if call['function']['name'] == 'prepare_workout_sessions')
    monkeypatch.setattr(session_drafting, '_reviewed_recipe_candidate_references',
        lambda *_args, **_kwargs: ['LIBRARY_1'])
    setup_concern = {'code': 'recorded_loaded_setup_requires_reassessment'}
    history = SimpleNamespace(fingerprint=None, evidence=lambda args, _equipment: {
        'exercises': [{'reference': reference, 'loadSuitabilityConcerns': [setup_concern]}
            for reference in args['definition_ids'] if reference == 'LIBRARY_1']})

    saved = copy.deepcopy(cached)
    saved['recipeSessions'] = session_drafting._add_reviewed_recipe_candidates(
        saved['recipeSessions'], ['LIBRARY_1'])
    selected = session_drafting.get_exercise_candidates({'definition_ids': ['LIBRARY_1']}, equipment, messages)
    saved['candidates'].update({item['id']: item for item in selected['exercises']})
    saved['libraryFingerprint'] = session_drafting.library_fingerprint(equipment)
    saved['sourceBudgetAuthority'] = session_drafting._preparation_authority(
        messages, arguments, equipment, None)
    messages[-1]['content'] = json.dumps(saved)

    cache_results = []

    def capture_cache(*args, **kwargs):
        assert any(item['definition_id'] == 'LIBRARY_1'
            for day in saved['recipeSessions'] for item in day['exercises'])
        cache_results.append(copy.deepcopy(saved))
        return copy.deepcopy(saved)

    monkeypatch.setattr(session_drafting, '_cached_preparation', capture_cache)
    rebuilt = session_drafting.prepare_workout_sessions(arguments, messages, equipment, training_history=history)

    assert len(cache_results) == 1
    assert any(item['definition_id'] == 'LIBRARY_1'
        for day in cache_results[0]['recipeSessions'] for item in day['exercises'])
    assert rebuilt['preparationId'] != cached['preparationId']
    assert all([item['definition_id'] for item in day['exercises']] == ['LIBRARY_0']
        for day in rebuilt['recipeSessions'])
    assert all([item['definition_id'] for item in day['exercises']] == ['LIBRARY_0']
        for day in rebuilt['sessions'])
    assert 'LIBRARY_0' in {item['definition_id'] for day in arguments['sessions'] for item in day['exercises']}


def test_saved_preparation_rechecks_setup_before_qualification_or_worker_reuse(monkeypatch):
    equipment, messages, prepared, _ = week_case()
    state = request_planning_state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    history = SimpleNamespace(fingerprint=None, evidence=lambda args, _equipment: {
        'exercises': [{'reference': reference, 'loadSuitabilityConcerns': [
            {'code': 'recorded_loaded_setup_requires_reassessment'}]}
            for reference in args['definition_ids']]})
    monkeypatch.setattr('workout_generator_pkg.recipe_contracts.qualify_recipe_contracts',
        lambda *args, **kwargs: pytest.fail('Saved preparation must be rechecked before qualification.'))
    monkeypatch.setattr(session_drafting, 'chat_call',
        lambda *args, **kwargs: pytest.fail('Saved preparation must be rechecked before worker drafting.'))

    result = session_drafting.draft_workout_sessions(None,
        {'preparationId': prepared['preparationId']}, messages, equipment, state,
        training_history=history)

    assert result['preparationErrors']
    assert all(error['code'] == 'prepared_design_finding' for error in result['preparationErrors'])
    assert not result.get('recipeQualification')
    assert not result.get('workerResults')


def test_inclusion_only_coverage_does_not_open_additional_menu_review():
    coverage = [{'key': 'upper_push', 'description': 'Include upper push',
                 'scope': 'weekly', 'intent': 'inclusion'}]
    equipment, messages, prepared, _ = week_case(coverage=coverage)
    prepared['setAllocation']['allocationDiagnostics'] = []
    messages[-1]['content'] = json.dumps(prepared)
    assert prepared['setAllocation']['feasible']
    assert not prepared['setAllocation']['allocationDiagnostics']

    state = request_planning_state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert not state['constructionTask']['reviewAllocationBeforeDrafting']


def test_joint_week_is_solved_before_any_semantic_review(monkeypatch):
    from workout_generator_pkg import joint_planning

    equipment, messages, prepared, exercises = week_case()
    state = request_planning_state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    monkeypatch.setattr(plan_review, 'review_week_structure', lambda *a, **k: pytest.fail('Review must see complete prescriptions'))
    solve_week = joint_planning.solve_prescribed_week
    observed_calibration_modes = []
    def solve_with_recorded_calibration(*args, **kwargs):
        observed_calibration_modes.append(kwargs['allow_educated_load_guesses'])
        return solve_week(*args, **kwargs)
    monkeypatch.setattr(joint_planning, 'solve_prescribed_week', solve_with_recorded_calibration)
    def draft(client, request, **options):
        return json.dumps({'exercises': copy.deepcopy(exercises)}), None, None
    monkeypatch.setattr(session_drafting, 'chat_call', draft)
    result = session_drafting.draft_workout_sessions(None, {'preparationId': prepared['preparationId']}, messages,
        equipment, state, allow_educated_load_guesses=False)
    assert result['jointPlanning']['feasible']
    assert result['jointPlanning']['preserveSourceSelection'] is False
    assert 'proposedSubmission' in result
    assert observed_calibration_modes == [False]


@pytest.mark.parametrize(('prescription_hash_matches', 'refresh_requirements_id'), [
    (True, False), (False, False), (True, True), (False, True),
])
@pytest.mark.parametrize('preserve_selection', [False, True])
def test_unchanged_audit_rebinds_only_the_matching_joint_receipt(
        monkeypatch, prescription_hash_matches, refresh_requirements_id, preserve_selection):
    from workout_generator_pkg import allocation, joint_planning, planning_tools, requirement_accounting
    from workout_generator_pkg.restriction_policy import effective_restrictions

    equipment, messages, prepared, _ = week_case()
    _, stored = planning_tools._latest_result(messages, 'set_workout_requirements')
    submitted = {'requirementsId': prepared['requirementsId'], 'name': prepared['name'],
        'workouts': copy.deepcopy(prepared['sessions'])}
    owner = {'passed': False, 'requirementsId': prepared['requirementsId'],
        'currentDraftId': 'REVISION_0', 'submittedDraft': submitted, 'audit': {'issues': []},
        'review': {'passed': False, 'failure': {'code': 'review_execution_failed'}},
        'libraryFingerprint': planning_tools.library_fingerprint(equipment), 'historyFingerprint': None,
        'resolvedDecisions': {}, 'automaticAllocation': {}}
    store_tool(messages, 'audit_workout_plan', submitted, owner)

    source_budget = {'source': 'test-preparation', 'variableWeeklyWorkingSets': 15,
        'preparationId': prepared['preparationId']}
    restrictions = effective_restrictions(stored, equipment)
    receipt = {
        'feasible': True, 'status': 'optimal',
        'selectionPolicyVersion': joint_planning.SELECTION_POLICY_VERSION,
        'preserveSourceSelection': preserve_selection,
        'objectivePolicy': ('approved' if stored['requirements'].get('objectiveOrder') is not None
                            else 'preserve_candidate_only'),
        'approvedObjectiveOrder': stored['requirements'].get('objectiveOrder'),
        'objectiveInputFingerprint': joint_planning.joint_objective_input_fingerprint(
            submitted['workouts'], stored['requirements'], equipment, None, messages,
            restriction_policy=restrictions, allow_educated_load_guesses=False,
            preserve_source_selection=preserve_selection, source_working_set_budget=source_budget),
        'objectiveProgress': [], 'objectiveOrderUsed': [],
        'solvedPrescriptionHash': (joint_planning.prescription_fingerprint(submitted['workouts'])
            if prescription_hash_matches else 'stale-solved-prescription'),
        'sourceWorkingSetBudget': source_budget,
        'priorityExecution': {'approvedPriorities': [{'priority': 'development_emphasis',
            'owner': 'joint_solver', 'status': 'optimal'}]},
    }
    owner['automaticAllocation'] = receipt
    messages[-1]['content'] = json.dumps(owner)

    refreshed_id = prepared['requirementsId'] + '_SOURCE_REFRESH' if refresh_requirements_id else prepared['requirementsId']
    current_submitted = copy.deepcopy(submitted)
    current_submitted['requirementsId'] = refreshed_id
    for index, workout in enumerate(current_submitted['workouts']):
        workout.update(name=f'Full Body {index + 1}', description='Full body')
    direct_reuse = allocation.reusable_joint_receipt(owner, refreshed_id, current_submitted['workouts'],
        stored['requirements'], equipment, messages, restriction_policy=restrictions,
        allow_educated_load_guesses=False, preserve_source_selection=preserve_selection,
        source_working_set_budget=source_budget)
    assert direct_reuse is not None
    checked = allocation.reusable_audited_joint_receipt(owner, refreshed_id,
        current_submitted['workouts'], stored['requirements'], equipment, messages,
        restriction_policy=restrictions, allow_educated_load_guesses=False)
    assert (checked is not None) is prescription_hash_matches
    assert allocation.reusable_audited_joint_receipt(owner, refreshed_id,
        current_submitted['workouts'], stored['requirements'], equipment, messages,
        restriction_policy=restrictions, allow_educated_load_guesses=False,
        source_working_set_budget={**source_budget, 'variableWeeklyWorkingSets': 14}) is None

    audited = {'passed': True, 'requirementsId': refreshed_id,
        'currentDraftId': 'REVISION_0', 'draftId': 'AUDIT_TEST', 'submittedDraft': current_submitted,
        'audit': {'issues': []}, 'errors': [], 'auditVersion': planning_tools.AUDIT_VERSION,
        'libraryFingerprint': planning_tools.library_fingerprint(equipment),
        'historyFingerprint': None, 'resolvedDecisions': {}, 'allowEducatedLoadGuesses': False}
    allocated = allocation.auto_allocate_workout(audited, equipment, messages,
        allow_educated_load_guesses=False)
    if prescription_hash_matches:
        assert allocated['coordinatedJointPlanning']['reusedForValidatedCandidate'] is True
    else:
        assert 'coordinatedJointPlanning' not in allocated

    monkeypatch.setattr(shell, 'audit_workout_plan', lambda *args, **kwargs: copy.deepcopy(audited))
    monkeypatch.setattr('workout_generator_pkg.repair_execution.solve_repair_candidate',
        lambda *args, **kwargs: pytest.fail('A label-only edit must reuse the exact prescription proof.'))
    observed = {}
    def review(_client, result, *_args, **_kwargs):
        observed['receipt'] = copy.deepcopy(result.get('coordinatedJointPlanning'))
        return result
    monkeypatch.setattr(shell, 'review_draft', review)
    monkeypatch.setattr(shell, 'auto_allocate_workout', lambda result, *args, **kwargs: result)
    monkeypatch.setattr(requirement_accounting, 'outcome', lambda _result: {})

    response = shell.handle_function_call(None, messages, 'audit_workout_plan', current_submitted,
        provided_equipment=equipment, allow_educated_load_guesses=False,
        deps=SimpleNamespace(execute_workout_generation=None))
    result = json.loads(response['result'])

    assert result['passed'] is True
    if prescription_hash_matches:
        assert result['coordinatedJointPlanning']['reusedForValidatedCandidate'] is True
        assert result['coordinatedJointPlanning']['sourceWorkingSetBudget'] == receipt['sourceWorkingSetBudget']
        assert result['coordinatedJointPlanning']['priorityExecution'] == receipt['priorityExecution']
    else:
        assert 'coordinatedJointPlanning' not in result


def test_auto_allocator_carries_coordinated_proof_across_source_refresh_without_solving(monkeypatch):
    from workout_generator_pkg import allocation, joint_planning
    from workout_generator_pkg.restriction_policy import effective_restrictions

    equipment, requirements, _, template = planning_case()
    requirements.update(sessionsPerWeek=3, objectiveOrder=['duration_balance'],
        durationBalanceToleranceSeconds=300)
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 15, 'maximum': 18}
    stored = set_workout_requirements(requirements,
        [{'role': 'user', 'content': 'Three sessions with balanced estimated duration.'}], equipment)
    messages = requirement_messages(stored)
    workouts = []
    for index in range(3):
        day = copy.deepcopy(template['workouts'][0])
        day.update(name=f'Session {index + 1}', trainingDays=[index * 2])
        workouts.append(day)
    submitted = {'requirementsId': stored['requirementsId'], 'name': 'Program', 'workouts': workouts}
    audit = audit_workout_plan(submitted, equipment, messages)
    assert audit['passed']
    submitted = audit['submittedDraft']
    workouts = submitted['workouts']

    restrictions = effective_restrictions(stored, equipment)
    receipt = {
        'feasible': True, 'status': 'optimal',
        'selectionPolicyVersion': joint_planning.SELECTION_POLICY_VERSION,
        'objectivePolicy': 'approved', 'approvedObjectiveOrder': ['duration_balance'],
        'preserveSourceSelection': False,
        'sourceWorkingSetBudget': joint_planning._source_working_set_budget_identity(workouts, None),
        'objectiveInputFingerprint': joint_planning.joint_objective_input_fingerprint(
            workouts, stored['requirements'], equipment, messages=messages,
            restriction_policy=restrictions, preserve_source_selection=False),
        'solvedPrescriptionHash': joint_planning.prescription_fingerprint(workouts),
    }
    prior = {**audit, 'coordinatedJointPlanning': receipt}
    store_tool(messages, 'audit_workout_plan', submitted, prior)
    assert allocation.reusable_joint_receipt(prior, stored['requirementsId'], workouts,
        stored['requirements'], equipment, messages, restriction_policy=restrictions) is not None

    # Force the allocator down the duration-balance reuse path while keeping the
    # proof bound to the unchanged, production-audited prescription.
    current = copy.deepcopy(audit)
    for day, seconds in zip(current['audit']['workouts'], (300, 700, 800), strict=True):
        day['estimatedSeconds'] = seconds
    monkeypatch.setattr(joint_planning, 'solve_prescribed_week',
        lambda *_args, **_kwargs: pytest.fail('A matching saved proof must prevent another solve.'))

    first_reaudit = allocation.auto_allocate_workout(current, equipment, messages)
    assert first_reaudit['coordinatedJointPlanning']['reusedForValidatedCandidate'] is True
    assert first_reaudit['coordinatedJointPlanning']['objectiveInputFingerprint'] == receipt['objectiveInputFingerprint']

    # A user source correction and a refreshed requirements ID leave the exact
    # structured solver domain unchanged. The proof is now stored under the
    # coordinated-review receipt key, as it is in the retained native run.
    messages.append({'role': 'user', 'content': 'Correct the source concern; keep the candidate and requirements unchanged.'})
    refreshed = copy.deepcopy(stored)
    refreshed['requirementsId'] = 'REQUIREMENTS_REFRESHED_SOURCE_ONLY'
    refreshed['baseRequirementsId'] = stored['requirementsId']
    store_tool(messages, 'set_workout_requirements', {'baseRequirementsId': stored['requirementsId'], 'updates': {}}, refreshed)
    store_tool(messages, 'audit_workout_plan', submitted, first_reaudit)
    refreshed_audit = copy.deepcopy(current)
    refreshed_audit['requirementsId'] = refreshed['requirementsId']
    refreshed_audit['submittedDraft']['requirementsId'] = refreshed['requirementsId']

    second_reaudit = allocation.auto_allocate_workout(refreshed_audit, equipment, messages)
    assert second_reaudit['coordinatedJointPlanning']['reusedForValidatedCandidate'] is True
    assert second_reaudit['coordinatedJointPlanning']['solvedPrescriptionHash'] == receipt['solvedPrescriptionHash']


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
    from workout_generator_pkg.planner_context import request_planning_state

    equipment, messages, prepared, _ = week_case(coverage=[{
        'key': 'press', 'description': 'Pressing movement', 'scope': 'weekly'}])
    history = SimpleNamespace(fingerprint='current-history', context=lambda: {})
    prepared['historyFingerprint'] = history.fingerprint
    messages[-1]['content'] = json.dumps(prepared)
    monkeypatch.setattr('workout_generator_pkg.recipe_contracts.qualify_recipe_contracts',
        lambda *a, **k: {'contracts': [{'definition_id': 'LIBRARY_0', 'satisfiesCoverage': [],
            'progressionPlan': {'kind': 'reps', 'nextDefinitionId': None, 'nextDefinitionName': None}}]})
    monkeypatch.setattr(session_drafting, 'chat_call', lambda *a, **k: pytest.fail('Missing coverage must stop before workers'))
    result = session_drafting.draft_workout_sessions(None, {'preparationId': prepared['preparationId']},
        messages, equipment, {'historyFingerprint': history.fingerprint}, training_history=history)
    assert result['preparationErrors'] and not result.get('executionFailure')
    assert result['historyFingerprint'] == history.fingerprint
    store_tool(messages, 'draft_workout_sessions', {'preparationId': prepared['preparationId']}, result)
    api_messages = shell._messages_for_api(messages, True, history, equipment)
    state = request_planning_state(api_messages)
    assert state['preparationRepairTask']['needsAlternatives']
    repair_tools = shell._preparation_repair_tools(state['preparationRepairTask'])
    assert [tool['function']['name'] for tool in repair_tools] == ['prepare_workout_sessions']


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
    assert len(result['excludedWarmupRecipes']) == 3
    for exclusion in result['excludedWarmupRecipes']:
        assert exclusion['definitionId'] == 'LIBRARY_0'
        assert exclusion['reasonCode'] == 'native_warmup_unavailable'
        assert exclusion['nativeWarmupSupported'] is False
        assert exclusion['configurationFacts'] == {
            'exerciseType': 'BODY_WEIGHT', 'equipmentId': None,
            'equipmentAvailable': False, 'bodyWeightPercentagePresent': True}
        assert exclusion['requiredWarmupCoverageKeys'] == ['chest']
        assert 'support check returns false' in exclusion['reason']
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


def test_open_ended_weekly_target_projects_without_inventing_shared_session_ceiling():
    equipment, requirements, _, draft = planning_case()
    requirements['sessionsPerWeek'] = 3
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 15, 'maximum': None}
    requirements['auditTargets']['perSessionEffectiveSets']['chest'] = {'minimum': 5, 'maximum': None}
    stored = set_workout_requirements(requirements, [{'role': 'user', 'content': 'Three sessions, at least 15 chest sets weekly.'}], equipment)
    messages = requirement_messages(stored)
    base = {key: value for key, value in draft['workouts'][0].items() if key != 'exercises'}
    arguments = {'requirementsId': stored['requirementsId'], 'baseDraftId': None, 'name': 'Program',
        'sessions': [{**base, 'name': f'Session {index}', 'trainingDays': [index * 2],
            'exercises': [{'definition_id': 'LIBRARY_0', 'numWorkSets': 5, 'superset': None}]}
            for index in range(3)]}

    prepared = session_drafting.prepare_workout_sessions(arguments, messages, equipment)
    assert prepared['sharedSessionTargets']['chest'] == {'minimum': 5, 'maximum': None}


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
        return json.dumps({'name':'Changed','description':'Hip thrust focus','trainingDays':[6],
            'timesCompletedInAWeek':7,'exercises':exercises}),None,None
    monkeypatch.setattr(session_drafting,'chat_call',respond)
    result=session_drafting.draft_workout_sessions(None,{'preparationId':prepared['preparationId']},messages,equipment,state)
    assert len(calls)==3
    for expected,actual in zip(prepared['sessions'],result['proposedSubmission']['workouts']):
        assert actual['name']==expected['name'] and actual['trainingDays']==expected['trainingDays']
        assert actual['description'] == 'Workout'
        assert actual['exercises'][0]['satisfiesCoverage']==['chest']
        assert actual['exercises'][0]['numWorkSets']==exercises[0]['numWorkSets']


def test_generated_full_body_description_comes_from_approved_session_roles():
    from workout_generator_pkg.session_drafting import canonicalize_generated_session_descriptions

    requirements = {'requiredCoverage': [
        {'key': role, 'scope': 'eachSession'} for role in
        ('knee_dominant', 'posterior_chain', 'upper_push', 'upper_pull')]}
    workouts = [{'name': 'Full Body A', 'description': 'Hip thrust focus'}]

    assert canonicalize_generated_session_descriptions(workouts, requirements) == [
        {'name': 'Full Body A', 'description': 'Full body'}]


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
    assert len(repairs)==1 and repairs[0]['permittedPaths']==['/workouts/0/exercises/0']
    assert result['proposedSubmission']['workouts'][1]['exercises'][0]['definition_id']=='LIBRARY_0'


@pytest.mark.parametrize(('complete_union', 'fail_scoped_recovery_once'), [
    (True, False), (False, False), (False, True),
])
def test_worker_subset_is_bound_by_reference_and_pool_completeness_is_checked_before_solver(
        monkeypatch, complete_union, fail_scoped_recovery_once):
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
    second = {**source, 'definition_id': 'LIBRARY_1'}
    template = copy.deepcopy(draft['workouts'][0]['exercises'][0])
    template['repDurationSeconds'] = 3
    sessions = [{'name': f'Day {index}', 'description': 'Pressing', 'timesCompletedInAWeek': 1,
                 'trainingDays': [index * 3], 'exercises': [copy.deepcopy(source), copy.deepcopy(second)]}
                for index in range(2)]
    arguments = {'requirementsId': stored['requirementsId'], 'baseDraftId': None,
                 'name': 'Program', 'sessions': sessions}
    prepared = session_drafting.prepare_workout_sessions(arguments, messages, equipment)
    store_tool(messages, 'prepare_workout_sessions', arguments, prepared)
    state = request_planning_state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    calls, repairs, drafted_recipe_refs, drafted_tasks = [], [], [], []
    recovery_failures_remaining = [int(fail_scoped_recovery_once)]
    solver_calls = []
    solver = joint_planning.solve_prescribed_week

    def solve(*args, **kwargs):
        solver_calls.append(True)
        return solver(*args, **kwargs)

    monkeypatch.setattr(joint_planning, 'solve_prescribed_week', solve)

    def draft_session(_, request, **__):
        payload = json.loads(request[-1]['content'])
        if 'permittedPaths' in payload:
            repairs.append(payload)
            raise AssertionError(json.dumps(payload.get('errors'), indent=2))
        selection = payload['session']
        calls.append(selection['name'])
        recipe_refs = [item['definition_id'] for item in selection['exercises']]
        drafted_recipe_refs.append(recipe_refs)
        drafted_tasks.append((payload['sessionReference'], recipe_refs))
        if (fail_scoped_recovery_once and payload['sessionReference'] == 'SESSION_0'
                and recipe_refs == ['LIBRARY_1'] and recovery_failures_remaining[0]):
            recovery_failures_remaining[0] -= 1
            raise RuntimeError('controlled first scoped-recovery failure')
        structures = (selection['exercises'][:1] if payload['sessionReference'] == 'SESSION_0'
                      or not complete_union else selection['exercises'])
        values = []
        for structure in structures:
            exercise = copy.deepcopy(template)
            for field in ('numWorkSets', 'allocationBounds', 'satisfiesCoverage', 'setupSeconds',
                          'intraSetRestInSeconds', 'generateWarmUpSets'):
                exercise.pop(field, None)
            exercise['definition_id'] = structure['definition_id']
            exercise['superset'] = None
            values.append(exercise)
        return json.dumps({'name': selection['name'], 'description': selection['description'],
            'timesCompletedInAWeek': selection['timesCompletedInAWeek'],
            'trainingDays': selection['trainingDays'], 'exercises': values}), None, None

    monkeypatch.setattr(session_drafting, 'chat_call', draft_session)
    checkpoints = []
    result = session_drafting.draft_workout_sessions(None, {'preparationId': prepared['preparationId']},
        messages, equipment, state, checkpoint=lambda value: checkpoints.append(copy.deepcopy(value)))

    assert not repairs
    if fail_scoped_recovery_once:
        assert not complete_union
        assert result.get('executionFailure')
        assert result['errors'][0]['code'] == 'recipe_pool_incomplete'
        assert not solver_calls
        assert drafted_tasks == [
            ('SESSION_0', ['LIBRARY_0', 'LIBRARY_1']),
            ('SESSION_1', ['LIBRARY_0', 'LIBRARY_1']),
            ('SESSION_0', ['LIBRARY_1']),
        ]
        retained_workers = copy.deepcopy(result['workerResults'])
        store_tool(messages, 'draft_workout_sessions', {'preparationId': prepared['preparationId']}, result)
        messages.append({'role': 'user', 'content': '/continue'})
        resumed_state = request_planning_state(shell._messages_for_api(
            messages, True, provided_equipment=equipment))
        result = session_drafting.draft_workout_sessions(None,
            {'preparationId': prepared['preparationId']}, messages, equipment, resumed_state,
            checkpoint=lambda value: checkpoints.append(copy.deepcopy(value)))
        assert drafted_tasks[-1] == ('SESSION_0', ['LIBRARY_1'])
        assert drafted_tasks.count(('SESSION_0', ['LIBRARY_0', 'LIBRARY_1'])) == 1
        assert drafted_tasks.count(('SESSION_1', ['LIBRARY_0', 'LIBRARY_1'])) == 1
        assert result['workerResults']['1'] == retained_workers['1']
        assert result['workerResults']['0']['exercises'][0] == retained_workers['0']['exercises'][0]
        assert [item['definition_id'] for item in result['workerResults']['0']['exercises']] == [
            'LIBRARY_0', 'LIBRARY_1']
        assert solver_calls
        assert 'proposedSubmission' in result, result
    else:
        assert solver_calls and all(solver_calls)
        assert 'proposedSubmission' in result, result
    if fail_scoped_recovery_once:
        return
    if not complete_union and not fail_scoped_recovery_once:
        assert len(calls) == 3 and drafted_recipe_refs[-1] == ['LIBRARY_1']
        assert [item['definition_id'] for item in result['workerResults']['0']['exercises']] == [
            'LIBRARY_0', 'LIBRARY_1']
        incomplete = next(value['workerResults']['0'] for value in checkpoints
                          if value.get('workerResults', {}).get('0', {}).get('exercises')
                          and len(value['workerResults']['0']['exercises']) == 1)
        assert result['workerResults']['0']['exercises'][0] == incomplete['exercises'][0]
        return

    assert len(calls) == 2
    assert len(result['workerResults']['0']['exercises']) == 1
    assert len(result['workerResults']['1']['exercises']) == 2
    assert solver_calls and all(solver_calls)
    for session in result['workerResults'].values():
        for exercise in session['exercises']:
            expected = next(item for item in prepared['recipeSessions'][0]['exercises']
                            if item['definition_id'] == exercise['definition_id'])
            assert exercise['numWorkSets'] == expected['numWorkSets']
            assert exercise['allocationBounds'] == expected['allocationBounds']
            assert exercise['satisfiesCoverage'] == expected['satisfiesCoverage']


def test_recipe_pool_gap_uses_maximum_occurrence_count_and_reports_missing_menu_items():
    selections = [{'exercises': [{'definition_id': 'LIBRARY_0'}, {'definition_id': 'LIBRARY_0'},
                                 {'definition_id': 'LIBRARY_1'}]},
                  {'exercises': [{'definition_id': 'LIBRARY_0'}, {'definition_id': 'LIBRARY_1'}]}]
    covered = [{'exercises': [{'definition_id': 'LIBRARY_0'}]},
               {'exercises': [{'definition_id': 'LIBRARY_0'}, {'definition_id': 'LIBRARY_0'},
                              {'definition_id': 'LIBRARY_1'}]}]
    assert session_drafting._recipe_pool_gaps(selections, covered) == []

    incomplete = [{'exercises': [{'definition_id': 'LIBRARY_0'}]},
                  {'exercises': [{'definition_id': 'LIBRARY_0'}, {'definition_id': 'LIBRARY_1'}]}]
    assert session_drafting._recipe_pool_gaps(selections, incomplete) == [{
        'definitionId': 'LIBRARY_0', 'requiredOccurrences': 2,
        'availableOccurrences': 1, 'missingOccurrences': 1}]
    repair_tasks = session_drafting._missing_recipe_repair_tasks(selections,
        {'0': {'exercises': []}, '1': incomplete[1]})
    assert [item['definition_id'] for item in repair_tasks[0]] == [
        'LIBRARY_0', 'LIBRARY_0']


def test_candidate_universe_coverage_reports_only_prepared_pool_and_fixed_sources():
    prepared = {'definition_ids': ['LIBRARY_0', 'LIBRARY_1', 'LIBRARY_2']}
    qualification = {'contracts': [{'definition_id': 'LIBRARY_0'}, {'definition_id': 'LIBRARY_1'}],
                     'qualificationConflicts': [{'definition_id': 'LIBRARY_1'}]}
    workers = {'0': {'exercises': [{'definition_id': 'LIBRARY_0'}]},
               '1': {'exercises': [{'definition_id': 'LIBRARY_1'}]}}
    excluded = [{'definitionId': 'LIBRARY_2', 'reasonCode': 'native_warmup_unavailable'}]
    existing = {'workouts': [{'exercises': [{'definition_id': 'LIBRARY_FIXED'}]}]}

    coverage = session_drafting._candidate_universe_coverage(
        prepared, qualification, workers, excluded, existing, workers_finished=True)

    assert coverage == {
        'scope': 'prepared_variable_candidate_definitions_only',
        'status': 'incomplete',
        'preparedDefinitionCount': 3,
        'qualifiedDefinitionCount': 2,
        'workerValidatedRecipeDefinitionCount': 2,
        'fixedExistingDefinitionCount': 1,
        'missingByReason': {
            'qualification_contract_missing': ['LIBRARY_2'],
            'qualification_conflict': ['LIBRARY_1'],
            'native_warmup_unavailable': ['LIBRARY_2'],
        },
    }


def test_candidate_universe_coverage_marks_a_complete_prepared_worker_pool():
    prepared = {'definition_ids': ['LIBRARY_0', 'LIBRARY_1']}
    qualification = {'contracts': [{'definition_id': 'LIBRARY_0'}, {'definition_id': 'LIBRARY_1'}]}
    workers = {'0': {'exercises': [{'definition_id': 'LIBRARY_0'}, {'definition_id': 'LIBRARY_1'}]}}

    coverage = session_drafting._candidate_universe_coverage(prepared, qualification, workers, [])

    assert coverage['status'] == 'complete'
    assert coverage['preparedDefinitionCount'] == coverage['qualifiedDefinitionCount'] == 2
    assert coverage['workerValidatedRecipeDefinitionCount'] == 2
    assert coverage['missingByReason'] == {}


def test_retained_worker_candidate_pool_requires_complete_bound_receipt(monkeypatch):
    from workout_generator_pkg import recipe_contracts

    equipment, messages, prepared, exercises = week_case()
    refs = prepared['definition_ids']
    input_hashes = {ref: hashlib.sha256(json.dumps(
        recipe_contracts._recipe_context(prepared, _latest_requirements(messages), ref),
        sort_keys=True).encode()).hexdigest() for ref in refs}
    qualification = {'inputHash': hashlib.sha256(json.dumps(
        input_hashes, sort_keys=True).encode()).hexdigest(), 'inputHashes': input_hashes,
        'contracts': [{'definition_id': ref, 'satisfiesCoverage': []} for ref in refs]}
    monkeypatch.setattr(recipe_contracts, 'qualify_recipe_contracts', lambda *a, **k: qualification)
    state = request_planning_state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    template = copy.deepcopy(exercises[0])

    def draft(_, request, **__):
        payload = json.loads(request[-1]['content'])
        selection = payload['session']
        values = []
        for item in selection['exercises']:
            exercise = copy.deepcopy(template)
            exercise.update({key: copy.deepcopy(item[key]) for key in
                ('definition_id', 'numWorkSets', 'allocationBounds', 'superset', 'satisfiesCoverage')
                if key in item})
            values.append(exercise)
        return json.dumps({key: copy.deepcopy(selection[key]) for key in
            ('name', 'description', 'timesCompletedInAWeek', 'trainingDays')} | {'exercises': values}), None, None

    monkeypatch.setattr(session_drafting, 'chat_call', draft)
    result = session_drafting.draft_workout_sessions(None, {'preparationId': prepared['preparationId']},
        messages, equipment, state)
    assert result['jointPlanning']['feasible']
    store_tool(messages, 'draft_workout_sessions', {'preparationId': prepared['preparationId']}, result)

    pool = session_drafting.retained_worker_candidate_pool(
        messages, result['proposedSubmission'], equipment)
    assert pool is not None
    assert pool['preparationId'] == prepared['preparationId']
    assert pool['scope'].startswith('retained_prepared_variable_recipe_pool_only')
    assert pool['candidateUniverseCoverage']['status'] == 'complete'
    assert len(pool['sessions']) == 3
    assert pool['fixedWorkouts'] == []

    incomplete = copy.deepcopy(result)
    incomplete['workerResults'] = {}
    messages.pop()
    messages.pop()
    store_tool(messages, 'draft_workout_sessions', {'preparationId': prepared['preparationId']}, incomplete)
    assert session_drafting.retained_worker_candidate_pool(
        messages, incomplete['proposedSubmission'], equipment) is None


def _latest_requirements(messages):
    from workout_generator_pkg.planning_tools import _latest_result
    _, result = _latest_result(messages, 'set_workout_requirements')
    return result['requirements']


@pytest.mark.parametrize(('returned', 'error_code'), [
    ([{'definition_id': 'LIBRARY_9'}], 'unknown_worker_recipe_reference'),
    ([{'definition_id': 'LIBRARY_0'}, {'definition_id': 'LIBRARY_0'}], 'worker_recipe_occurrence_exceeded'),
])
def test_worker_recipe_subset_rejects_unknown_references_and_excess_duplicates(returned, error_code):
    with pytest.raises(session_drafting.PlanningInputError) as error:
        session_drafting._bind_worker_recipe_subset({'exercises': structure()}, {'exercises': returned})
    assert error.value.code == error_code


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


def test_joint_solver_internal_error_reuses_workers_without_exposing_unsolved_submission(monkeypatch):
    from workout_generator_pkg import joint_planning

    equipment, messages, prepared, exercises = week_case()
    state = request_planning_state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    worker_calls = []

    def draft(client, request, **options):
        selection = json.loads(request[-1]['content'])['session']
        worker_calls.append(selection['name'])
        return json.dumps({**{key: value for key, value in selection.items()
            if key not in ('definition_ids', 'structure', 'coverageAssignments')}, 'exercises': exercises}), None, None

    solver = joint_planning.solve_prescribed_week
    solver_calls = []

    def fail_once(*args, **kwargs):
        solver_calls.append(True)
        if len(solver_calls) == 1:
            raise ValueError('An integer objective epigraph has no feasible canonical value.')
        return solver(*args, **kwargs)

    monkeypatch.setattr(session_drafting, 'chat_call', draft)
    monkeypatch.setattr(joint_planning, 'solve_prescribed_week', fail_once)
    checkpoints = []
    arguments = {'preparationId': prepared['preparationId']}
    failed = session_drafting.draft_workout_sessions(None, arguments, messages, equipment, state,
        checkpoint=lambda result: checkpoints.append(copy.deepcopy(result)))

    assert failed['executionFailure'] is True and failed['passed'] is False
    assert failed['errors'][0]['code'] == 'tool_execution_failed'
    assert failed['errors'][0]['owner'] == 'generator'
    assert 'proposedSubmission' not in failed
    assert set(failed['workerResults']) == {'0', '1', '2'}
    assert all('proposedSubmission' not in item for item in checkpoints)
    assert checkpoints[-1]['inProgress'] is False
    store_tool(messages, 'draft_workout_sessions', arguments, failed)
    pending = request_planning_state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert pending.get('parallelSubmission') is None
    assert pending['parallelPreparation']['preparationId'] == prepared['preparationId']
    assert pending['constructionTask']['stage'] == 'draft_sessions'

    monkeypatch.setattr(session_drafting, 'chat_call', lambda *a, **k: pytest.fail('Saved workers must be reused'))
    resumed = session_drafting.draft_workout_sessions(None, arguments, messages, equipment, state)
    assert 'proposedSubmission' in resumed
    assert len(solver_calls) == 2
    assert all(worker_calls.count(name) == 1 for name in ('Session 0', 'Session 1', 'Session 2'))
    store_tool(messages, 'draft_workout_sessions', arguments, resumed)
    completed = request_planning_state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert completed['parallelSubmission'] == resumed['proposedSubmission']


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


def test_mixed_straight_set_repair_allows_group_fields_on_its_superset_partner_only():
    before = {'workouts': [{'exercises': [
        {'definition_id': 'LIBRARY_0', 'superset': 'A', 'restBetweenSetsSeconds': 0,
         'restAfterExerciseSeconds': 0, 'restAfterSupersetExerciseSeconds': 20},
        {'definition_id': 'LIBRARY_1', 'superset': 'A', 'restBetweenSetsSeconds': 0,
         'restAfterExerciseSeconds': 0, 'restAfterSupersetExerciseSeconds': 120},
        {'definition_id': 'LIBRARY_2', 'superset': 'B', 'restBetweenSetsSeconds': 0,
         'restAfterExerciseSeconds': 0, 'restAfterSupersetExerciseSeconds': 30},
    ]}]}
    errors = [{'code': 'execution_straightSets',
        'path': '/workouts/0/exercises/0/superset', 'groupRepairOnly': True,
        'permittedPaths': {'exact': ['/workouts/0/exercises'], 'descendants': ['/workouts/0/exercises']}}]
    patch = [
        {'op': 'replace', 'path': '/workouts/0/exercises/0/superset', 'value': None},
        {'op': 'replace', 'path': '/workouts/0/exercises/0/restBetweenSetsSeconds', 'value': 120},
        {'op': 'replace', 'path': '/workouts/0/exercises/0/restAfterExerciseSeconds', 'value': 60},
        {'op': 'replace', 'path': '/workouts/0/exercises/0/restAfterSupersetExerciseSeconds', 'value': 0},
        {'op': 'replace', 'path': '/workouts/0/exercises/1/superset', 'value': None},
        {'op': 'replace', 'path': '/workouts/0/exercises/1/restBetweenSetsSeconds', 'value': 90},
        {'op': 'replace', 'path': '/workouts/0/exercises/1/restAfterSupersetExerciseSeconds', 'value': 0},
    ]
    after = session_drafting.apply_json_patch(before, patch)['workouts'][0]

    session_drafting._validate_mixed_group_repair(before, after, patch, errors)

    unrelated = [{'op': 'replace', 'path': '/workouts/0/exercises/2/restAfterSupersetExerciseSeconds', 'value': 0}]
    unrelated_after = session_drafting.apply_json_patch(before, unrelated)['workouts'][0]
    with pytest.raises(ValueError, match='outside the reported findings'):
        session_drafting._validate_mixed_group_repair(before, unrelated_after, unrelated, errors)


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


def test_worker_response_omits_code_owned_session_fields_and_restores_prepared_values(monkeypatch):
    from workout_generator_pkg.planning_tools import ASSUMPTIONS

    equipment, messages, prepared, exercises = week_case(occurrences=3,
        working_set_rir={'minimum': 1, 'maximum': 2})
    prepared['recipeSessions'][0]['exercises'][0]['workSetTemplate'] = {'reps': 8}
    messages[-1]['content'] = json.dumps(prepared)
    state = request_planning_state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    def respond(client, request, **options):
        payload = json.loads(request[-1]['content'])
        assert 'permittedPaths' not in payload
        session_schema = payload['responseSchema']
        assert not {'name', 'description', 'timesCompletedInAWeek', 'trainingDays'} & session_schema['properties'].keys()
        exercise_schema = session_schema['properties']['exercises']['items']
        assert not {'numWorkSets', 'allocationBounds', 'satisfiesCoverage'} & exercise_schema['properties'].keys()
        assert not {'setupSeconds', 'intraSetRestInSeconds', 'generateWarmUpSets',
                    'effortAcceptance'} & exercise_schema['properties'].keys()
        assert {'workSetTemplate', 'targetSetPrescriptions'} <= exercise_schema['properties'].keys()
        target_schema = exercise_schema['properties']['targetSetPrescriptions']['items']
        assert 'workSetIndex' not in target_schema['properties']
        assert 'workSetIndex' not in target_schema['required']
        values = [copy.deepcopy(exercises[0]) for _ in payload['session']['exercises']]
        for index, value in enumerate(values):
            for field in ('numWorkSets', 'allocationBounds', 'satisfiesCoverage'):
                value.pop(field, None)
            value.pop('repDurationSeconds', None)
            value.update(setupSeconds=999, intraSetRestInSeconds=20, generateWarmUpSets=True,
                         effortAcceptance={'kind': 'rir_range', 'minimumRIR': 10, 'maximumRIR': 10})
            value.pop('workSetTemplate', None)
            value.pop('targetSetPrescriptions', None)
            if payload['sessionReference'] == 'SESSION_0' and index == 0:
                value['workSetTemplate'] = {'reps': 100, 'additionalWeight': 200}
            elif index == 1:
                value['targetSetPrescriptions'] = [
                    {'workSetIndex': 999, 'reps': 8}, {'workSetIndex': 999, 'reps': 8}]
            value.update(superset='Invented' if index in (0, 2) else None)
        return json.dumps({'exercises': values}), None, None
    monkeypatch.setattr(session_drafting, 'chat_call', respond)
    result = session_drafting.draft_workout_sessions(None, {'preparationId': prepared['preparationId']}, messages, equipment, state)
    assert 'proposedSubmission' in result, result.get('errors')
    for index, expected in enumerate(prepared['recipeSessions']):
        day = result['workerResults'][str(index)]
        assert [item['numWorkSets'] for item in day['exercises']] == [item['numWorkSets'] for item in expected['exercises']]
        assert all(item['effortAcceptance']['minimumRIR'] == 1 and
                   item['effortAcceptance']['maximumRIR'] == 2 for item in day['exercises'])
        if index == 0:
            assert day['exercises'][0]['workSetTemplate'] == {'reps': 8}
        else:
            assert 'workSetTemplate' not in day['exercises'][0]
        assert day['exercises'][1]['targetSetPrescriptions'] == [
            {'workSetIndex': 0, 'reps': 8}, {'workSetIndex': 1, 'reps': 8}]
        assert all(item['generateWarmUpSets'] is False and item['intraSetRestInSeconds'] is None
                   for item in day['exercises'])
        assert all('repDurationSeconds' not in item for item in day['exercises'])
        assert day['exercises'][0].get('setupSeconds') is None
        assert all(item['setupSeconds'] == ASSUMPTIONS['transitionSeconds']
                   for item in day['exercises'][1:])
        assert all(item['superset'] is None for item in day['exercises'])
    assert result['jointPlanning']['feasible']


def test_worker_schema_leaves_rep_choices_and_technique_cues_to_model_but_not_approved_rir():
    schema = session_drafting._worker_response_schema({'workingSetRIR': {'minimum': 1, 'maximum': 2}})
    exercise = schema['properties']['exercises']['items']['properties']
    assert 'minReps' in exercise and 'maxReps' in exercise and 'durationSeconds' in exercise
    assert 'repDurationSeconds' in exercise
    assert not {'numWorkSets', 'allocationBounds', 'satisfiesCoverage', 'setupSeconds',
                'intraSetRestInSeconds', 'generateWarmUpSets', 'effortAcceptance'} & exercise.keys()
    assert {'workSetTemplate', 'targetSetPrescriptions'} <= exercise.keys()
    assert 'workSetIndex' not in exercise['targetSetPrescriptions']['items']['properties']
    exercise_without_approved_rir = session_drafting._worker_response_schema({})['properties']['exercises']['items']['properties']
    assert 'acceptanceCriterion' in exercise_without_approved_rir['effortAcceptance']['properties']
    assert 'minimumRIR' in exercise_without_approved_rir['effortAcceptance']['properties']


def test_partial_recipe_qualification_is_checkpointed_and_reused_after_resume(monkeypatch):
    equipment, messages, prepared, exercises = week_case()
    state = request_planning_state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    partial = {'inputHash': 'partial-input', 'inputHashes': {'LIBRARY_0': 'recipe-hash'},
               'contracts': [{'definition_id': 'LIBRARY_0', 'satisfiesCoverage': []}]}
    complete = {'inputHash': 'complete-input', 'inputHashes': {'LIBRARY_0': 'recipe-hash'},
                'contracts': [{'definition_id': 'LIBRARY_0', 'satisfiesCoverage': []}]}
    qualifications = []

    def qualify(*args, **kwargs):
        cached = args[6]
        qualifications.append(copy.deepcopy(cached))
        if len(qualifications) == 1:
            kwargs['checkpoint'](copy.deepcopy(partial))
            raise RuntimeError('later qualification batch was truncated')
        assert cached == partial
        return copy.deepcopy(complete)

    def draft(_, request, **__):
        return json.dumps({'exercises': copy.deepcopy(exercises)}), None, None

    monkeypatch.setattr('workout_generator_pkg.recipe_contracts.qualify_recipe_contracts', qualify)
    monkeypatch.setattr(session_drafting, 'chat_call', draft)
    arguments = {'preparationId': prepared['preparationId']}
    partial_checkpoints = []
    failed = session_drafting.draft_workout_sessions(None, arguments, messages, equipment, state,
        checkpoint=lambda result: partial_checkpoints.append(copy.deepcopy(result)))

    assert failed['executionFailure'] is True
    assert failed['recipeQualification'] == partial
    assert partial_checkpoints == [{**{key: prepared.get(key) for key in (
        'preparationId', 'requirementsId', 'baseDraftId', 'libraryFingerprint',
        'historyFingerprint', 'draftingVersion')}, 'recipeQualification': partial, 'inProgress': True}]
    store_tool(messages, 'draft_workout_sessions', arguments, failed)

    resumed = session_drafting.draft_workout_sessions(None, arguments, messages, equipment, state)

    assert 'proposedSubmission' in resumed, resumed.get('errors')
    assert qualifications == [None, partial]
    assert resumed['recipeQualification'] == complete


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


def test_shell_prepares_parallel_sessions_and_audits_combined_proposal_after_menu_choice(monkeypatch, tmp_path):
    from test_workout_generator_conversation_sessions import make_shell_deps, FakeToolCall, FakeFunction
    from test_workout_generator_single_review import response_for, request_data
    from workout_generator_pkg.conversation_store import load_active_conversation_record
    equipment, messages, prepared, exercises = week_case(working_set_rir={'minimum': 1, 'maximum': 2})
    stored = json.loads(next(m['content'] for m in messages if m.get('tool_call_id') == 'requirements'))
    stored['requirements'].pop('notes', None)
    path = tmp_path / 'library.json'
    path.write_text(json.dumps(equipment), encoding='utf-8')
    arguments = {key: prepared[key] for key in ('requirementsId', 'baseDraftId', 'name', 'sessions')}
    def tool(name, args, key):
        return None, [FakeToolCall(key, 'function', FakeFunction(name, json.dumps(args)))]
    deps = make_shell_deps(tmp_path, chat_results=[
        tool('set_workout_requirements', stored['requirements'], 'requirements'),
        tool('search_exercise_library', {'queries': ['Push-Up']}, 'search'),
        tool('prepare_workout_sessions', arguments, 'prepare'),
        tool('draft_workout_sessions', {'preparationId': prepared['preparationId']}, 'draft')],
        generation_results=[], generation_calls=[])
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
            elif call.function.name == 'draft_workout_sessions':
                call.function.arguments = json.dumps({'preparationId': state['parallelPreparation']['preparationId']})
        return result
    deps.chat_call_with_loading = capture
    def worker(client, request, **kwargs):
        selection = json.loads(request[-1]['content'])['session']
        return json.dumps({**{key: value for key, value in selection.items() if key not in ('definition_ids', 'structure', 'coverageAssignments')},
                           'exercises': exercises}), None, None
    monkeypatch.setattr(session_drafting, 'chat_call', worker)
    monkeypatch.setattr(plan_review, '_review_call', lambda client, request, **options:
        (json.dumps(response_for(request_data(request), options['output_schema'])
                    if 'sourceCoverage' in options['output_schema']['properties'] else {'findings': []}), None, None))
    monkeypatch.setattr('sys.argv', ['workout_generator.py', '--exercise-library-file', str(path)])
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test-key')
    inputs = iter(['Plan three sessions, 5-6 chest sets each and 15-18 weekly, at 1-2 RIR.', 'CONFIRM REQUIREMENTS', '/exit'])
    monkeypatch.setattr('builtins.input', lambda prompt='': next(inputs))
    shell.main(deps=deps)
    saved = load_active_conversation_record(str(tmp_path))['messages']
    audits = [json.loads(m['content']) for m in saved if m.get('role') == 'tool' and '"auditVersion"' in m.get('content', '')]
    assert len(requests) == 4
    assert len(audits) == 1 and audits[0]['passed']
    assert len(audits[0]['submittedDraft']['workouts']) == 3
