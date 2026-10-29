import copy
import json

import pytest
from jsonschema import ValidationError, validate

from workout_generator_pkg import allocation, api_client, plan_review, session_drafting
from workout_generator_pkg.planner_context import planner_response_profile
from workout_generator_pkg.planning_tools import (
    REPAIR_WORKOUT_PLAN_TOOL, _EXERCISE, PlanningInputError, audit_workout_plan,
    metadata_patch_tool, planning_failure_signature,
)
from test_workout_generator_planning_tools import planning_case, requirement_messages
from test_workout_generator_parallel_planning import store_tool
from test_workout_generator_week_structure import prepared_case


@pytest.fixture(autouse=True)
def qualified_recipe_fixture(monkeypatch):
    # Recipe qualification has dedicated tests; these tests isolate drafting/repair behavior.
    monkeypatch.setattr('workout_generator_pkg.recipe_contracts.qualify_recipe_contracts',
        lambda *args, **kwargs: {'inputHash': 'qualified-fixture', 'contracts': [], 'capabilities': {}})


def test_selection_repair_ignores_exact_identity_noops_but_keeps_change_guards():
    original = {'sessions': [{'exercises': [
        {'definition_id': 'LIBRARY_1', 'satisfiesCoverage': ['horizontal_pull']},
        {'definition_id': 'LIBRARY_2', 'satisfiesCoverage': ['horizontal_push']},
    ]}]}
    occurrences = {
        '/sessions/0/exercises/0': copy.deepcopy(original['sessions'][0]['exercises'][0]),
        '/sessions/0/exercises/1': copy.deepcopy(original['sessions'][0]['exercises'][1]),
    }
    task = {'arguments': copy.deepcopy(original), 'blockRepair': {'groupingOnly': False, 'sessions': {
        'SESSION_0': {'occurrences': occurrences, 'editableOccurrences': list(occurrences), 'canAdd': False}}}}
    patch = {'sessionBlocks': [{'sessionReference': 'SESSION_0', 'replacements': [
        {'replaces': '/sessions/0/exercises/0', 'definition_id': 'LIBRARY_1',
         'satisfiesCoverage': ['horizontal_pull']},
        {'replaces': '/sessions/0/exercises/1', 'definition_id': 'LIBRARY_3',
         'satisfiesCoverage': ['vertical_pull']},
    ]}]}

    result = session_drafting._apply_selection_blocks(patch, task)
    assert result['sessions'][0]['exercises'] == [
        {'definition_id': 'LIBRARY_1', 'satisfiesCoverage': ['horizontal_pull']},
        {'definition_id': 'LIBRARY_3', 'satisfiesCoverage': ['vertical_pull']},
    ]
    assert original['sessions'][0]['exercises'][1]['definition_id'] == 'LIBRARY_2'

    coverage_edit = copy.deepcopy(patch)
    coverage_edit['sessionBlocks'][0]['replacements'][0]['satisfiesCoverage'] = ['vertical_pull']
    with pytest.raises(ValueError, match='different library definition'):
        session_drafting._apply_selection_blocks(coverage_edit, task)

    all_noop = {'sessionBlocks': [{'sessionReference': 'SESSION_0', 'replacements': [
        {'replaces': '/sessions/0/exercises/0', 'definition_id': 'LIBRARY_1',
         'satisfiesCoverage': ['horizontal_pull']},
    ]}]}
    with pytest.raises(ValueError, match='replace or add at least one exercise'):
        session_drafting._apply_selection_blocks(all_noop, task)


def test_preparation_repair_carries_menu_review_into_the_model_request():
    from workout_generator_pkg.planner_context import focus_planner_context

    equipment, _, messages, arguments, _ = prepared_case()
    prepared = session_drafting.prepare_workout_sessions(arguments, messages, equipment)
    store_tool(messages, 'prepare_workout_sessions', arguments, prepared)
    alternate = 'LIBRARY_0'
    menu_review = {'evidence': {
        'status': 'infeasible_relaxation', 'roleUpperBounds': {'lateral_delt': 3.0},
        'approvedMinimumConflicts': [{'role': 'lateral_delt', 'required': 6, 'qualifiedMenuUpperBound': 3.0}],
        'selectableCreditProfileAlternatives': {'alternatives': [
            {'definition_id': alternate, 'qualificationStatus': 'unqualified'}]},
    }}
    error = {'code': 'infeasible_set_allocation', 'path': '/sessions',
        'conflictingTargets': [{'target': 'weekly:lateral_delt', 'slotIds': ['/sessions/0/exercises/0']}]}
    worker = {'preparationId': prepared['preparationId'], 'preparationErrors': [error], 'menuReview': menu_review}
    store_tool(messages, 'draft_workout_sessions', {}, worker)

    task = session_drafting.preparation_repair_task(messages)
    request = focus_planner_context(messages, messages, equipment)
    state = json.loads(request[-1]['content'].split('\n', 1)[1])
    evidence = state['preparationRepairTask']['menuReview']['evidence']
    assert task['menuReview'] == menu_review
    assert evidence['roleUpperBounds']['lateral_delt'] == 3.0
    assert evidence['approvedMinimumConflicts'][0]['required'] == 6
    assert evidence['selectableCreditProfileAlternatives']['alternatives'][0]['definition_id'] == alternate


def test_hard_menu_conflict_exposes_only_proven_single_addition_and_code_owns_fields():
    task = {'menuReview': {'evidence': {
        'hardFeasibilityStatus': 'infeasible_relaxation',
        'developmentRoleRelief': {'singleAdditionFeasibility': {
            'status': 'feasible_relaxation', 'additions': [{
                'hardFeasibilityStatus': 'feasible_relaxation', 'qualificationStatus': 'unqualified',
                'qualifiedRoleContribution': 0, 'definitionChoices': [
                {'id': 'LIBRARY_17', 'name': 'Candidate'}]}]}}}},
        'arguments': {'sessions': [{'exercises': [
            {'definition_id': 'LIBRARY_1', 'satisfiesCoverage': ['upper_pull'], 'numWorkSets': 5}]}]},
        'blockRepair': {'groupingOnly': False, 'sessions': {'SESSION_0': {
            'occurrences': {'/sessions/0/exercises/0': {'definition_id': 'LIBRARY_1'}},
            'editableOccurrences': ['/sessions/0/exercises/0'], 'canAdd': True}}},
        'permittedPaths': ['/sessions/0/exercises/-'], 'permittedDescendantPaths': [],
    }
    schema = session_drafting.preparation_patch_tool(task)['function']['parameters']
    valid = {'basePreparationId': 'PREPARATION_3', 'sessionBlocks': [{
        'sessionReference': 'SESSION_0', 'additions': [{'definition_id': 'LIBRARY_17'}]}]}
    validate(valid, schema)

    for forbidden in (
        {'definition_id': 'LIBRARY_18'},
        {'definition_id': 'LIBRARY_17', 'satisfiesCoverage': ['lateral_delt']},
        {'definition_id': 'LIBRARY_17', 'numWorkSets': 4},
    ):
        invalid = copy.deepcopy(valid)
        invalid['sessionBlocks'][0]['additions'] = [forbidden]
        with pytest.raises(ValidationError):
            validate(invalid, schema)
    invalid = copy.deepcopy(valid)
    invalid['sessionBlocks'][0]['additions'].append({'definition_id': 'LIBRARY_17'})
    with pytest.raises(ValidationError):
        validate(invalid, schema)
    invalid = copy.deepcopy(valid)
    invalid['sessionBlocks'][0]['replacements'] = [{'replaces': '/sessions/0/exercises/0',
        'definition_id': 'LIBRARY_17', 'satisfiesCoverage': []}]
    with pytest.raises(ValidationError):
        validate(invalid, schema)

    applied = session_drafting._apply_selection_blocks(valid, task)
    assert applied['sessions'][0]['exercises'][0] == task['arguments']['sessions'][0]['exercises'][0]
    assert applied['sessions'][0]['exercises'][1] == {
        'definition_id': 'LIBRARY_17', 'satisfiesCoverage': [], 'numWorkSets': 3,
        'allocationBounds': {'minimum': 1, 'maximum': 20}, 'superset': None}


def test_stale_hard_menu_review_recomputes_from_hash_matched_recipe_qualification(monkeypatch):
    import hashlib
    from workout_generator_pkg.recipe_contracts import _recipe_context

    equipment, _, messages, arguments, _ = prepared_case()
    prepared = session_drafting.prepare_workout_sessions(arguments, messages, equipment)
    prepared['recipeSessions'][0]['exercises'][0]['satisfiesCoverage'] = ['untrusted_model_claim']
    store_tool(messages, 'prepare_workout_sessions', arguments, prepared)
    _, requirements = session_drafting._latest_result(messages, 'set_workout_requirements')
    refs = prepared['definition_ids']
    input_hashes = {ref: hashlib.sha256(json.dumps(_recipe_context(
        prepared, requirements['requirements'], ref), sort_keys=True).encode()).hexdigest() for ref in refs}
    identity = hashlib.sha256(json.dumps(input_hashes, sort_keys=True).encode()).hexdigest()
    worker = {key: prepared[key] for key in (
        'preparationId', 'requirementsId', 'baseDraftId', 'libraryFingerprint', 'historyFingerprint', 'draftingVersion')}
    worker.update(preparationErrors=[{'code': 'infeasible_set_allocation'}], recipeQualification={
        'inputHash': identity, 'inputHashes': input_hashes,
        'contracts': [{'definition_id': ref, 'satisfiesCoverage': []} for ref in refs]},
        menuReview={'evidence': {'hardFeasibilityStatus': 'infeasible_relaxation',
            'selectableCreditProfileAlternatives': {'alternatives': [{'definition_id': 'LIBRARY_98'}]}}})
    store_tool(messages, 'draft_workout_sessions', {}, worker)
    worker_index = len(messages) - 1
    task = {'basePreparationId': f'PREPARATION_{worker_index}',
        'arguments': arguments, 'menuReview': worker['menuReview']}
    observed = {}
    def recompute(actual_prepared, selections, actual_requirements, actual_equipment, actual_messages, existing):
        observed['coverage'] = [item['satisfiesCoverage'] for day in selections for item in day['exercises']]
        return {'evidence': {'status': 'infeasible_relaxation',
            'hardFeasibilityStatus': 'infeasible_relaxation',
            'roleUpperBounds': {'lateral_delt': 4.5},
            'selectableCreditProfileAlternatives': {'alternatives': [{'definition_id': 'LIBRARY_98'}]},
            'developmentRoleRelief': {'singleAdditionFeasibility': {
                'status': 'feasible_relaxation', 'additions': [{
                    'hardFeasibilityStatus': 'feasible_relaxation', 'qualificationStatus': 'unqualified',
                    'qualifiedRoleContribution': 0, 'definitionChoices': [{'id': 'LIBRARY_216', 'name': 'Candidate'}]}]}}}}
    monkeypatch.setattr(session_drafting, '_development_menu_review', recompute)

    refreshed = session_drafting.refresh_stale_hard_menu_review(task, messages, equipment)

    assert observed['coverage'] == [[], [], []]
    evidence = refreshed['menuReview']['evidence']
    assert session_drafting._proven_single_add_menu_choices(refreshed) == ['LIBRARY_216']
    assert 'selectableCreditProfileAlternatives' not in evidence
    assert evidence['roleUpperBounds'] == {'lateral_delt': 4.5}
    schema = session_drafting.preparation_patch_tool({**refreshed, 'blockRepair': {
        'groupingOnly': False, 'sessions': {'SESSION_0': {
            'occurrences': {}, 'editableOccurrences': [], 'canAdd': True}}},
        'permittedPaths': [], 'permittedDescendantPaths': []})['function']['parameters']
    assert schema['properties']['sessionBlocks']['items']['oneOf'][0]['properties']['additions']['items'][
        'properties']['definition_id']['enum'] == ['LIBRARY_216']


def test_retained_lib216_repair_passes_request_and_real_preparation_handler():
    from pathlib import Path
    from workout_generator_pkg.interactive_shell import _load_exercise_library_payload

    root = Path(__file__).resolve().parents[1]
    run = root / 'build/workout_quality_policy_20261027/fresh_e2e'
    transcript = run / 'workouts/conversation_sessions/aca503d2-2204-4091-959a-64cc950960f4/messages.json'
    backup = root / 'build/backup_conversion/workout_store_backup_2026-10-15_current_library_snapshot_evidence.json'
    if not transcript.exists() or not backup.exists():
        pytest.skip('Retained E2E case is unavailable in this checkout.')
    messages = json.loads(transcript.read_text(encoding='utf-8'))[:209]
    arguments = json.loads(messages[205]['tool_calls'][0]['function']['arguments'])
    assert arguments['sessionBlocks'][0]['additions'] == [{'definition_id': 'LIBRARY_216'}]
    failed = json.loads(messages[206]['content'])
    assert failed['errors'][0]['code'] == 'preparation_patch_rejected'
    library = _load_exercise_library_payload(str(backup))
    equipment = {key: library[key] for key in (
        'exerciseDefinitions', 'equipments', 'accessoryEquipments', 'exerciseMovements')}
    from workout_generator_pkg.planner_context import focus_planner_context
    request = focus_planner_context(messages, messages, equipment)
    request_state = json.loads(request[-1]['content'].split('\n', 1)[1])
    projected_task = request_state['preparationRepairTask']
    validate(arguments, session_drafting.preparation_patch_tool(projected_task)['function']['parameters'])
    assert session_drafting._proven_single_add_menu_choices(projected_task)

    prepared = session_drafting.prepare_workout_sessions(arguments, messages, equipment)

    assert prepared['setAllocation']['feasible'] is True
    added = [item for day in prepared['recipeSessions'] for item in day['exercises']
        if item['definition_id'] == 'LIBRARY_216']
    assert len(added) == 1 and added[0]['satisfiesCoverage'] == []


def test_movement_selection_leaves_arithmetic_to_allocator_and_preserves_source_state():
    from workout_generator_pkg.interactive_shell import _messages_for_api
    from workout_generator_pkg.planner_context import request_planning_state
    equipment, requirements, messages, arguments, _ = prepared_case()
    before = copy.deepcopy(messages)
    # Retain a selectable movement, including the numerical credits returned by discovery.
    from workout_generator_pkg.exercise_library_tools import get_exercise_candidates
    result = get_exercise_candidates({'definition_ids': ['LIBRARY_0']}, equipment, messages)
    store_tool(messages, 'get_exercise_candidates', {'definition_ids': ['LIBRARY_0']}, result)
    saved = copy.deepcopy(messages)
    state = request_planning_state(_messages_for_api(messages, True, provided_equipment=equipment))
    assert state['constructionTask']['stage'] == 'choose_movements'
    assert state['requirements']['auditTargets']['weeklyEffectiveSets'] == requirements['auditTargets']['weeklyEffectiveSets']
    assert state['requirements']['auditTargets']['maximumSessionSeconds'] == requirements['auditTargets']['maximumSessionSeconds']
    candidate = state['exerciseCandidates']['LIBRARY_0']
    assert candidate['creditsPerWorkingSet'] == result['exercises'][0]['creditsPerWorkingSet']
    assert candidate['muscleGroups'] == ['FRONT_CHEST']
    profile = planner_response_profile(state)
    assert profile['reasoning_effort'] is None and profile['activity'] == 'Selecting weekly movements'
    assert messages == saved and messages[:len(before)] == before
    # The backend still checks every numerical target against the selected structure.
    impossible = copy.deepcopy(arguments)
    from workout_generator_pkg.planning_tools import set_workout_requirements
    limited = set_workout_requirements({**requirements, 'executionRules': [
        {'kind': 'workSets', 'coverageKey': None, 'minimumSets': 1, 'maximumSets': 1}]},
        [{'role': 'user', 'content': 'Exactly one set per exercise.'}], equipment)
    messages = requirement_messages(limited)
    impossible['requirementsId'] = limited['requirementsId']
    for day in impossible['sessions']:
        day['exercises'][0]['allocationBounds'] = {'minimum': 1, 'maximum': 1}
        day['exercises'][0]['numWorkSets'] = 1
    with pytest.raises(PlanningInputError) as caught:
        session_drafting.prepare_workout_sessions(impossible, messages, equipment)
    assert caught.value.code == 'infeasible_set_allocation'
    from workout_generator_pkg.planning_tools import planning_tool_failure, _latest_result
    store_tool(messages, 'prepare_workout_sessions', impossible,
               planning_tool_failure('prepare_workout_sessions', caught.value, impossible))
    repair_state = request_planning_state(_messages_for_api(messages, True, provided_equipment=equipment))
    assert repair_state['preparationRepairTask']['needsAlternatives']
    assert planner_response_profile(repair_state)['reasoning_effort'] is None
    assert repair_state['requirements']['auditTargets']['weeklyEffectiveSets'] == requirements['auditTargets']['weeklyEffectiveSets']
    assert repair_state['exerciseCandidates']['LIBRARY_0']['muscleGroups'] == ['FRONT_CHEST']
    _, retained = _latest_result(messages, 'set_workout_requirements')
    assert retained['requirements']['auditTargets']['weeklyEffectiveSets'] == requirements['auditTargets']['weeklyEffectiveSets']


def test_prepared_session_stage_keeps_prescription_reasoning_budget():
    profile = planner_response_profile({'constructionTask': {'stage': 'draft_sessions', 'remainingWeeklySessions': 3}})
    assert profile['reasoning_effort'] == 'low' and profile['activity'] == 'Drafting session'


def test_movement_repair_uses_solver_feedback_without_restarting_extended_reasoning():
    profile = planner_response_profile({'preparationRepairTask': {'needsAlternatives': True,
        'errors': [{'code': 'infeasible_set_allocation', 'path': '/sessions'}]}})
    assert profile['reasoning_effort'] is None and profile['activity'] == 'Repairing weekly selection'
    assert profile['max_tokens'] == 16384


def test_retry_identity_ignores_preparation_receipts_and_overwritten_note_operations():
    failures = [{'code': 'export_description_too_long', 'path': '/sessions/0/description'}]
    feedback = {'preparationArguments': {'sessions': [{'description': 'Too long'}]}, 'errors': failures}
    assert planning_failure_signature('prepare_workout_sessions', {'basePreparationId': 'PREPARATION_1'}, feedback, []) == \
        planning_failure_signature('prepare_workout_sessions', {'basePreparationId': 'PREPARATION_3'}, feedback, [])
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    result = audit_workout_plan(draft, equipment, messages)
    store_tool(messages, 'audit_workout_plan', draft, result)
    path = '/workouts/0/exercises/0/placementNotes'
    patch = {'requirementsId': stored['requirementsId'], 'baseDraftId': result['currentDraftId'],
             'patch': [{'op': 'replace', 'path': path, 'value': 'Too long'}]}
    first = {'errors': failures, 'rejectedSubmission': patch}
    accumulated = copy.deepcopy(first)
    accumulated['rejectedSubmission']['patch'].append(copy.deepcopy(patch['patch'][0]))
    assert planning_failure_signature('audit_workout_plan', patch, first, messages) == \
        planning_failure_signature('audit_workout_plan', accumulated['rejectedSubmission'], accumulated, messages)
    accumulated['rejectedSubmission']['patch'][-1]['value'] = 'Shorter'
    assert planning_failure_signature('audit_workout_plan', patch, first, messages) != \
        planning_failure_signature('audit_workout_plan', accumulated['rejectedSubmission'], accumulated, messages)


@pytest.mark.parametrize('arguments', [None, [], 'invalid'])
def test_retry_identity_preserves_invalid_non_object_arguments(arguments):
    feedback = {'errors': [{'code': 'invalid_arguments', 'path': '/'}]}
    signature = planning_failure_signature('audit_workout_plan', arguments, feedback, [])
    assert json.loads(signature)[1] == arguments


def test_metadata_tool_enforces_the_actual_field_budget_without_mutating_shared_schema():
    original = copy.deepcopy(REPAIR_WORKOUT_PLAN_TOOL)
    path = '/workouts/0/exercises/0/placementNotes'
    tool = metadata_patch_tool(REPAIR_WORKOUT_PLAN_TOOL, {path: {'maximumCharacters': 226}})
    args = {'requirementsId': 'R', 'baseDraftId': 'REVISION_1',
            'patch': [{'op': 'replace', 'path': path, 'value': 'x' * 226}]}
    validate(args, tool['function']['parameters'])
    args['patch'][0]['value'] += 'x'
    with pytest.raises(ValidationError):
        validate(args, tool['function']['parameters'])
    args['patch'][0].update(path='/workouts/1/description', value='Short')
    with pytest.raises(ValidationError):
        validate(args, tool['function']['parameters'])
    assert REPAIR_WORKOUT_PLAN_TOOL == original


def test_first_preparation_rejection_contains_usable_budget_purpose_and_repair_scope():
    from workout_generator_pkg.planning_tools import planning_tool_failure
    equipment, _, messages, arguments, _ = prepared_case()
    arguments['sessions'][0].update(description='Front squat, bench/row, hip hinge, lateral delts, arms, calves', trainingDays=[0])
    arguments['sessions'][1].update(description='Overhead press, split squat, row/floor press, chin-up, Nordic curl', trainingDays=[2])
    with pytest.raises(PlanningInputError) as caught:
        session_drafting.prepare_workout_sessions(arguments, messages, equipment)
    feedback = planning_tool_failure('prepare_workout_sessions', caught.value, arguments)
    assert [error['expected'] for error in feedback['errors']] == [32, 29]
    assert all('textFieldContract' in error for error in feedback['errors'])
    store_tool(messages, 'prepare_workout_sessions', arguments, feedback)
    task = session_drafting.preparation_repair_task(messages)
    assert len(task['metadataFields']) == len(task['errors']) == 2
    for field in task['metadataFields'].values():
        assert field['maximumCharacters'] + field['reservedCharacters'] == 50
        assert field['charactersToRemove'] == field['currentCharacters'] - field['maximumCharacters']
        assert 'not an exercise list' in field['purpose'] and field['repair']
    repaired = session_drafting.prepare_workout_sessions({'basePreparationId': task['basePreparationId'], 'patch': [
        {'op': 'replace', 'path': path, 'value': field['example']} for path, field in task['metadataFields'].items()]}, messages, equipment)
    assert repaired['sessions'][0]['description'] == 'Full body'
    assert repaired['sessions'][1]['description'] == 'Full body'


def test_workout_citation_permits_description_fix_without_authorizing_other_sessions():
    equipment, _, messages, arguments, _ = prepared_case()
    prepared = session_drafting.prepare_workout_sessions(arguments, messages, equipment)
    store_tool(messages, 'prepare_workout_sessions', arguments, prepared)
    store_tool(messages, 'draft_workout_sessions', {}, {'preparationId': prepared['preparationId'],
        'structureReview': {'version': plan_review.STRUCTURE_REVIEW_VERSION, 'passed': False, 'findings': [{'severity': 'blocking', 'path': '/draft/workouts/0',
            'evidencePaths': ['/draft/workouts/0'], 'message': 'Description names the wrong movement.',
            'repair': 'Correct the description.'}]}})
    task = session_drafting.preparation_repair_task(messages)
    repair = {'basePreparationId': task['basePreparationId'], 'patch': [
        {'op': 'replace', 'path': '/sessions/0/description', 'value': 'Push'}]}
    corrected = session_drafting.resolve_preparation_patch(repair, messages)
    assert corrected['sessions'][0]['exercises'] == prepared['sessions'][0]['exercises']
    repair['patch'][0]['path'] = '/sessions/1/description'
    with pytest.raises(PlanningInputError, match='outside|not one of'):
        session_drafting.resolve_preparation_patch(repair, messages)


def test_allocator_identifies_forced_counts_and_releases_them_when_placement_changes():
    candidates = {'LIBRARY_0': {'creditsPerWorkingSet': {'chest': {'direct': 1, 'indirect': 0}}}}
    item = {'definition_id': 'LIBRARY_0', 'numWorkSets': 3, 'superset': None,
            'allocationBounds': {'minimum': 1, 'maximum': 20}}
    sessions = [{'timesCompletedInAWeek': 1, 'exercises': [item]},
                {'timesCompletedInAWeek': 1, 'exercises': []}]
    requirements = {'auditTargets': {'weeklyEffectiveSets': {'chest': {'minimum': 15, 'maximum': 18}},
                                    'perSessionEffectiveSets': {}}}
    before = copy.deepcopy(sessions)
    result = allocation.allocate_prepared_sets(sessions, candidates, requirements)
    assert result['sessions'][0]['exercises'][0]['numWorkSets'] == 15
    assert result['allocationDiagnostics'][0]['minimumRequiredSets'] == 15
    sessions[1]['exercises'].append(copy.deepcopy(item))
    spread = allocation.allocate_prepared_sets(sessions, candidates, requirements)
    assert sorted(day['exercises'][0]['numWorkSets'] for day in spread['sessions']) == [7, 8]
    assert all(item.get('scope') == 'weekly' for item in spread['allocationDiagnostics'])
    assert spread['allocationDiagnostics'][0]['minimumRequiredSets'] == 15
    assert sessions[0] == before[0]


def test_review_distinguishes_builtin_progression_from_local_notes_and_maps_repairs():
    equipment, _, stored, draft = planning_case()
    draft['workouts'][0]['exercises'][0].update(progressionMethod='reps', placementNotes='Keep the body rigid.')
    messages = requirement_messages(stored)
    result = audit_workout_plan(draft, equipment, messages)
    assert result['passed']
    reviewed = plan_review._compact_review_draft(result['planIndex'], equipment, draft)
    authority = reviewed['exercises'][0]['coachingAuthority']
    assert authority['localNotes'] == 'Keep the body rigid.'
    assert 'Stop at the rep ceiling' in authority['generatedProgression']
    assert reviewed['exercises'][0]['placementNotes'] == 'Keep the body rigid.'
    assert reviewed['exercises'][0]['renderedGuidance'] == result['planIndex']['exercises'][0]['placementNotes']
    assert authority['generatedProgression'] in reviewed['exercises'][0]['renderedGuidance']
    assert plan_review._draft_patch_path('/draft/exercises/0/coachingAuthority/generatedProgression',
        result['planIndex'], draft) is None
    assert plan_review._draft_patch_path('/draft/exercises/0/renderedGuidance',
        result['planIndex'], draft) is None
    assert plan_review._draft_patch_path('/draft/exercises/0/coachingAuthority/localNotes',
        result['planIndex'], draft) == '/workouts/0/exercises/0/placementNotes'
    context = plan_review._context(result, messages, equipment, None, len(messages) - 1)
    tampered = copy.deepcopy(result)
    tampered['planIndex']['exercises'][0]['placementNotes'] += ' Tampered assembled guidance.'
    tampered_context = plan_review._context(tampered, messages, equipment, None, len(messages) - 1)
    assert context['draft']['exercises'][0]['renderedGuidance'] == result['planIndex']['exercises'][0]['placementNotes']
    assert plan_review._hash(context) != plan_review._hash(tampered_context)


def test_repair_capability_contract_keeps_native_calibration_code_owned():
    from workout_generator_pkg.repair_capabilities import repair_capability_contract
    contract = repair_capability_contract()
    assert 'calibration' not in contract['editableDimensions']
    assert contract['editableFields']['effortAcceptance'] == ['prescription']
    assert 'requiresEffortCalibration' not in contract['editableFields']
    assert 'calibrationAttempts' not in contract['editableFields']
    assert 'native_load_calibration' in contract['codeOwnedBehaviors']
    assert 'app-native requiresLoadCalibration' in contract['codeOwnedBehaviors']['native_load_calibration']


def test_repair_budgets_reach_the_real_api_wrapper(monkeypatch):
    options = planner_response_profile({'metadataOnlyRepair': True})
    calls = []
    def chat(*args, **kwargs):
        calls.append(kwargs)
        return 'done', None, None
    monkeypatch.setattr(api_client, 'chat_call', chat)
    assert api_client.chat_call_with_loading(None, [], **options) == ('done', None, None)
    assert calls == [{'reasoning_effort': None, 'max_tokens': 2048, 'timeout': None}]
    assert planner_response_profile({'repairTask': {'baseDraftId': 'REVISION_1'}})['max_tokens'] == 16384


def test_mixed_preparation_errors_keep_structural_repair_budget():
    task = {'metadataFields': {'/sessions/0/description': {'maximumCharacters': 100}},
            'errors': [{'code': 'export_description_too_long', 'path': '/sessions/0/description'}]}
    assert planner_response_profile({'preparationRepairTask': task})['max_tokens'] == 2048
    task['errors'].append({'code': 'infeasible_set_allocation', 'path': '/sessions'})
    profile = planner_response_profile({'preparationRepairTask': task})
    assert profile['max_tokens'] == 16384 and profile['reasoning_effort'] == 'low'


@pytest.mark.parametrize('mixed', [False, True])
def test_shell_advertises_structural_patches_for_mixed_repairs(monkeypatch, tmp_path, mixed):
    from workout_generator_pkg import interactive_shell
    from test_workout_generator_conversation_sessions import make_shell_deps, run_shell
    task = {'metadataFields': {'/sessions/0/description': {'maximumCharacters': 100}},
            'errors': [{'code': 'export_description_too_long', 'path': '/sessions/0/description'}]}
    if mixed:
        task['errors'].append({'code': 'infeasible_set_allocation', 'path': '/sessions'})
    monkeypatch.setattr(interactive_shell, 'request_planning_state', lambda messages: {'preparationRepairTask': task})
    deps = make_shell_deps(tmp_path, chat_results=[], generation_results=[], generation_calls=[])
    advertised = []
    def capture(client, messages, tools, logger, **options):
        advertised.extend(tools)
        return 'Repair needs attention.', None, None
    deps.chat_call_with_loading = capture
    run_shell(monkeypatch, deps, ['Repair the preparation', '/exit'])
    schema = next(tool['function']['parameters'] for tool in advertised
                  if tool.get('function', {}).get('name') == 'prepare_workout_sessions')
    patch = {'basePreparationId': 'PREPARATION_1', 'patch': [
        {'op': 'replace', 'path': '/sessions/0/exercises/0/allocationBounds/maximum', 'value': 12}]}
    if mixed:
        validate(patch, schema)
    else:
        with pytest.raises(ValidationError):
            validate(patch, schema)


def test_retained_candidate_allocation_repair_hides_question_but_uncertainty_keeps_it():
    from pathlib import Path
    from workout_generator_pkg.interactive_shell import _preparation_repair_tools

    root = Path(__file__).resolve().parents[1]
    saved = next((root / 'build/workout_joint_priority_solver_20261023/fresh_e2e_role_keys'
        / 'workouts/conversation_sessions').glob('*/messages.json'))
    messages = json.loads(saved.read_text(encoding='utf-8'))
    task = session_drafting.preparation_repair_task(messages)
    assert task and len(task['errors']) == 1
    assert task['errors'][0]['code'] == 'infeasible_set_allocation'
    assert task['errors'][0]['owner'] == 'candidate'
    assert 'ask_user' not in [tool['function']['name'] for tool in _preparation_repair_tools(task)]

    uncertain = copy.deepcopy(task)
    uncertain['errors'] = [{
        'code': 'prepared_design_finding', 'sourceCode': 'training_load_suitability_unresolved',
        'basis': 'uncertainty', 'action': 'change', 'check': 'load_suitability',
    }]
    assert 'ask_user' in [tool['function']['name'] for tool in _preparation_repair_tools(uncertain)]


@pytest.mark.parametrize('mode, expected_calls', [('progress', 2), ('changing', 3), ('unchanged', 1)])
def test_worker_repair_tracks_proposal_progress_and_has_a_total_limit(monkeypatch, mode, expected_calls):
    from workout_generator_pkg import interactive_shell
    from workout_generator_pkg.planner_context import request_planning_state
    from test_workout_generator_parallel_planning import week_case
    equipment, messages, prepared, exercises = week_case()
    state = request_planning_state(interactive_shell._messages_for_api(messages, True, provided_equipment=equipment))
    repairs = []
    def respond(client, request, **options):
        payload = json.loads(request[-1]['content'])
        if 'permittedPaths' in payload:
            repairs.append(payload)
            value = ('x' * (510 + len(repairs)) if len(repairs) == 1 else 'Controlled execution.') if mode == 'progress' else (
                'x' * (510 + len(repairs)) if mode == 'changing' else 'x' * 505)
            return json.dumps({'patch': [{'op': 'replace', 'path': '/workouts/0/exercises/0/placementNotes',
                                         'value': value}]}), None, None
        selection = payload['session']
        values = copy.deepcopy(exercises)
        if selection['name'] == 'Session 0':
            values[0]['placementNotes'] = 'x' * 505
        return json.dumps({**selection, 'exercises': values}), None, None
    monkeypatch.setattr(plan_review, 'review_week_structure', lambda *args, **kwargs: {'passed': True, 'findings': []})
    monkeypatch.setattr(session_drafting, 'chat_call', respond)
    result = session_drafting.draft_workout_sessions(None, {'preparationId': prepared['preparationId']}, messages, equipment, state)
    assert len(repairs) == expected_calls
    assert ('proposedSubmission' in result) is (mode == 'progress')


@pytest.mark.parametrize('metadata, expected_calls', [(True, 3), (False, 40)])
def test_shell_stops_bounded_repair_work_and_saves_feedback(monkeypatch, tmp_path, capsys, metadata, expected_calls):
    from test_workout_generator_conversation_sessions import (
        FakeFunction, FakeToolCall, make_shell_deps, run_shell, load_active_conversation_record,
    )
    calls = [FakeToolCall(str(index), 'function', FakeFunction('audit_workout_plan', json.dumps({'attempt': index})))
             for index in range(41)]
    deps = make_shell_deps(tmp_path, chat_results=[('', [call]) for call in calls],
                           generation_results=[], generation_calls=[])
    attempts = []
    def reject(*args, **kwargs):
        attempts.append(len(attempts))
        error = {'code': 'export_notes_too_long' if metadata else 'invalid_arguments',
                 'path': '/workouts/0/exercises/0/placementNotes' if metadata else '/workouts/0',
                 'message': f'Unresolved attempt {len(attempts)}'}
        return {'result': json.dumps({'passed': False, 'errors': [error]}),
                'should_exit': False, 'generation_result': None}
    deps.handle_function_call = reject
    run_shell(monkeypatch, deps, ['Repair my draft', '/exit'])
    assert len(attempts) == expected_calls
    expected_reason = 'Text repair failed three times' if metadata else '40-round work budget'
    assert expected_reason in capsys.readouterr().out
    saved = load_active_conversation_record(str(tmp_path))['messages']
    feedback = [json.loads(message['content']) for message in saved if message['role'] == 'tool']
    assert len(feedback) == expected_calls and feedback[-1]['errors']


def test_pending_question_reply_keeps_repair_task_on_stable_edit_route():
    from workout_generator_pkg.interactive_shell import _active_draft_edit_route
    from workout_generator_pkg.planning_tools import coordinated_repair_tool

    draft = {'workouts': [{'name': 'Full Body A', 'exercises': [
        {'definition_id': 'LIBRARY_1', 'numWorkSets': 2},
        {'definition_id': 'LIBRARY_2', 'numWorkSets': 2},
    ]}]}
    repair_task = {'requirementsId': 'REQ_1', 'baseDraftId': 'REVISION_2',
        'findingsAssessment': {'groups': [{'disposition': 'repair', 'findingIndexes': [0],
            'repairDimensions': ['exercise_selection'], 'repairObjectives': []}]},
        'currentDraft': draft}
    active_task, sparse = _active_draft_edit_route({
        'newInstructionPending': True, 'planningDecisionNeeded': True,
    }, repair_task)
    assert active_task is repair_task and sparse
    schema = coordinated_repair_tool({**active_task, 'preferSparseEdits': sparse})['function']['parameters']
    assert 'edits' in schema['properties']
    assert 'sessionBlocks' not in schema['properties']
    assert 'patch' not in schema['properties']
