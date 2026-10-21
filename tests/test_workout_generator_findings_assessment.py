import copy
import json
import pytest
from jsonschema import ValidationError
from workout_generator_pkg import review_assessment as assessment, plan_review
from workout_generator_pkg.planning_tools import audit_workout_plan
from test_workout_generator_planning_tools import planning_case, requirement_messages


def test_repair_round_cap_stops_the_current_llm_turn():
    from workout_generator_pkg.interactive_shell import _repair_cap_pause, _unchanged_repair_failure_pause

    assert _repair_cap_pause([{'code': 'repair_round_cap_reached', 'repair': 'Stop and preserve the draft.'}]) == 'Stop and preserve the draft.'
    assert _repair_cap_pause([{'code': 'invalid_patch'}]) is None
    task = {'baseDraftId': 'REVISION_4'}
    feedback = {'passed': False, 'currentDraftId': 'REVISION_4', 'errors': [{'code': 'invalid_arguments'}]}
    messages = []
    for index in range(3):
        call_id = f'repair-{index}'
        messages.extend([
            {'role': 'assistant', 'tool_calls': [{'id': call_id, 'function': {'name': 'audit_workout_plan',
                'arguments': json.dumps({'baseDraftId': 'REVISION_4', 'patch': [{'op': 'replace',
                    'path': '/workouts/0/description', 'value': 'Updated focus'}]})}}]},
            {'role': 'tool', 'tool_call_id': call_id, 'content': json.dumps(feedback)},
        ])
    assert 'Three coordinated repair submissions' in _unchanged_repair_failure_pause(task, feedback, messages)


def _alternative_repair_failures(candidate_ids, *, statuses=None):
    messages = []
    statuses = statuses or ['repair_failed'] * len(candidate_ids)
    for index, (candidate_id, status) in enumerate(zip(candidate_ids, statuses)):
        call_id = f'alternative-repair-{index}'
        result = {'passed': False, 'tool': 'repair_workout_alternative', 'attemptStatus': status,
            'repairCandidateId': candidate_id, 'errors': [{'code': 'invalid_arguments'}]}
        messages.extend([
            {'role': 'assistant', 'tool_calls': [{'id': call_id, 'function': {
                'name': 'repair_workout_alternative', 'arguments': json.dumps({'repairCandidateId': candidate_id})}}]},
            {'role': 'tool', 'tool_call_id': call_id, 'content': json.dumps(result)},
        ])
    return messages


def test_capability_pause_does_not_block_a_current_alternative_for_stale_source_findings():
    from workout_generator_pkg.interactive_shell import _repair_capability_pause

    assert _repair_capability_pause({
        'repairCapabilityUnresolved': {'currentDraftId': 'SOURCE', 'findingIndexes': [2]},
        'alternativeRepairTask': {'repairCandidateId': 'CURRENT_ALT'},
    }) is None
    paused = _repair_capability_pause({'alternativeRepairCapabilityUnresolved': {
        'repairCandidateId': 'CURRENT_ALT', 'findingIndexes': [1]}})
    assert 'CURRENT_ALT' in paused and 'findings 1' in paused and 'no impossibility was established' in paused


def test_proven_infeasible_alternative_menu_pauses_only_after_three_matching_solver_fingerprints():
    from workout_generator_pkg.interactive_shell import _unchanged_repair_failure_pause

    candidate_id = 'ALT_1'
    messages = []
    for index, fingerprint in enumerate(('MENU_A', 'MENU_A', 'MENU_B')):
        call_id = f'infeasible-{index}'
        messages.extend([
            {'role': 'assistant', 'tool_calls': [{'id': call_id, 'function': {
                'name': 'repair_workout_alternative', 'arguments': json.dumps({'repairCandidateId': candidate_id})}}]},
            {'role': 'tool', 'tool_call_id': call_id, 'content': json.dumps({
                'passed': False, 'attemptStatus': 'repair_menu_infeasible', 'repairCandidateId': candidate_id,
                'jointSolve': {'status': 'infeasible', 'problemFingerprint': fingerprint},
                'errors': [{'code': 'joint_menu_infeasible'}]})},
        ])
    feedback = json.loads(messages[-1]['content'])
    assert _unchanged_repair_failure_pause({'repairCandidateId': candidate_id}, feedback, messages) is None

    call_id = 'infeasible-3'
    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': call_id, 'function': {
            'name': 'repair_workout_alternative', 'arguments': json.dumps({'repairCandidateId': candidate_id})}}]},
        {'role': 'tool', 'tool_call_id': call_id, 'content': json.dumps({
            'passed': False, 'attemptStatus': 'repair_menu_infeasible', 'repairCandidateId': candidate_id,
            'jointSolve': {'status': 'infeasible', 'problemFingerprint': 'MENU_A'},
            'errors': [{'code': 'joint_menu_infeasible'}]})},
    ])
    feedback = json.loads(messages[-1]['content'])
    assert 'same alternative exercise menu was proven infeasible three times' in _unchanged_repair_failure_pause(
        {'repairCandidateId': candidate_id}, feedback, messages)


def test_alternative_repair_pauses_after_three_rejections_of_same_candidate():
    from workout_generator_pkg.interactive_shell import _unchanged_repair_failure_pause

    candidate_id = 'REVISION_41'
    task = {'repairCandidateId': candidate_id}
    messages = _alternative_repair_failures([candidate_id] * 3)
    feedback = json.loads(messages[-1]['content'])

    assert 'Three alternative repair submissions' in _unchanged_repair_failure_pause(
        task, feedback, messages, 0)


def test_alternative_repair_failure_guard_scopes_to_candidate_and_continue_window():
    from workout_generator_pkg.interactive_shell import _unchanged_repair_failure_pause

    old_candidate = 'REVISION_41'
    messages = _alternative_repair_failures([old_candidate] * 3)
    current_task = {'repairCandidateId': 'REVISION_42'}
    current_feedback = {'passed': False, 'attemptStatus': 'repair_failed',
        'repairCandidateId': 'REVISION_42', 'errors': [{'code': 'invalid_arguments'}]}

    assert _unchanged_repair_failure_pause(current_task, current_feedback, messages, 0) is None
    assert _unchanged_repair_failure_pause({'repairCandidateId': old_candidate},
        json.loads(messages[-1]['content']), messages, len(messages)) is None


def test_successful_alternative_repair_result_does_not_count_as_rejection():
    from workout_generator_pkg.interactive_shell import _unchanged_repair_failure_pause

    candidate_id = 'REVISION_41'
    messages = _alternative_repair_failures([candidate_id, candidate_id])
    call_id = 'alternative-repair-success'
    success = {'passed': True, 'repairCandidateId': candidate_id,
        'repairStatus': 'repaired_and_reviewed', 'proposal': {'proposalId': 'ALT_1'}}
    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': call_id, 'function': {
            'name': 'repair_workout_alternative', 'arguments': json.dumps({'repairCandidateId': candidate_id})}}]},
        {'role': 'tool', 'tool_call_id': call_id, 'content': json.dumps(success)},
    ])

    assert _unchanged_repair_failure_pause({'repairCandidateId': candidate_id}, success, messages, 0) is None


def reviewed():
    return {'inputHash': 'reviewed-input', 'findings': [
        {'severity': 'warning', 'message': 'Wrong session title.'},
        {'severity': 'warning', 'message': 'Optional preference.'},
        {'severity': 'blocking', 'message': 'Required role missing.'}]}


def test_coordinated_repair_preflight_requires_all_groups_and_matching_dimensions():
    from workout_generator_pkg.planning_tools import validate_repair_scope, PlanningInputError

    current = {'workouts': [{'name': 'Monday', 'description': 'Focus', 'exercises': [
        {'definition_id': 'LIBRARY_0', 'numWorkSets': 2, 'progressionPlan': {'kind': 'reps'},
         'superset': None, 'satisfiesCoverage': [], 'setupSeconds': 60, 'placementNotes': 'Old cue'},
        {'definition_id': 'LIBRARY_1', 'numWorkSets': 2}]}]}
    dimensions = ['progression', 'prescription', 'superset', 'coverage', 'session_timing', 'guidance', 'ordering']
    task = {'findingsAssessment': {'groups': [
        {'findingIndexes': [i], 'disposition': 'repair', 'repairDimensions': [dimension]}
        for i, dimension in enumerate(dimensions)]},
        'reviewFindings': [{'draftPath': '/workouts/0/exercises/0/placementNotes'} for _ in dimensions]}
    label_only = {'requirementsId': 'REQ', 'baseDraftId': 'REVISION_1',
        'addressedFindingIndexes': list(range(len(dimensions))),
        'patch': [{'op': 'replace', 'path': '/workouts/0/name', 'value': 'New label'}]}
    with pytest.raises(PlanningInputError, match='matching structured field'):
        validate_repair_scope(label_only, task, current)

    complete = {'requirementsId': 'REQ', 'baseDraftId': 'REVISION_1',
        'addressedFindingIndexes': list(range(len(dimensions))), 'patch': [
            {'op': 'replace', 'path': '/workouts/0/exercises/0/progressionPlan', 'value': {'kind': 'load'}},
            {'op': 'replace', 'path': '/workouts/0/exercises/0/numWorkSets', 'value': 3},
            {'op': 'replace', 'path': '/workouts/0/exercises/0/superset', 'value': 'PAIR'},
            {'op': 'replace', 'path': '/workouts/0/exercises/0/satisfiesCoverage', 'value': ['push']},
            {'op': 'replace', 'path': '/workouts/0/exercises/0/setupSeconds', 'value': 90},
            {'op': 'replace', 'path': '/workouts/0/exercises/0/placementNotes', 'value': 'New cue'},
            {'op': 'move', 'from': '/workouts/0/exercises/0', 'path': '/workouts/0/exercises/1'}]}
    validated = validate_repair_scope(complete, task, current)
    assert 'addressedFindingIndexes' not in validated
    assert len(validated['patch']) == 7


def test_coordinated_repair_array_shifts_do_not_count_as_field_repairs():
    from workout_generator_pkg.planning_tools import validate_repair_scope, PlanningInputError

    current = {'workouts': [{'name': 'Monday', 'description': 'Focus', 'exercises': [
        {'definition_id': 'LIBRARY_0', 'numWorkSets': 2}, {'definition_id': 'LIBRARY_1', 'numWorkSets': 3}]}]}
    task = {'findingsAssessment': {'groups': [{'findingIndexes': [0], 'disposition': 'repair',
        'repairDimensions': ['prescription']}]}, 'reviewFindings': [{'draftPath': '/workouts/0/exercises/0/numWorkSets'}]}
    request = {'requirementsId': 'REQ', 'baseDraftId': 'REVISION_1', 'addressedFindingIndexes': [0],
        'patch': [{'op': 'move', 'from': '/workouts/0/exercises/1', 'path': '/workouts/0/exercises/0'}]}
    with pytest.raises(PlanningInputError, match='matching structured field'):
        validate_repair_scope(request, task, current)


def test_assessed_repair_scope_uses_evidence_occurrences_and_rejects_unrelated_same_workout_coverage():
    from workout_generator_pkg.planning_tools import _structured_repair_coverage, PlanningInputError

    current = {'workouts': [{'name': f'Session {day}', 'exercises': [
        {'definition_id': f'LIBRARY_{index}', 'numWorkSets': 2, 'satisfiesCoverage': []}
        for index in range(day * 10, day * 10 + 10)]} for day in range(3)]}
    task = {
        'findingsAssessment': {'groups': [{'findingIndexes': [0], 'disposition': 'repair',
            'repairDimensions': ['prescription', 'exercise_selection', 'coverage']}]},
        'reviewFindings': [{'draftPath': '/workouts/0/exercises/7', 'evidencePaths': [
            '/draft/exercises/7', '/draft/exercises/23', '/draft/exercises/25', '/audit']}],
    }
    related_repair = {
        'addressedFindingIndexes': [0],
        'patch': [
            {'op': 'replace', 'path': '/workouts/2/exercises/3/numWorkSets', 'value': 1},
            {'op': 'add', 'path': '/workouts/2/exercises/-', 'value': {
                'definition_id': 'LIBRARY_99', 'numWorkSets': 1}},
            {'op': 'add', 'path': '/workouts/2/exercises/10/satisfiesCoverage',
             'value': ['elbow_extension_weekly']},
        ],
    }
    related_task = {**task, '_compiledRepairOperationRefs': [
        ['EXERCISE_23', 'WORKOUT_2'],
        ['NEW_EXERCISE_TRICEPS_C', 'WORKOUT_2'],
        ['NEW_EXERCISE_TRICEPS_C', 'WORKOUT_2'],
    ]}
    _structured_repair_coverage(related_repair, related_task, current)

    unrelated_repair = {
        'addressedFindingIndexes': [0],
        'patch': [{'op': 'replace', 'path': '/workouts/0/exercises/8/satisfiesCoverage',
                   'value': ['shoulder_isolation_weekly']}],
    }
    unrelated_task = {**task, '_compiledRepairOperationRefs': [['EXERCISE_8', 'WORKOUT_0']]}
    with pytest.raises(PlanningInputError, match='matching structured field'):
        _structured_repair_coverage(unrelated_repair, unrelated_task, current)


def test_selection_repair_can_target_a_cross_session_duplicate_of_the_cited_movement_only():
    from workout_generator_pkg.planning_tools import _structured_repair_coverage, PlanningInputError

    current = {'workouts': [
        {'name': 'Session A', 'exercises': [{'definition_id': 'LIBRARY_CLOSE_GRIP', 'numWorkSets': 4}]},
        {'name': 'Session B', 'exercises': [
            {'definition_id': 'LIBRARY_CLOSE_GRIP', 'numWorkSets': 4},
            {'definition_id': 'LIBRARY_ROW', 'numWorkSets': 3},
        ]},
    ]}
    task = {'findingsAssessment': {'groups': [{'findingIndexes': [0], 'disposition': 'repair',
        'repairDimensions': ['exercise_selection']}]},
        'reviewFindings': [{'draftPath': '/workouts/0/exercises/0',
            'evidencePaths': ['/draft/exercises/0', '/draft/libraryDefinitions/LIBRARY_CLOSE_GRIP']} ]}
    related = {'addressedFindingIndexes': [0], 'patch': [
        {'op': 'replace', 'path': '/workouts/1/exercises/0/definition_id', 'value': 'LIBRARY_INCLINE'},
    ]}
    related_task = {**task, '_compiledRepairOperationRefs': [
        ['EXERCISE_1', 'WORKOUT_1']]}
    _structured_repair_coverage(related, related_task, current)

    unrelated = {**related, 'patch': [
        {'op': 'replace', 'path': '/workouts/1/exercises/1/definition_id', 'value': 'LIBRARY_INCLINE'},
    ]}
    unrelated_task = {**task, '_compiledRepairOperationRefs': [
        ['EXERCISE_2', 'WORKOUT_1']]}
    with pytest.raises(PlanningInputError, match='matching structured field'):
        _structured_repair_coverage(unrelated, unrelated_task, current)


def test_stable_coordinated_edits_compile_atomically_and_reject_stale_or_duplicate_refs():
    from workout_generator_pkg.planning_tools import (
        PlanningInputError, compile_coordinated_repair, validate_repair_scope,
    )

    _, _, _, current = planning_case()
    current['workouts'][0]['exercises'][0]['progressionMethod'] = 'doubleProgression'
    original_exercise = current['workouts'][0]['exercises'][0]
    added_exercise = copy.deepcopy(original_exercise)
    added_exercise['satisfiesCoverage'] = ['dedicated_role']
    task = {
        'baseDraftId': 'REVISION_3',
        'findingsAssessment': {'groups': [{'findingIndexes': [0], 'disposition': 'repair',
            'repairDimensions': ['coverage']}]},
        'reviewFindings': [{'draftPath': '/workouts/0/exercises/0/satisfiesCoverage'}],
    }
    arguments = {
        'requirementsId': current['requirementsId'],
        'baseDraftId': 'REVISION_3',
        'addressedFindingIndexes': [0],
        'edits': {
            'workoutUpdates': [{'workoutRef': 'WORKOUT_0', 'setFields': {'name': 'Updated focus'}}],
            'exerciseUpdates': [{'exerciseRef': 'EXERCISE_0',
                'setFields': {'placementNotes': 'Updated cue'},
                'removeOptionalFields': ['progressionMethod']}],
            'exerciseAdditions': [{'temporaryId': 'NEW_EXERCISE_extra',
                'workoutRef': 'WORKOUT_0', 'exercise': added_exercise}],
            'exerciseOrders': [{'workoutRef': 'WORKOUT_0',
                'exerciseRefs': ['NEW_EXERCISE_extra', 'EXERCISE_0']}],
        },
    }
    compiled, source_refs, reference_map = compile_coordinated_repair(
        arguments, task, current, return_reference_map=True)
    assert compiled['patch']
    assert any(item['op'] == 'remove' and item['path'].endswith('/progressionMethod')
               for item in compiled['patch'])
    assert any(item['op'] == 'move' for item in compiled['patch'])
    assert any(item['op'] == 'add' and item['path'].endswith('/satisfiesCoverage')
               for item in compiled['patch'])
    assert reference_map['workoutRefsByPosition'] == ['WORKOUT_0']
    assert reference_map['exerciseRefsByWorkout']['WORKOUT_0'] == [
        'NEW_EXERCISE_extra', 'EXERCISE_0']
    # Adding a movement can repair a coverage issue attached to an existing
    # occurrence in the same workout; it does not pretend to repair its local cues.
    validated = validate_repair_scope(compiled, {**task, '_compiledRepairOperationRefs': source_refs}, current)
    assert validated['patch']

    with pytest.raises(PlanningInputError, match='base is stale'):
        compile_coordinated_repair({**arguments, 'baseDraftId': 'REVISION_2'}, task, current)
    duplicate = copy.deepcopy(arguments)
    duplicate['edits']['exerciseUpdates'].append(copy.deepcopy(duplicate['edits']['exerciseUpdates'][0]))
    with pytest.raises(PlanningInputError, match='only once'):
        compile_coordinated_repair(duplicate, task, current)


def test_unassessed_saved_draft_repairs_use_stable_typed_edits_and_add_missing_optional_fields():
    from workout_generator_pkg.json_patching import apply_json_patch
    from workout_generator_pkg.planning_tools import (
        PlanningInputError, compile_coordinated_repair, coordinated_repair_tool, validate_repair_scope,
    )

    _, _, _, current = planning_case()
    exercise = current['workouts'][0]['exercises'][0]
    exercise.pop('setupSeconds', None)
    task = {'requirementsId': current['requirementsId'], 'baseDraftId': 'REVISION_6',
            'findingCode': 'independent_review_finding'}
    tool = coordinated_repair_tool({**task, 'currentDraft': current})['function']['parameters']
    assert 'addressedFindingIndexes' not in tool['properties']
    assert 'addressedFindingIndexes' not in tool['required']

    arguments = {'requirementsId': task['requirementsId'], 'baseDraftId': 'REVISION_6', 'edits': {
        'exerciseUpdates': [{'exerciseRef': 'EXERCISE_0',
            'setFields': {'setupSeconds': 75, 'definition_id': 'LIBRARY_1'}}]}}
    compiled, operation_refs = compile_coordinated_repair(arguments, task, current)
    assert {'op': 'add', 'path': '/workouts/0/exercises/0/setupSeconds', 'value': 75} in compiled['patch']
    assert {'op': 'replace', 'path': '/workouts/0/exercises/0/definition_id', 'value': 'LIBRARY_1'} in compiled['patch']
    validate_repair_scope(compiled, {**task, '_compiledRepairOperationRefs': operation_refs}, current)
    updated = apply_json_patch(current, compiled['patch'])
    assert updated['workouts'][0]['exercises'][0]['setupSeconds'] == 75
    assert updated['workouts'][0]['exercises'][0]['definition_id'] == 'LIBRARY_1'
    assert all('EXERCISE_' not in str(item) for item in updated['workouts'])

    with pytest.raises(PlanningInputError, match='stale'):
        compile_coordinated_repair({**arguments, 'baseDraftId': 'REVISION_5'}, task, current)


def test_rejected_typed_repair_is_amended_by_default_and_can_be_explicitly_replaced():
    from workout_generator_pkg.json_patching import apply_json_patch
    from workout_generator_pkg.planning_tools import compile_coordinated_repair, coordinated_repair_tool

    _, _, _, current = planning_case()
    requirements_id = current['requirementsId']
    previous = {
        'workoutUpdates': [{'workoutRef': 'WORKOUT_0', 'setFields': {'description': 'Retained focus'}}],
        'exerciseUpdates': [{'exerciseRef': 'EXERCISE_0', 'setFields': {'setupSeconds': 45}}],
    }
    task = {'requirementsId': requirements_id, 'baseDraftId': 'REVISION_8',
        'rejectedCoordinatedRepair': {
            'requirementsId': requirements_id, 'baseDraftId': 'REVISION_8', 'currentDraftId': 'REVISION_8',
            'submittedEdits': previous,
        }}
    schema = coordinated_repair_tool({**task, 'currentDraft': current})['function']['parameters']
    assert 'replaceRejectedRepair' in schema['properties']
    correction = {'requirementsId': requirements_id, 'baseDraftId': 'REVISION_8', 'edits': {
        'exerciseUpdates': [{'exerciseRef': 'EXERCISE_0', 'setFields': {
            'setupSeconds': 90, 'placementNotes': 'Corrected cue'}}]}}
    compiled, _ = compile_coordinated_repair(correction, task, current)
    updated = apply_json_patch(current, compiled['patch'])
    assert updated['workouts'][0]['description'] == 'Retained focus'
    assert updated['workouts'][0]['exercises'][0]['setupSeconds'] == 90
    assert updated['workouts'][0]['exercises'][0]['placementNotes'] == 'Corrected cue'
    assert correction['edits'] == {'exerciseUpdates': [{'exerciseRef': 'EXERCISE_0', 'setFields': {
        'setupSeconds': 90, 'placementNotes': 'Corrected cue'}}]}
    assert 'replaceRejectedRepair' not in correction

    replacement = {'requirementsId': requirements_id, 'baseDraftId': 'REVISION_8',
        'replaceRejectedRepair': True, 'edits': {'exerciseUpdates': [
            {'exerciseRef': 'EXERCISE_0', 'setFields': {'placementNotes': 'Full replacement'}}]}}
    replaced, _ = compile_coordinated_repair(replacement, task, current)
    replaced_candidate = apply_json_patch(current, replaced['patch'])
    assert replaced_candidate['workouts'][0].get('description') != 'Retained focus'
    assert replaced_candidate['workouts'][0]['exercises'][0]['setupSeconds'] == current['workouts'][0]['exercises'][0]['setupSeconds']
    assert task['rejectedCoordinatedRepair']['submittedEdits'] == previous


def test_rejected_typed_repair_conflicts_require_an_explicit_full_replacement():
    from workout_generator_pkg.planning_tools import PlanningInputError, compile_coordinated_repair

    _, _, _, current = planning_case()
    task = {'requirementsId': current['requirementsId'], 'baseDraftId': 'REVISION_9',
        'rejectedCoordinatedRepair': {
            'requirementsId': current['requirementsId'], 'baseDraftId': 'REVISION_9', 'currentDraftId': 'REVISION_9',
            'submittedEdits': {'exerciseRemovals': ['EXERCISE_0']},
        }}
    correction = {'requirementsId': current['requirementsId'], 'baseDraftId': 'REVISION_9', 'edits': {
        'exerciseUpdates': [{'exerciseRef': 'EXERCISE_0', 'setFields': {'placementNotes': 'Keep this movement'}}]}}
    with pytest.raises(PlanningInputError, match='cannot be updated or removed more than once'):
        compile_coordinated_repair(correction, task, current)
    correction['replaceRejectedRepair'] = True
    compiled, _ = compile_coordinated_repair(correction, task, current)
    assert any(operation['path'].endswith('/placementNotes') for operation in compiled['patch'])
    assert task['rejectedCoordinatedRepair']['submittedEdits']['exerciseRemovals'] == ['EXERCISE_0']


def test_malformed_retained_repair_is_revalidated_and_only_explicit_replacement_discards_it():
    from workout_generator_pkg.planning_tools import compile_coordinated_repair

    _, _, _, current = planning_case()
    task = {'requirementsId': current['requirementsId'], 'baseDraftId': 'REVISION_10',
        'rejectedCoordinatedRepair': {
            'requirementsId': current['requirementsId'], 'baseDraftId': 'REVISION_10', 'currentDraftId': 'REVISION_10',
            'submittedEdits': {'exerciseUpdates': [
                {'exerciseRef': 'EXERCISE_0', 'setFields': {'staleUnknownField': 'retain and diagnose'}}]},
        }}
    correction = {'requirementsId': current['requirementsId'], 'baseDraftId': 'REVISION_10', 'edits': {
        'exerciseUpdates': [{'exerciseRef': 'EXERCISE_0', 'setFields': {'placementNotes': 'Valid correction'}}]}}
    proposal_context = {}
    with pytest.raises(ValidationError) as caught:
        compile_coordinated_repair(correction, task, current, proposal_context=proposal_context)
    assert 'staleUnknownField' in str(caught.value)
    assert proposal_context['proposalCompiled'] is True
    assert proposal_context['submittedEdits']['exerciseUpdates'][0]['setFields'] == {
        'staleUnknownField': 'retain and diagnose', 'placementNotes': 'Valid correction'}
    assert correction['edits'] == {'exerciseUpdates': [
        {'exerciseRef': 'EXERCISE_0', 'setFields': {'placementNotes': 'Valid correction'}}]}

    correction['replaceRejectedRepair'] = True
    compiled, _ = compile_coordinated_repair(correction, task, current)
    assert any(operation['path'].endswith('/placementNotes') for operation in compiled['patch'])
    assert task['rejectedCoordinatedRepair']['submittedEdits']['exerciseUpdates'][0]['setFields']['staleUnknownField'] == 'retain and diagnose'


def test_invalid_correction_keeps_prior_proposal_and_next_valid_edit_amends_it():
    from workout_generator_pkg.json_patching import apply_json_patch
    from workout_generator_pkg.interactive_shell import _admit_repair_scope
    from workout_generator_pkg.planning_tools import compile_coordinated_repair

    _, _, _, current = planning_case()
    requirements_id = current['requirementsId']
    previous = {
        'workoutUpdates': [{'workoutRef': 'WORKOUT_0', 'setFields': {'description': 'Retained focus'}}],
        'exerciseUpdates': [{'exerciseRef': 'EXERCISE_0', 'setFields': {'setupSeconds': 45}}],
    }
    first_task = {'requirementsId': requirements_id, 'baseDraftId': 'REVISION_14',
        'rejectedCoordinatedRepair': {
            'requirementsId': requirements_id, 'baseDraftId': 'REVISION_14', 'currentDraftId': 'REVISION_14',
            'submittedEdits': previous,
        }}
    malformed = {'requirementsId': requirements_id, 'baseDraftId': 'REVISION_14', 'edits': {
        'exerciseUpdates': [{'exerciseRef': 'EXERCISE_0', 'setFields': {'unknownTypedField': 'bad'}}]}}
    submission = {'attemptedEdits': copy.deepcopy(malformed['edits'])}
    with pytest.raises(ValidationError):
        _admit_repair_scope(malformed, first_task, current, [], 0, 3, submission_context=submission)
    assert submission['submittedEdits'] == previous
    assert submission['attemptedEdits'] == malformed['edits']
    assert 'proposalCompiled' not in submission

    next_task = {'requirementsId': requirements_id, 'baseDraftId': 'REVISION_14',
        'rejectedCoordinatedRepair': {
            'requirementsId': requirements_id, 'baseDraftId': 'REVISION_14', 'currentDraftId': 'REVISION_14',
            'submittedEdits': submission['submittedEdits'],
        }}
    next_correction = {'requirementsId': requirements_id, 'baseDraftId': 'REVISION_14', 'edits': {
        'exerciseUpdates': [{'exerciseRef': 'EXERCISE_0', 'setFields': {'setupSeconds': 90}}]}}
    compiled, _ = compile_coordinated_repair(next_correction, next_task, current)
    updated = apply_json_patch(current, compiled['patch'])
    assert updated['workouts'][0]['description'] == 'Retained focus'
    assert updated['workouts'][0]['exercises'][0]['setupSeconds'] == 90


def test_scope_rejection_receipt_context_keeps_the_composed_proposal():
    from workout_generator_pkg.interactive_shell import _admit_repair_scope
    from workout_generator_pkg.planning_tools import PlanningInputError

    _, _, _, current = planning_case()
    task = {'requirementsId': current['requirementsId'], 'baseDraftId': 'REVISION_11',
        'rejectedCoordinatedRepair': {
            'requirementsId': current['requirementsId'], 'baseDraftId': 'REVISION_11', 'currentDraftId': 'REVISION_11',
            'submittedEdits': {'exerciseUpdates': [{'exerciseRef': 'EXERCISE_0',
                'setFields': {'setupSeconds': 45}}]},
        }}
    arguments = {'requirementsId': current['requirementsId'], 'baseDraftId': 'REVISION_11', 'edits': {
        'exerciseUpdates': [{'exerciseRef': 'EXERCISE_0', 'setFields': {'placementNotes': 'Correction'}}]}}
    submission = {'attemptedEdits': copy.deepcopy(arguments['edits'])}

    def reject_after_compilation(*_args):
        raise PlanningInputError('scope_rejected', 'Not admitted.', '/edits', 'Keep repairing the assessed scope.')

    with pytest.raises(PlanningInputError, match='Not admitted'):
        _admit_repair_scope(arguments, task, current, [], 0, 3, scope_validator=reject_after_compilation,
            submission_context=submission)
    assert submission['proposalCompiled'] is True
    assert submission['submittedEdits']['exerciseUpdates'][0]['setFields'] == {
        'setupSeconds': 45, 'placementNotes': 'Correction'}


def test_composed_structural_addition_keeps_its_order_when_later_fields_are_corrected():
    from workout_generator_pkg.planning_tools import compile_coordinated_repair

    _, _, _, current = planning_case()
    exercise = copy.deepcopy(current['workouts'][0]['exercises'][0])
    previous = {'exerciseAdditions': [{'temporaryId': 'NEW_EXERCISE_kept', 'workoutRef': 'WORKOUT_0',
        'exercise': exercise}], 'exerciseOrders': [{'workoutRef': 'WORKOUT_0',
        'exerciseRefs': ['NEW_EXERCISE_kept', 'EXERCISE_0']}]}
    task = {'requirementsId': current['requirementsId'], 'baseDraftId': 'REVISION_12',
        'rejectedCoordinatedRepair': {
            'requirementsId': current['requirementsId'], 'baseDraftId': 'REVISION_12', 'currentDraftId': 'REVISION_12',
            'submittedEdits': previous,
        }}
    correction = {'requirementsId': current['requirementsId'], 'baseDraftId': 'REVISION_12', 'edits': {
        'exerciseUpdates': [{'exerciseRef': 'EXERCISE_0', 'setFields': {'placementNotes': 'Keep the source change'}}]}}
    compiled, operation_refs, references = compile_coordinated_repair(
        correction, task, current, return_reference_map=True)
    assert references['composedEdits']['exerciseAdditions'][0]['temporaryId'] == 'NEW_EXERCISE_kept'
    assert references['composedEdits']['exerciseOrders'][0]['exerciseRefs'] == ['NEW_EXERCISE_kept', 'EXERCISE_0']
    assert any(operation['op'] == 'add' and operation['path'].endswith('/exercises/-') for operation in compiled['patch'])
    assert any(operation['op'] == 'move' for operation in compiled['patch'])
    assert any('NEW_EXERCISE_kept' in refs for refs in operation_refs)


def test_explicit_replacement_still_must_cover_every_assessed_group():
    from workout_generator_pkg.planning_tools import PlanningInputError, compile_coordinated_repair, validate_repair_scope

    _, _, _, current = planning_case()
    task = {'requirementsId': current['requirementsId'], 'baseDraftId': 'REVISION_13',
        'findingsAssessment': {'inputHash': 'assessment-input', 'groups': [
            {'findingIndexes': [0], 'disposition': 'repair', 'repairDimensions': ['guidance']},
            {'findingIndexes': [1], 'disposition': 'repair', 'repairDimensions': ['coverage']},
        ]},
        'reviewFindings': [
            {'draftPath': '/workouts/0/exercises/0/placementNotes'},
            {'draftPath': '/workouts/0/exercises/0/satisfiesCoverage'},
        ],
        'rejectedCoordinatedRepair': {
            'requirementsId': current['requirementsId'], 'baseDraftId': 'REVISION_13', 'currentDraftId': 'REVISION_13',
            'assessmentInputHash': 'assessment-input', 'submittedEdits': {'exerciseRemovals': ['EXERCISE_0']},
        }}
    replacement = {'requirementsId': current['requirementsId'], 'baseDraftId': 'REVISION_13',
        'addressedFindingIndexes': [0, 1], 'replaceRejectedRepair': True, 'edits': {
            'exerciseUpdates': [{'exerciseRef': 'EXERCISE_0', 'setFields': {'placementNotes': 'Complete guidance'}}]}}
    compiled, operation_refs = compile_coordinated_repair(replacement, task, current)
    with pytest.raises(PlanningInputError, match='matching structured field'):
        validate_repair_scope(compiled, {**task, '_compiledRepairOperationRefs': operation_refs}, current)


def test_typed_repair_schema_feedback_preserves_all_errors_and_shows_correct_sibling_location():
    from workout_generator_pkg.planning_tools import (
        compile_coordinated_repair, planning_tool_failure,
    )

    _, _, _, current = planning_case()
    task = {'requirementsId': current['requirementsId'], 'baseDraftId': 'REVISION_6'}
    arguments = {'requirementsId': task['requirementsId'], 'baseDraftId': task['baseDraftId'], 'edits': {
        'exerciseUpdates': [
            {'exerciseRef': 'EXERCISE_0', 'setFields': {
                'numWorkSets': 10, 'removeOptionalFields': ['progressionMethod']}},
            {'exerciseRef': 'EXERCISE_99', 'setFields': {'numWorkSets': 10}},
        ]}}
    before = copy.deepcopy(current)
    with pytest.raises(ValidationError) as caught:
        compile_coordinated_repair(arguments, task, current)
    assert current == before
    validation_errors = caught.value.validation_errors
    assert len(validation_errors) >= 2
    feedback = planning_tool_failure('audit_workout_plan', caught.value, arguments)
    messages = json.dumps(feedback['errors'])
    assert '/edits/exerciseUpdates/0/setFields' in messages
    assert 'EXERCISE_0' in messages
    assert 'removeOptionalFields' in messages
    assert '/edits/exerciseUpdates/0/removeOptionalFields' in messages
    assert 'Schema-shaped example' in messages
    assert 'EXERCISE_99' in messages
    assert feedback['instruction'].startswith('Follow errors[].repair')



def test_out_of_range_set_repair_names_prescription_fields_and_preserves_rep_range():
    from workout_generator_pkg.planning_tools import planning_tool_failure

    equipment, _, stored, draft = planning_case()
    exercise = draft['workouts'][0]['exercises'][0]
    exercise['minReps'], exercise['maxReps'] = 10, 12
    exercise['workSetTemplate'] = {'reps': 8}
    with pytest.raises(ValueError) as caught:
        audit_workout_plan(draft, equipment, requirement_messages(stored))
    feedback = planning_tool_failure('audit_workout_plan', caught.value, draft)
    error = next(item for item in feedback['errors'] if item['code'] == 'target_set_prescription_outside_rep_range')
    assert error['path'] == '/workouts/0/exercises/0/workSetTemplate/reps'
    assert '10–12 unchanged' in error['repair']
    assert 'Correct workSetTemplate.reps' in error['repair']
    assert 'Do not change minReps/maxReps' in error['repair']

    indexed_draft = copy.deepcopy(draft)
    indexed_exercise = indexed_draft['workouts'][0]['exercises'][0]
    indexed_exercise.pop('workSetTemplate')
    indexed_exercise['targetSetPrescriptions'] = [
        {'workSetIndex': index, 'reps': 8}
        for index in range(indexed_exercise['numWorkSets'])]
    with pytest.raises(ValueError) as indexed_caught:
        audit_workout_plan(indexed_draft, equipment, requirement_messages(stored))
    indexed_feedback = planning_tool_failure('audit_workout_plan', indexed_caught.value, indexed_draft)
    indexed_error = next(item for item in indexed_feedback['errors']
        if item['code'] == 'target_set_prescription_outside_rep_range')
    assert indexed_error['path'] == '/workouts/0/exercises/0/targetSetPrescriptions/0/reps'
    assert 'Correct targetSetPrescriptions workSetIndex=0 reps' in indexed_error['repair']


def test_typed_repair_advertises_current_description_cap_without_rejecting_schedule_edits():
    from workout_generator_pkg.planning_tools import compile_coordinated_repair, coordinated_repair_tool

    _, _, _, current = planning_case()
    current['workouts'][0]['trainingDays'] = [0, 1]
    task = {'requirementsId': current['requirementsId'], 'baseDraftId': 'REVISION_7'}
    tool = coordinated_repair_tool({**task, 'currentDraft': current})
    description = tool['function']['parameters']['properties']['edits']['properties']
    allowed = description['workoutUpdates']['items']['properties']['setFields']['properties']['description']['description']
    assert 'WORKOUT_0=23 characters' in allowed
    proposed_description = 'A concise focus with 28 chars'  # Fits Monday but not Monday and Tuesday.
    current['workouts'][0]['description'] = 'Initial focus'
    over_limit = {'requirementsId': task['requirementsId'], 'baseDraftId': task['baseDraftId'], 'edits': {
        'workoutUpdates': [{'workoutRef': 'WORKOUT_0', 'setFields': {'description': proposed_description}}]}}
    # The tool reports the current schedule allowance, while production audit
    # validates the complete proposed schedule after the edit is applied.
    compiled_current_schedule, _ = compile_coordinated_repair(over_limit, task, current)
    assert any(operation['path'] == '/workouts/0/description' for operation in compiled_current_schedule['patch'])

    rescheduled = copy.deepcopy(over_limit)
    rescheduled['edits']['workoutUpdates'][0]['setFields']['trainingDays'] = [0]
    compiled, _ = compile_coordinated_repair(rescheduled, task, current)
    assert any(operation['path'] == '/workouts/0/trainingDays' for operation in compiled['patch'])
    assert any(operation['path'] == '/workouts/0/description' for operation in compiled['patch'])

    reordered = copy.deepcopy(current)
    second = copy.deepcopy(reordered['workouts'][0])
    second.update(name='Second', description='Short focus', trainingDays=[2])
    reordered['workouts'].append(second)
    reordered_task = {**task, 'baseDraftId': 'REVISION_8'}
    reorder_and_edit = {'requirementsId': task['requirementsId'], 'baseDraftId': 'REVISION_8', 'edits': {
        'workoutUpdates': [{'workoutRef': 'WORKOUT_0', 'setFields': {'description': proposed_description}}],
        'workoutOrder': ['WORKOUT_1', 'WORKOUT_0']}}
    reordered_compiled, _ = compile_coordinated_repair(reorder_and_edit, reordered_task, reordered)
    assert any(operation['op'] == 'move' for operation in reordered_compiled['patch'])


def test_saved_metadata_repair_compiles_stable_refs_with_exact_path_scope_and_replays_rejected_candidate():
    from workout_generator_pkg.json_patching import apply_json_patch
    from workout_generator_pkg.planning_tools import (
        PlanningInputError, compile_coordinated_repair, coordinated_repair_tool, planning_tool_failure, validate_repair_scope,
    )

    _, _, _, saved = planning_case()
    saved['workouts'][0]['exercises'].append(copy.deepcopy(saved['workouts'][0]['exercises'][0]))
    path = '/workouts/0/exercises/0/placementNotes'
    second_path = '/workouts/0/exercises/1/placementNotes'
    rejected = {'requirementsId': saved['requirementsId'], 'baseDraftId': 'REVISION_7',
        'patch': [{'op': 'replace', 'path': path, 'value': 'Rejected source cue'}]}
    hypothetical = apply_json_patch(saved, rejected['patch'])
    task = {'requirementsId': saved['requirementsId'], 'baseDraftId': 'REVISION_7',
        'permittedPatchPaths': [path, second_path], 'metadataFields': {
            path: {'maximumCharacters': 80}, second_path: {'maximumCharacters': 25}},
        'rejectedSubmission': rejected}
    schema = coordinated_repair_tool({**task, 'currentDraft': hypothetical})['function']['parameters']['properties']['edits']['properties']
    assert set(schema) == {'exerciseUpdates'}
    variants = schema['exerciseUpdates']['items']['oneOf']
    assert [(variant['properties']['exerciseRef']['enum'],
             variant['properties']['setFields']['properties']['placementNotes']['maxLength'])
            for variant in variants] == [(['EXERCISE_0'], 80), (['EXERCISE_1'], 25)]

    too_long = {'requirementsId': task['requirementsId'], 'baseDraftId': 'REVISION_7', 'edits': {
        'exerciseUpdates': [{'exerciseRef': 'EXERCISE_1',
            'setFields': {'placementNotes': 'x' * 26}}]}}
    with pytest.raises(ValidationError) as caught:
        compile_coordinated_repair(too_long, task, hypothetical)
    scoped_feedback = planning_tool_failure('audit_workout_plan', caught.value, too_long)
    assert len(scoped_feedback['errors']) == 1
    assert scoped_feedback['errors'][0]['validator'] == 'maxLength'
    assert scoped_feedback['errors'][0]['expected'] == 25
    assert scoped_feedback['errors'][0]['textFieldContract']['maximumCharacters'] == 25

    arguments = {'requirementsId': task['requirementsId'], 'baseDraftId': 'REVISION_7', 'edits': {
        'exerciseUpdates': [{'exerciseRef': 'EXERCISE_0',
            'setFields': {'placementNotes': 'Short valid cue'}}, {'exerciseRef': 'EXERCISE_1',
            'setFields': {'placementNotes': 'Brief cue'}}]}}
    compiled, refs = compile_coordinated_repair(arguments, task, hypothetical)
    merged = validate_repair_scope(compiled, {**task, '_compiledRepairOperationRefs': refs}, hypothetical)
    assert merged['patch'] == rejected['patch'] + [
        {'op': 'replace', 'path': path, 'value': 'Short valid cue'},
        {'op': 'replace', 'path': second_path, 'value': 'Brief cue'}]
    final = apply_json_patch(saved, merged['patch'])
    assert final['workouts'][0]['exercises'][0]['placementNotes'] == 'Short valid cue'
    assert final['workouts'][0]['exercises'][1]['placementNotes'] == 'Brief cue'
    with pytest.raises(ValueError, match='outside allowed error paths'):
        validate_repair_scope({**compiled, 'patch': [{'op': 'replace',
            'path': '/workouts/0/exercises/0/numWorkSets', 'value': 2}]}, task, hypothetical)


def test_stable_coordinated_repair_moves_exercise_between_workouts_and_reorders_final_inventory():
    from workout_generator_pkg.json_patching import apply_json_patch
    from workout_generator_pkg.planning_tools import (
        PlanningInputError, compile_coordinated_repair, validate_repair_scope, coordinated_repair_tool,
    )

    _, _, _, current = planning_case()
    current['workouts'].append(copy.deepcopy(current['workouts'][0]))
    current['workouts'][1]['name'] = 'Wednesday'
    task = {
        'baseDraftId': 'REVISION_4',
        'findingsAssessment': {'groups': [{'findingIndexes': [0], 'disposition': 'repair',
            'repairDimensions': ['exercise_selection', 'ordering']}]},
        'reviewFindings': [{'draftPath': '/workouts/0/exercises/0/definition_id'}],
    }
    repair_description = coordinated_repair_tool({**task, 'currentDraft': current})['function']['description']
    assert 'WORKOUT_0: EXERCISE_0' in repair_description
    assert 'WORKOUT_1: EXERCISE_' in repair_description
    arguments = {
        'requirementsId': current['requirementsId'], 'baseDraftId': 'REVISION_4',
        'addressedFindingIndexes': [0], 'edits': {
            'exerciseUpdates': [{'exerciseRef': 'EXERCISE_0',
                'setFields': {'placementNotes': 'Preserved and revised cue.'}}],
            'exerciseMoves': [{'exerciseRef': 'EXERCISE_0', 'workoutRef': 'WORKOUT_1'}],
            'exerciseOrders': [{'workoutRef': 'WORKOUT_1',
                'exerciseRefs': ['EXERCISE_0', 'EXERCISE_1']}],
        },
    }
    compiled, source_refs = compile_coordinated_repair(arguments, task, current)
    validate_repair_scope(compiled, {**task, '_compiledRepairOperationRefs': source_refs}, current)
    moved = apply_json_patch(current, compiled['patch'])
    assert moved['workouts'][0]['exercises'] == []
    assert [item['definition_id'] for item in moved['workouts'][1]['exercises']] == ['LIBRARY_0', 'LIBRARY_0']
    assert moved['workouts'][1]['exercises'][0]['placementNotes'] == 'Preserved and revised cue.'

    invalid = copy.deepcopy(arguments)
    invalid['edits']['exerciseMoves'].append({'exerciseRef': 'EXERCISE_0', 'workoutRef': 'WORKOUT_0'})
    with pytest.raises(PlanningInputError, match='only once'):
        compile_coordinated_repair(invalid, task, current)
    same_workout = copy.deepcopy(arguments)
    same_workout['edits']['exerciseMoves'][0]['workoutRef'] = 'WORKOUT_0'
    with pytest.raises(PlanningInputError, match='must change its workout'):
        compile_coordinated_repair(same_workout, task, current)
    same_workout['edits']['exerciseOrders'] = [{'workoutRef': 'WORKOUT_0',
        'exerciseRefs': [f'EXERCISE_{index}' for index in range(len(current['workouts'][0]['exercises']))]}]
    compiled, _ = compile_coordinated_repair(same_workout, task, current)
    assert not any(operation['op'] == 'move' for operation in compiled['patch'])


def test_compact_audit_context_preserves_coordinated_repair_receipt():
    from workout_generator_pkg.interactive_shell import _messages_for_api

    receipt = {'status': 'attempted_pending_validation', 'requirementsId': 'REQ',
        'baseDraftId': 'REVISION_2', 'currentDraftId': 'REVISION_3',
        'assessmentInputHash': 'assessment-input', 'assessmentHash': 'assessment',
        'libraryFingerprint': 'library', 'historyFingerprint': 'history',
        'resolvedDecisions': {'D1': 'yes'}, 'submittedEdits': {'exerciseMoves': []}}
    findings = [{'draftPath': '/workouts/0/exercises/0', 'message': 'Repair this occurrence.'}]
    messages = [
        {'role': 'assistant', 'tool_calls': [{'id': 'audit', 'function': {
            'name': 'audit_workout_plan', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'audit', 'content': json.dumps({
            'passed': False, 'currentDraftId': 'REVISION_3', 'audit': {},
            'coordinatedRepairReceipt': receipt, 'review': {'findings': findings},
            'submittedDraft': {'workouts': []}})},
    ]
    outgoing = _messages_for_api(messages)
    compact = json.loads(outgoing[-1]['content'])
    assert compact['coordinatedRepairReceipt'] == receipt
    assert compact['reviewFindings'] == findings
    assert 'submittedDraft' not in compact

    marked = [{'role': 'assistant', '_internalAuditActions': {'reaudit': 'deterministic_metadata_correction'},
        'tool_calls': [{'id': 'reaudit', 'function': {'name': 'audit_workout_plan', 'arguments': '{}'}}]}]
    assert '_internalAuditActions' not in _messages_for_api(marked)[0]


def test_exercise_order_accepts_relative_sequence_and_preserves_omitted_source_order():
    from workout_generator_pkg.json_patching import apply_json_patch
    from workout_generator_pkg.planning_tools import (
        PlanningInputError, compile_coordinated_repair,
    )

    _, _, _, current = planning_case()
    exercise_a = current['workouts'][0]['exercises'][0]
    exercise_a['placementNotes'] = 'source A'
    exercise_b = copy.deepcopy(exercise_a)
    exercise_b.update(definition_id='LIBRARY_1', placementNotes='source B')
    exercise_c = copy.deepcopy(exercise_a)
    exercise_c.update(definition_id='LIBRARY_2', placementNotes='source C')
    current['workouts'][0]['exercises'] = [exercise_a, exercise_b, exercise_c]
    task = {'baseDraftId': 'REVISION_5', 'findingsAssessment': {'groups': []}}
    arguments = {'requirementsId': current['requirementsId'], 'baseDraftId': 'REVISION_5',
        'addressedFindingIndexes': [], 'edits': {'exerciseOrders': [
            {'workoutRef': 'WORKOUT_0', 'exerciseRefs': ['EXERCISE_2', 'EXERCISE_0']}]}}
    compiled, _ = compile_coordinated_repair(arguments, task, current)
    reordered = apply_json_patch(current, compiled['patch'])
    assert [item['placementNotes'] for item in reordered['workouts'][0]['exercises']] == [
        'source B', 'source C', 'source A']

    unknown = copy.deepcopy(arguments)
    unknown['edits']['exerciseOrders'][0]['exerciseRefs'] = ['EXERCISE_99']
    with pytest.raises(PlanningInputError, match='reference absent'):
        compile_coordinated_repair(unknown, task, current)
    repeated = copy.deepcopy(arguments)
    repeated['edits']['exerciseOrders'].append(copy.deepcopy(repeated['edits']['exerciseOrders'][0]))
    with pytest.raises(PlanningInputError, match='at most one'):
        compile_coordinated_repair(repeated, task, current)
    empty = copy.deepcopy(arguments)
    empty['edits']['exerciseOrders'][0]['exerciseRefs'] = []
    with pytest.raises(ValidationError):
        compile_coordinated_repair(empty, task, current)


def test_coordinated_admission_reports_order_ownership_with_schema_errors():
    from workout_generator_pkg.planning_tools import compile_coordinated_repair, planning_tool_failure

    _, _, _, current = planning_case()
    current['workouts'].extend(copy.deepcopy(current['workouts'][0]) for _ in range(2))
    task = {'baseDraftId': 'REVISION_22', 'findingsAssessment': {'groups': []}}
    arguments = {'requirementsId': current['requirementsId'], 'baseDraftId': 'REVISION_22',
        'addressedFindingIndexes': [], 'edits': {
            'workoutUpdates': [{'workoutRef': f'WORKOUT_{index}', 'setFields': {
                'description': 'x' * 80}} for index in range(3)],
            'exerciseOrders': [
                {'workoutRef': 'WORKOUT_0', 'exerciseRefs': ['EXERCISE_0']},
                {'workoutRef': 'WORKOUT_1', 'exerciseRefs': ['EXERCISE_1', 'EXERCISE_2']},
                {'workoutRef': 'WORKOUT_2', 'exerciseRefs': ['EXERCISE_0', 'EXERCISE_2']},
            ]}}

    with pytest.raises(ValidationError) as raised:
        compile_coordinated_repair(arguments, task, current)
    result = planning_tool_failure('repair_workout_alternative', raised.value, arguments)
    assert len([error for error in result['errors'] if error['code'] == 'invalid_arguments']) == 3
    ownership_errors = [error for error in result['errors']
        if error['code'] == 'unknown_exercise_order_reference']
    assert [(error['workoutRef'], error['offendingReferences'], error['availableReferences'])
        for error in ownership_errors] == [
            ('WORKOUT_1', ['EXERCISE_2'], ['EXERCISE_1']),
            ('WORKOUT_2', ['EXERCISE_0'], ['EXERCISE_2']),
        ]


def test_coordinated_admission_identifies_cross_workout_order_reference():
    from workout_generator_pkg.planning_tools import PlanningInputError, compile_coordinated_repair

    _, _, _, current = planning_case()
    current['workouts'].append(copy.deepcopy(current['workouts'][0]))
    task = {'baseDraftId': 'REVISION_23', 'findingsAssessment': {'groups': []}}
    arguments = {'requirementsId': current['requirementsId'], 'baseDraftId': 'REVISION_23',
        'addressedFindingIndexes': [], 'edits': {'exerciseOrders': [
            {'workoutRef': 'WORKOUT_0', 'exerciseRefs': ['EXERCISE_0', 'EXERCISE_1']}]}}

    with pytest.raises(PlanningInputError) as raised:
        compile_coordinated_repair(arguments, task, current)
    error = raised.value.errors[0]
    assert error['workoutRef'] == 'WORKOUT_0'
    assert error['offendingReferences'] == ['EXERCISE_1']
    assert error['availableReferences'] == ['EXERCISE_0']
    assert error['path'] == '/edits/exerciseOrders/0/exerciseRefs'


def test_coordinated_admission_does_not_misdiagnose_order_for_schema_invalid_addition():
    from workout_generator_pkg.planning_tools import compile_coordinated_repair, planning_tool_failure

    _, _, _, current = planning_case()
    current['workouts'].append(copy.deepcopy(current['workouts'][0]))
    task = {'baseDraftId': 'REVISION_24', 'findingsAssessment': {'groups': []}}
    added = copy.deepcopy(current['workouts'][0]['exercises'][0])
    added['intraSetRestPerExerciseSeconds'] = 15
    arguments = {'requirementsId': current['requirementsId'], 'baseDraftId': 'REVISION_24',
        'addressedFindingIndexes': [], 'edits': {
            'exerciseAdditions': [{'temporaryId': 'NEW_EXERCISE_C1', 'workoutRef': 'WORKOUT_1',
                'exercise': added}],
            'exerciseOrders': [{'workoutRef': 'WORKOUT_1',
                'exerciseRefs': ['EXERCISE_1', 'NEW_EXERCISE_C1']}],
        }}

    with pytest.raises(ValidationError) as raised:
        compile_coordinated_repair(arguments, task, current)
    result = planning_tool_failure('repair_workout_alternative', raised.value, arguments)
    assert [error['code'] for error in result['errors']] == ['invalid_arguments']
    assert "intraSetRestPerExerciseSeconds" in result['errors'][0]['message']


def test_program_guidance_is_canonical_manual_preview_text_not_plan_index_metadata():
    from workout_generator_pkg.planning_tools import audit_workout_plan

    equipment, _, stored, draft = planning_case()
    draft['programGuidance'] = 'During recovery weeks, keep the approved exercises and reduce effort if needed.'
    result = audit_workout_plan(draft, equipment, requirement_messages(stored))

    assert result['submittedDraft']['programGuidance'] == draft['programGuidance']
    assert '## Program guidance (manual reference)' in result['preview']
    assert draft['programGuidance'] in result['preview']
    assert 'programGuidance' not in result['planIndex']


def test_program_guidance_typed_edit_scopes_and_replays_as_a_scalar_last_write():
    from workout_generator_pkg.json_patching import apply_json_patch
    from workout_generator_pkg.planning_tools import (
        PlanningInputError, compile_coordinated_repair, validate_repair_scope,
    )

    _, _, _, current = planning_case()
    requirements_id = current['requirementsId']
    task = {'requirementsId': requirements_id, 'baseDraftId': 'REVISION_31',
        'findingsAssessment': {'groups': [{'findingIndexes': [0], 'disposition': 'repair',
            'repairDimensions': ['program_guidance']}]},
        'reviewFindings': [{'draftPath': '/draft/programGuidance',
            'message': 'Add a program-wide recovery instruction.'}]}
    task['rejectedCoordinatedRepair'] = {'status': 'rejected_before_materialization',
        'requirementsId': requirements_id, 'baseDraftId': 'REVISION_31',
        'currentDraftId': 'REVISION_31', 'submittedEdits': {'programGuidance': 'Old recovery note.'}}
    arguments = {'requirementsId': requirements_id, 'baseDraftId': 'REVISION_31',
        'addressedFindingIndexes': [0], 'edits': {'programGuidance': 'Updated recovery note.'}}

    compiled, operation_refs = compile_coordinated_repair(arguments, task, current)
    validate_repair_scope(compiled, {**task, '_compiledRepairOperationRefs': operation_refs}, current)
    updated = apply_json_patch(current, compiled['patch'])
    assert updated['programGuidance'] == 'Updated recovery note.'
    assert compiled['patch'] == [{'op': 'add', 'path': '/programGuidance', 'value': 'Updated recovery note.'}]
    assert operation_refs == [[]]

    blank = copy.deepcopy(arguments)
    blank['edits']['programGuidance'] = '   '
    with pytest.raises(PlanningInputError, match='must contain user-facing text'):
        compile_coordinated_repair(blank, task, current)


def test_repair_round_budget_counts_changed_submissions_once_after_attempt_start():
    from workout_generator_pkg.interactive_shell import _repair_attempt_counts

    base = {'requirementsId': 'REQ', 'name': 'Week', 'workouts': [{'name': 'Monday', 'exercises': []}]}
    changed = copy.deepcopy(base)
    changed['workouts'][0]['name'] = 'Monday strength'
    unchanged = copy.deepcopy(changed)
    messages = [
        {'role': 'assistant', 'tool_calls': [{'id': 'initial', 'function': {'name': 'audit_workout_plan',
            'arguments': json.dumps(base)}}]},
        {'role': 'tool', 'tool_call_id': 'initial', 'content': json.dumps({'submittedDraft': base, 'currentDraftId': 'REVISION_0',
            'passed': False, 'review': {'assessment': {'groups': [{'disposition': 'repair'}]}}})},
        {'role': 'assistant', 'tool_calls': [{'id': 'repair1', 'function': {'name': 'audit_workout_plan',
            'arguments': json.dumps({'patch': [{'op': 'replace', 'path': '/workouts/0/name', 'value': 'Monday strength'}]})}}]},
        {'role': 'tool', 'tool_call_id': 'repair1', 'content': json.dumps({'submittedDraft': changed, 'currentDraftId': 'REVISION_1'})},
        {'role': 'tool', 'tool_call_id': 'repair1', 'content': json.dumps({'submittedDraft': changed, 'currentDraftId': 'REVISION_1'})},
        {'role': 'assistant', 'tool_calls': [{'id': 'repair2', 'function': {'name': 'audit_workout_plan',
            'arguments': json.dumps({'patch': [{'op': 'replace', 'path': '/workouts/0/name', 'value': 'Monday strength'}]})}}]},
        {'role': 'tool', 'tool_call_id': 'repair2', 'content': json.dumps({'submittedDraft': unchanged, 'currentDraftId': 'REVISION_1'})},
        {'role': 'assistant', 'tool_calls': [{'id': 'repair3', 'function': {'name': 'audit_workout_plan',
            'arguments': json.dumps({'workouts': [{'name': 'Monday strength 2', 'exercises': []}]})}}]},
        {'role': 'tool', 'tool_call_id': 'repair3', 'content': json.dumps({'submittedDraft': {
            'requirementsId': 'REQ', 'name': 'Week', 'workouts': [{'name': 'Monday strength 2', 'exercises': []}]},
            'currentDraftId': 'REVISION_2'})},
        {'role': 'assistant', 'tool_calls': [{'id': 'repair4', 'function': {'name': 'audit_workout_plan',
            'arguments': json.dumps({'edits': {'exerciseUpdates': [{'exerciseRef': 'EXERCISE_0',
                'setFields': {'numWorkSets': 2}}]}})}}]},
        {'role': 'tool', 'tool_call_id': 'repair4', 'content': json.dumps({'submittedDraft': {
            'requirementsId': 'REQ', 'name': 'Week', 'workouts': [{'name': 'Monday stable edits', 'exercises': []}]},
            'currentDraftId': 'REVISION_3'})},
    ]
    assert _repair_attempt_counts(messages, 2) == {'changed': 3, 'rejected': 0, 'internal': 0}
    assert _repair_attempt_counts(messages, len(messages)) == {'changed': 0, 'rejected': 0, 'internal': 0}


def test_repair_attempt_budget_counts_varying_rejected_submissions_and_resets_on_resume():
    from workout_generator_pkg.interactive_shell import _repair_attempt_counts

    messages = [
        {'role': 'assistant', 'tool_calls': [{'id': 'initial', 'function': {'name': 'audit_workout_plan',
            'arguments': json.dumps({'workouts': []})}}]},
        {'role': 'tool', 'tool_call_id': 'initial', 'content': json.dumps({'submittedDraft': {
            'requirementsId': 'REQ', 'name': 'Week', 'workouts': [{'name': 'Monday', 'exercises': []}]},
            'currentDraftId': 'REVISION_0'})},
    ]
    malformed = [
        {'patch': [{'op': 'replace', 'path': '/workouts/0/exercises/0/setupSeconds', 'value': 20}]},
        {'patch': [{'op': 'replace', 'path': '/workouts/0/exercises/0/setupSeconds', 'value': 30}], 'baseDraftId': 'OLD'},
        {'edits': {'exerciseUpdates': [{'exerciseRef': 'EXERCISE_999', 'setFields': {'setupSeconds': 40}}]}},
    ]
    for index, arguments in enumerate(malformed):
        call_id = f'rejected_{index}'
        messages.extend([
            {'role': 'assistant', 'tool_calls': [{'id': call_id, 'function': {
                'name': 'audit_workout_plan', 'arguments': json.dumps(arguments)}}]},
            {'role': 'tool', 'tool_call_id': call_id, 'content': json.dumps({'passed': False,
                'errors': [{'code': 'invalid_arguments'}], 'currentDraftId': 'REVISION_0'})},
        ])

    assert _repair_attempt_counts(messages, 2) == {'changed': 0, 'rejected': 3, 'internal': 0}
    assert _repair_attempt_counts(messages, len(messages)) == {'changed': 0, 'rejected': 0, 'internal': 0}


def test_repair_attempt_budget_counts_invalid_json_and_trusted_internal_empty_reaudit():
    from workout_generator_pkg.interactive_shell import _repair_attempt_counts

    base = {'requirementsId': 'REQ', 'name': 'Week', 'workouts': [{'name': 'Monday', 'exercises': []}]}
    messages = [
        {'role': 'assistant', '_internalAuditActions': {'saved_reaudit': 'saved_candidate_revalidation'},
         'tool_calls': [{'id': 'saved_reaudit', 'function': {'name': 'audit_workout_plan',
            'arguments': json.dumps({'requirementsId': 'REQ', 'baseDraftId': 'REVISION_0', 'patch': []})}}]},
        {'role': 'tool', 'tool_call_id': 'saved_reaudit', 'content': json.dumps({'passed': False,
            'errors': [{'code': 'volume_below_target'}], 'submittedDraft': base, 'currentDraftId': 'REVISION_0'})},
        {'role': 'assistant', 'tool_calls': [{'id': 'invalid_json', 'function': {'name': 'audit_workout_plan',
            'arguments': '{"edits":'}}]},
        {'role': 'tool', 'tool_call_id': 'invalid_json', 'content': json.dumps({'passed': False,
            'errors': [{'code': 'invalid_tool_json'}], 'currentDraftId': 'REVISION_0'})},
    ]

    assert _repair_attempt_counts(messages, 0) == {'changed': 0, 'rejected': 1, 'internal': 1}


def test_repair_budget_counts_all_alternative_proposals_without_mistaking_menu_for_candidate():
    from workout_generator_pkg.interactive_shell import _repair_attempt_counts, _repair_budget_pause

    original = {'workouts': [{'name': 'Monday', 'exercises': [{'definition_id': 'LIBRARY_1'}]}]}
    proposed_menu = copy.deepcopy(original['workouts'])
    proposed_menu[0]['exercises'][0]['definition_id'] = 'LIBRARY_2'
    snapshot = {'repairCandidateId': 'ALT_1', 'workouts': original['workouts'],
        'currentDraft': {'workouts': [{'name': 'Source', 'exercises': []}]}}
    cases = [
        ('repair_menu_infeasible', 0),
        ('joint_repair_unresolved', 1),
        ('repair_failed', 2),
        ('repair_menu_infeasible', 3),
        ('repair_failed', 4),
        ('joint_repair_unresolved', 5),
    ]
    messages = [
        {'role': 'assistant', 'tool_calls': [{'id': 'prior', 'function': {
            'name': 'repair_workout_alternative', 'arguments': json.dumps({'repairCandidateId': 'ALT_1'})}}]},
        {'role': 'tool', 'tool_call_id': 'prior', 'content': json.dumps({
            'passed': False, 'repairCandidateId': 'ALT_1', 'candidateSnapshot': snapshot,
            'attemptStatus': 'repair_failed', 'errors': [{'code': 'earlier'}]})},
    ]
    for status, index in cases:
        call_id = f'alternative-{index}'
        messages.extend([
            {'role': 'assistant', 'tool_calls': [{'id': call_id, 'function': {
                'name': 'repair_workout_alternative', 'arguments': json.dumps({'repairCandidateId': 'ALT_1'})}}]},
            {'role': 'tool', 'tool_call_id': call_id, 'content': json.dumps({
                'passed': False, 'attemptStatus': status, 'repairCandidateId': 'ALT_1',
                'candidateSnapshot': snapshot, 'workouts': proposed_menu,
                'errors': [{'code': status}]})},
        ])

    state = {'alternativeRepairTask': {'repairCandidateId': 'ALT_1'}}
    assert _repair_attempt_counts(messages, 2) == {'changed': 0, 'rejected': 6, 'internal': 0}
    assert _repair_attempt_counts(messages, len(messages)) == {'changed': 0, 'rejected': 0, 'internal': 0}
    pause = _repair_budget_pause(state, messages, 2, 3)
    assert 'used 6 of 3 model repair submissions' in pause
    assert '0 changed the candidate and 6 were rejected' in pause
    assert _repair_budget_pause(state, messages, len(messages), 3) is None


def test_alternative_repair_budget_counts_materialized_snapshot_change():
    from workout_generator_pkg.interactive_shell import _repair_attempt_counts

    source = {'repairCandidateId': 'ALT_1', 'workouts': [{'name': 'Monday', 'exercises': []}]}
    materialized = copy.deepcopy(source)
    materialized['workouts'][0]['name'] = 'Monday strength'
    messages = [
        {'role': 'assistant', 'tool_calls': [{'id': 'prior', 'function': {
            'name': 'repair_workout_alternative', 'arguments': json.dumps({'repairCandidateId': 'ALT_1'})}}]},
        {'role': 'tool', 'tool_call_id': 'prior', 'content': json.dumps({
            'passed': False, 'repairCandidateId': 'ALT_1', 'candidateSnapshot': source,
            'attemptStatus': 'repair_failed', 'errors': [{'code': 'earlier'}]})},
        {'role': 'assistant', 'tool_calls': [{'id': 'current', 'function': {
            'name': 'repair_workout_alternative', 'arguments': json.dumps({'repairCandidateId': 'ALT_1'})}}]},
        {'role': 'tool', 'tool_call_id': 'current', 'content': json.dumps({
            'passed': False, 'repairCandidateId': 'ALT_1', 'candidateSnapshot': materialized,
            'attemptStatus': 'repair_failed', 'errors': [{'code': 'materialized_change'}]})},
    ]
    assert _repair_attempt_counts(messages, 2) == {'changed': 1, 'rejected': 0, 'internal': 0}


def test_alternative_repair_submission_with_malformed_snapshot_counts_rejected():
    from workout_generator_pkg.interactive_shell import _repair_attempt_counts

    messages = [
        {'role': 'assistant', 'tool_calls': [{'id': 'alternative', 'function': {
            'name': 'repair_workout_alternative', 'arguments': json.dumps({'repairCandidateId': 'ALT_1'})}}]},
        {'role': 'tool', 'tool_call_id': 'alternative', 'content': json.dumps({
            'passed': False, 'attemptStatus': 'joint_repair_unresolved', 'candidateSnapshot': 'invalid',
            'workouts': [{'name': 'Monday', 'exercises': []}], 'errors': [{'code': 'unresolved'}]})},
    ]
    assert _repair_attempt_counts(messages, 0) == {'changed': 0, 'rejected': 1, 'internal': 0}


def test_repair_attempt_budget_separates_code_owned_metadata_audit_from_model_submissions():
    from workout_generator_pkg.interactive_shell import _model_repair_submissions_used, _repair_attempt_counts

    base = {'requirementsId': 'REQ', 'name': 'Week', 'workouts': [{'name': 'Monday', 'description': 'Long', 'exercises': []}]}
    model_changed = copy.deepcopy(base)
    model_changed['workouts'][0]['description'] = 'Short description'
    internal_changed = copy.deepcopy(model_changed)
    internal_changed['workouts'][0]['description'] = 'Strength training'
    messages = [
        {'role': 'assistant', 'tool_calls': [{'id': 'initial', 'function': {'name': 'audit_workout_plan',
            'arguments': json.dumps({'workouts': base['workouts']})}}]},
        {'role': 'tool', 'tool_call_id': 'initial', 'content': json.dumps({'submittedDraft': base, 'currentDraftId': 'REVISION_0'})},
        {'role': 'assistant', 'tool_calls': [{'id': 'rejected_1', 'function': {'name': 'audit_workout_plan', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'rejected_1', 'content': json.dumps({'passed': False, 'errors': [{'code': 'invalid_arguments'}]})},
        {'role': 'assistant', 'tool_calls': [{'id': 'rejected_2', 'function': {'name': 'audit_workout_plan', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'rejected_2', 'content': json.dumps({'passed': False, 'errors': [{'code': 'invalid_arguments'}]})},
        {'role': 'assistant', 'tool_calls': [{'id': 'model_repair', 'function': {'name': 'audit_workout_plan',
            'arguments': json.dumps({'edits': {'workoutUpdates': [{'workoutRef': 'WORKOUT_0',
                'setFields': {'description': 'Short description'}}]}})}}]},
        {'role': 'tool', 'tool_call_id': 'model_repair', 'content': json.dumps({'submittedDraft': model_changed, 'currentDraftId': 'REVISION_1'})},
        {'role': 'assistant', '_internalAuditActions': {'internal_reaudit': 'deterministic_metadata_correction'},
         'tool_calls': [{'id': 'internal_reaudit', 'function': {'name': 'audit_workout_plan', 'arguments':
             json.dumps({'requirementsId': 'REQ', 'baseDraftId': 'REVISION_1', 'patch': [{'op': 'replace',
                 'path': '/workouts/0/description', 'value': 'Strength training'}]})}}]},
        {'role': 'tool', 'tool_call_id': 'internal_reaudit', 'content': json.dumps({'submittedDraft': internal_changed, 'currentDraftId': 'REVISION_2'})},
    ]

    counts = _repair_attempt_counts(messages, 2)
    assert counts == {'changed': 1, 'rejected': 2, 'internal': 1}
    assert _model_repair_submissions_used(counts) == 3

    # A model cannot label its own submission as code-owned to evade the cap.
    forged = copy.deepcopy(messages)
    forged[-2].pop('_internalAuditActions')
    forged[-2]['tool_calls'][0]['function']['arguments'] = json.dumps({'_internalAuditAction': 'deterministic_metadata_correction'})
    forged[-1]['content'] = json.dumps({'passed': False, 'errors': [{'code': 'invalid_internal_audit_marker'}]})
    forged_counts = _repair_attempt_counts(forged, 2)
    assert forged_counts == {'changed': 1, 'rejected': 3, 'internal': 0}


def test_empty_saved_repair_patch_is_rejected_before_audit():
    from workout_generator_pkg.interactive_shell import _admit_repair_scope
    from workout_generator_pkg.planning_tools import PlanningInputError

    with pytest.raises(PlanningInputError) as error:
        _admit_repair_scope({'patch': []}, {'baseDraftId': 'REVISION_0'}, {'workouts': []}, [], 0, 3)

    assert error.value.code == 'empty_repair_noop'


def test_recipe_qualification_runs_only_for_owned_contract_or_movement_changes():
    from workout_generator_pkg.interactive_shell import _repair_requires_coordinated_qualification

    draft = {'workouts': [{'exercises': [{'definition_id': 'LIBRARY_1'}]}]}
    assert not _repair_requires_coordinated_qualification({'exerciseUpdates': [{'exerciseRef': 'EXERCISE_0',
        'setFields': {'numWorkSets': 4}}]}, draft)
    assert not _repair_requires_coordinated_qualification({'exerciseUpdates': [{'exerciseRef': 'EXERCISE_0',
        'setFields': {'definition_id': 'LIBRARY_1'}}]}, draft)
    assert not _repair_requires_coordinated_qualification({'exerciseUpdates': [{'exerciseRef': 'EXERCISE_0',
        'setFields': {'progressionMethod': 'doubleProgression'}}]}, draft)
    assert _repair_requires_coordinated_qualification({'exerciseUpdates': [{'exerciseRef': 'EXERCISE_0',
        'setFields': {'progressionPlan': {'kind': 'reps'}}}]}, draft)
    assert _repair_requires_coordinated_qualification({'exerciseUpdates': [{'exerciseRef': 'EXERCISE_0',
        'removeOptionalFields': ['satisfiesCoverage']}]}, draft)
    assert _repair_requires_coordinated_qualification({'exerciseUpdates': [{'exerciseRef': 'EXERCISE_0',
        'setFields': {'definition_id': 'LIBRARY_2'}}]}, draft)
    assert _repair_requires_coordinated_qualification({'exerciseAdditions': [{'temporaryId': 'NEW_EXERCISE_1'}]}, draft)


def test_selection_repair_can_read_only_omitted_draft_details_while_choosing():
    from workout_generator_pkg.interactive_shell import _candidate_menu_expansion_tools

    tools = [{'function': {'name': name}} for name in (
        'search_exercise_library', 'get_workout_draft', 'audit_workout_plan',
        'propose_workout_alternatives', 'accept_workout_alternative')]
    choose = {'proofScope': 'exercise_selection_repair', 'stage': 'choose_candidate',
        'missingDraftReferences': ['WORKOUT_2']}
    discover = {**choose, 'stage': 'discover_candidates'}

    assert {tool['function']['name'] for tool in _candidate_menu_expansion_tools(tools, choose)} == {
        'get_workout_draft', 'audit_workout_plan', 'propose_workout_alternatives'}
    assert {tool['function']['name'] for tool in _candidate_menu_expansion_tools(tools, discover)} == {
        'search_exercise_library'}


def test_repair_cap_zero_rejects_before_repair_scope_validation():
    from unittest.mock import Mock
    from workout_generator_pkg.interactive_shell import _admit_repair_scope
    from workout_generator_pkg.planning_tools import PlanningInputError

    scope_validator = Mock()
    with pytest.raises(PlanningInputError) as error:
        _admit_repair_scope(
            {'patch': []}, {'findingsAssessment': {'groups': [{'disposition': 'repair'}]}},
            {'workouts': []}, [], 0, 0, scope_validator=scope_validator,
        )

    assert error.value.code == 'repair_round_cap_reached'
    scope_validator.assert_not_called()


def test_repair_cap_blocks_stable_edits_before_candidate_qualification():
    from unittest.mock import Mock
    from workout_generator_pkg.interactive_shell import _admit_repair_scope
    from workout_generator_pkg.planning_tools import PlanningInputError

    base = {'requirementsId': 'REQ', 'workouts': [{'name': 'Monday', 'exercises': []}]}
    messages = [
        {'role': 'assistant', 'tool_calls': [{'id': 'initial', 'function': {
            'name': 'audit_workout_plan', 'arguments': json.dumps({'workouts': base['workouts']})}}]},
        {'role': 'tool', 'tool_call_id': 'initial', 'content': json.dumps({
            'submittedDraft': base, 'currentDraftId': 'REVISION_0'})},
    ]
    previous = base
    for index in range(3):
        call_id = f'stable_repair_{index}'
        changed = copy.deepcopy(base)
        changed['workouts'][0]['name'] = f'Monday revision {index + 1}'
        messages.extend([
            {'role': 'assistant', 'tool_calls': [{'id': call_id, 'function': {
                'name': 'audit_workout_plan', 'arguments': json.dumps({'edits': {
                    'workoutUpdates': [{'workoutRef': 'WORKOUT_0', 'setFields': {
                        'name': changed['workouts'][0]['name']}}]}})}}]},
            {'role': 'tool', 'tool_call_id': call_id, 'content': json.dumps({
                'submittedDraft': changed, 'currentDraftId': f'REVISION_{index + 1}'})},
        ])
        previous = changed

    scope_validator = Mock()
    with pytest.raises(PlanningInputError) as error:
        _admit_repair_scope(
            {'edits': {'exerciseUpdates': [{'exerciseRef': 'EXERCISE_0',
                'setFields': {'numWorkSets': 2}}]}},
            {'findingsAssessment': {'groups': [{'disposition': 'repair'}]}},
            previous, messages, 2, 3, scope_validator=scope_validator,
        )

    assert error.value.code == 'repair_round_cap_reached'
    scope_validator.assert_not_called()


def test_repair_dimensions_cover_nested_owned_fields_and_individual_exercise_additions():
    from workout_generator_pkg.planning_tools import _operation_repair_dimensions, _repair_field_dimensions
    from workout_generator_pkg.repair_capabilities import repair_capability_contract

    assert _operation_repair_dimensions({'op': 'replace', 'path': '/workouts/0/exercises/2/progressionPlan/kind'}, {}) == {'progression'}
    assert _operation_repair_dimensions({'op': 'replace', 'path': '/workouts/0/exercises/2/workSetTemplate/reps'}, {}) == {'prescription', 'session_timing'}
    assert _operation_repair_dimensions({'op': 'add', 'path': '/workouts/0/exercises/-', 'value': {'definition_id': 'LIBRARY_2'}}, {}) == {'exercise_selection'}
    assert _operation_repair_dimensions({'op': 'remove', 'path': '/workouts/0/exercises/2'}, {}) == {'exercise_selection'}
    assert _operation_repair_dimensions({'op': 'replace', 'path': '/workouts/0/exercises', 'value': []}, {}) == set()
    assert _operation_repair_dimensions({'op': 'replace', 'path': '/workouts/0/exercises/2/effortAcceptance/minimumRIR'}, {}) == {'prescription'}
    inventory = repair_capability_contract()['editableFields']
    assert inventory['trainingDays'] == ['ordering', 'session_timing']
    assert inventory['effortAcceptance'] == ['prescription']
    assert _repair_field_dimensions('effortAcceptance') == set(inventory['effortAcceptance'])


def test_exercise_finding_cannot_be_credited_by_an_unrelated_exercise_in_same_workout():
    from workout_generator_pkg.planning_tools import PlanningInputError, validate_repair_scope

    _, _, _, current = planning_case()
    current['workouts'][0]['exercises'].append(copy.deepcopy(current['workouts'][0]['exercises'][0]))
    current['workouts'][0]['exercises'][1]['placementNotes'] = 'Sibling source cue'
    task = {'baseDraftId': 'REVISION_1', 'findingsAssessment': {'groups': [
        {'findingIndexes': [0], 'disposition': 'repair', 'repairDimensions': ['guidance']} ]},
        'reviewFindings': [{'draftPath': '/workouts/0/exercises/0/placementNotes'}]}
    sibling_edit = {'requirementsId': current['requirementsId'], 'baseDraftId': 'REVISION_1',
        'addressedFindingIndexes': [0], 'patch': [{'op': 'replace',
            'path': '/workouts/0/exercises/1/placementNotes', 'value': 'Changed sibling cue'}]}

    with pytest.raises(PlanningInputError, match='matching structured field'):
        validate_repair_scope({**sibling_edit, 'patch': copy.deepcopy(sibling_edit['patch'])},
            {**task, '_compiledRepairOperationRefs': [['EXERCISE_1', 'WORKOUT_0']]}, current)

    target_edit = {**sibling_edit, 'patch': [{'op': 'replace',
        'path': '/workouts/0/exercises/0/placementNotes', 'value': 'Changed target cue'}]}
    validate_repair_scope(target_edit,
        {**task, '_compiledRepairOperationRefs': [['EXERCISE_0', 'WORKOUT_0']]}, current)

    mixed_task = {**task, 'findingsAssessment': {'groups': [
        {'findingIndexes': [0], 'disposition': 'repair', 'repairDimensions': ['guidance', 'ordering']} ]}}
    mixed_patch = {'requirementsId': current['requirementsId'], 'baseDraftId': 'REVISION_1',
        'addressedFindingIndexes': [0], 'patch': [
            {'op': 'replace', 'path': '/workouts/0/exercises/1/placementNotes', 'value': 'Changed sibling cue'}]}
    with pytest.raises(PlanningInputError, match='matching structured field'):
        validate_repair_scope(mixed_patch, {**mixed_task, '_compiledRepairOperationRefs': [
            ['EXERCISE_1', 'WORKOUT_0']]}, current)


def test_exercise_order_move_credits_each_occurrence_it_crosses():
    from workout_generator_pkg.alternative_repair import _patch_operation_references
    from workout_generator_pkg.planning_tools import validate_repair_scope

    _, _, _, current = planning_case()
    current['workouts'][0]['exercises'].append(copy.deepcopy(current['workouts'][0]['exercises'][0]))
    patch = [{'op': 'move', 'from': '/workouts/0/exercises/1', 'path': '/workouts/0/exercises/0'}]
    references = _patch_operation_references(current['workouts'], patch)
    assert set(references[0]) == {'EXERCISE_0', 'EXERCISE_1', 'WORKOUT_0'}
    task = {'baseDraftId': 'REVISION_1', 'findingsAssessment': {'groups': [
        {'findingIndexes': [0], 'disposition': 'repair', 'repairDimensions': ['ordering']} ]},
        'reviewFindings': [{'draftPath': '/workouts/0/exercises/0/placementNotes'}]}
    arguments = {'requirementsId': current['requirementsId'], 'baseDraftId': 'REVISION_1',
        'addressedFindingIndexes': [0], 'patch': patch}

    validate_repair_scope(arguments, {**task, '_compiledRepairOperationRefs': references}, current)


def test_previous_assessment_without_capability_contract_is_fully_reassessed(monkeypatch):
    review = {'inputHash': 'legacy-review', 'findings': [{'severity': 'warning', 'message': 'Improve progression.'}]}
    previous = {'version': assessment.VERSION - 1, 'inputHash': assessment.assessment_hash(review),
        'groups': [{'findingIndexes': [0], 'disposition': 'repair', 'reason': 'Preserve the source-backed route.',
                    'evidencePaths': ['/draft/workouts/0/exercises/0/progressionPlan'], 'evidenceHash': 'keep-me'}],
        'repairPlan': 'Repair progression with the existing candidate.'}
    review['assessment'] = previous
    calls = []
    def respond(client, request, **options):
        calls.append((request, options))
        return json.dumps({'groups': [{'findingIndexes': [0], 'disposition': 'repair',
            'repairDimensions': ['progression'], 'reason': 'The typed route can be corrected.',
            'errorKind': 'none', 'authorityEvidenceRefs': [], 'currentDataEvidenceRefs': []}],
            'repairPlan': 'Correct the typed progression route.'}), None, None
    monkeypatch.setattr(assessment, '_review_call', respond)
    result = assessment.assess_findings(None, {'draft': {'workouts': []}}, review)
    assert len(calls) == 1 and calls[0][1]['reasoning_effort'] == 'low'
    assert result['version'] == assessment.VERSION
    assert result['groups'][0]['reason'] == 'The typed route can be corrected.'
    assert result['repairPlan'] == 'Correct the typed progression route.'
    context = json.loads(calls[0][0][-1]['content'])['context']
    assert 'repairCapabilityContract' in context


def test_stale_dimensioned_assessment_with_empty_repair_scope_is_fully_reassessed(monkeypatch):
    review = {'inputHash': 'saved-review', 'findings': [
        {'severity': 'warning', 'message': 'No unsupported direct deltoid requirement is present.'}]}
    review['assessment'] = {'version': assessment.VERSION - 1,
        'inputHash': assessment.assessment_hash(review),
        'groups': [{'findingIndexes': [0], 'disposition': 'repair', 'repairDimensions': [],
            'reason': 'No numerical change is required.', 'errorHash': 'saved'}],
        'repairPlan': 'No numerical change is required.'}
    calls = []
    def respond(_client, request, **_options):
        calls.append(request)
        return json.dumps({'groups': [{'findingIndexes': [0], 'disposition': 'advisory',
            'repairDimensions': [], 'reason': 'The target is met and direct deltoid loading was not requested.',
            'errorKind': 'none', 'authorityEvidenceRefs': [], 'currentDataEvidenceRefs': []}],
            'repairPlan': ''}), None, None
    monkeypatch.setattr(plan_review, '_review_call', respond)
    result = assessment.assess_findings(None, {'draft': 'saved candidate'}, review)
    assert len(calls) == 1
    assert result['groups'][0]['disposition'] == 'advisory'


def test_previous_assessment_version_is_stale_even_when_legacy_validation_is_requested():
    review = {'inputHash': 'saved-review', 'findings': [{'severity': 'warning', 'message': 'Review item.'}]}
    review['assessment'] = {'version': assessment.VERSION - 1,
        'inputHash': assessment.assessment_hash(review),
        'groups': [{'findingIndexes': [0], 'disposition': 'repair', 'repairDimensions': [],
            'reason': 'Saved disposition.'}], 'repairPlan': 'Repair it.'}
    with pytest.raises(ValueError, match='missing or stale'):
        assessment.validate_assessment(review)


def test_review_draft_reassesses_cached_legacy_assessment(monkeypatch):
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    raw = audit_workout_plan(draft, equipment, messages)
    context = {'draft': {'workouts': [{'name': 'A'}]}, 'requirements': {'goal': 'strength'}}
    finding = {'severity': 'warning', 'action': 'repair', 'message': 'Progression guidance needs a source-backed correction.'}
    monkeypatch.setattr(plan_review, '_context', lambda *args: context)
    monkeypatch.setattr(plan_review, '_review_checklist', lambda *args: None)
    monkeypatch.setattr(plan_review, '_evidence_units', lambda *args: {})
    monkeypatch.setattr(plan_review, '_execution_review_context', lambda *args: {'scope': 'execution'})
    monkeypatch.setattr(plan_review, '_with_blocker_checklist', lambda scope, part, *args: part)
    execution_hash = plan_review._hash({'scope': 'execution'})
    cached_review = {
        'version': plan_review.REVIEW_VERSION,
        'inputHash': plan_review._review_input_hash(context, raw.get('currentDraftId')),
        'reviewBaseHash': plan_review._review_base_hash(context),
        'reviewLedgerOutputFingerprint': plan_review._review_ledger_fingerprint(context),
        'findings': [finding],
        'scopeResults': {'execution': {'inputHash': execution_hash, 'findings': [finding]}},
        'evidenceUnits': {},
        'assessment': {
            'version': assessment.VERSION - 1,
            'inputHash': assessment.assessment_hash({'inputHash': plan_review._review_input_hash(context, raw.get('currentDraftId')), 'findings': [finding]}),
            'groups': [{'findingIndexes': [0], 'disposition': 'repair',
                        'reason': 'The supported progression issue needs correction.',
                        'evidencePaths': ['/draft/workouts/0/exercises/0/progressionPlan'],
                        'evidenceHash': 'preserve'}],
            'repairPlan': 'Correct progression using the supported plan.'}}
    previous = {**raw, 'review': cached_review}
    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': 'legacy-review', 'function': {'name': 'audit_workout_plan'}}]},
        {'role': 'tool', 'tool_call_id': 'legacy-review', 'content': json.dumps(previous)}])

    monkeypatch.setattr(plan_review, 'parallel_proposals',
        lambda *args, **kwargs: pytest.fail('Cached independent review scopes must be reused'))
    requests = []
    def reassess(client, request, **options):
        requests.append(options)
        return json.dumps({'groups': [{'findingIndexes': [0], 'disposition': 'repair',
            'repairDimensions': ['progression'], 'reason': 'Reassessed with current capabilities.',
            'errorKind': 'none', 'authorityEvidenceRefs': [], 'currentDataEvidenceRefs': []}],
            'repairPlan': 'Repair the progression route.'}), None, None
    monkeypatch.setattr(assessment, '_review_call', reassess)

    result = plan_review.review_draft(None, raw, messages, equipment)

    assert len(requests) == 1 and requests[0]['reasoning_effort'] == 'low'
    assert result['review']['assessment']['version'] == assessment.VERSION
    reassessed = result['review']['assessment']['groups'][0]
    assert reassessed['repairDimensions'] == ['progression']
    assert reassessed['reason'] == 'Reassessed with current capabilities.'


def test_every_finding_is_assessed_together_cached_and_malformed_assessments_fail_closed(monkeypatch):
    review = reviewed()
    calls = []
    prompts = []
    alternative_review = {'mode': 'hypothetical_candidate_merit', 'approvalStatus': 'pending',
        'approvalGate': 'after_full_validation', 'instruction': 'Pending approval is expected workflow state, not a defect.'}
    def respond(client, request, **options):
        calls.append(json.loads(request[-1]['content']))
        prompts.append(request[0]['content'])
        return json.dumps({'groups': [
            {'findingIndexes': [0, 2], 'disposition': 'repair', 'repairDimensions': ['guidance'], 'reason': 'Coordinate title and coverage repair.'},
            {'findingIndexes': [1], 'disposition': 'advisory', 'repairDimensions': [], 'reason': 'No explicit goal is violated.'}],
            'repairPlan': 'Repair coverage and titles while preserving time and volume.'}), None, None
    monkeypatch.setattr(assessment, '_review_call', respond)
    result = assessment.assess_findings(None, {'draft': 'whole week', 'alternativeReview': alternative_review}, review)
    assert set(calls[0]['findings']) == {'0', '1', '2'}
    assert calls[0]['context']['alternativeReview'] == alternative_review
    assert 'Pending approval is expected' in prompts[0]
    review['assessment'] = result
    assert assessment.assess_findings(None, {}, review) == result and len(calls) == 1
    for indexes in ([0], [0, 0, 2], [0, 2, True]):
        bad = copy.deepcopy(review)
        bad['assessment']['groups'][0]['findingIndexes'] = indexes
        with pytest.raises(ValueError):
            assessment.validate_assessment(bad)
    bad = copy.deepcopy(review)
    bad['assessment']['groups'][0]['disposition'] = 'advisory'
    with pytest.raises(ValueError, match='waive'):
        assessment.validate_assessment(bad)
    review['findings'][0]['message'] = 'Changed evidence'
    with pytest.raises(ValueError, match='stale'):
        assessment.validate_assessment(review)


def test_blocking_finding_assessment_gets_one_bounded_correction(monkeypatch):
    review = {'inputHash': 'review-input', 'findings': [
        {'severity': 'blocking', 'message': 'Invented universal lateral-raise cap.'}]}
    context = {'draft': {'workouts': ['complete candidate']}, 'sourceMessages': ['full source']}
    monkeypatch.setattr(plan_review, '_with_review_refs', lambda value: (copy.deepcopy(value), {'FACT_0': '/draft'}))
    invalid = {'groups': [{'findingIndexes': [0], 'disposition': 'advisory', 'repairDimensions': [],
        'reason': 'The finding is unsupported.', 'errorKind': 'none', 'authorityEvidenceRefs': [], 'currentDataEvidenceRefs': []}],
        'repairPlan': ''}
    corrected = {'groups': [{'findingIndexes': [0], 'disposition': 'repair', 'repairDimensions': ['guidance'],
        'reason': 'Blocking finding must be corrected.', 'errorKind': 'none', 'authorityEvidenceRefs': [], 'currentDataEvidenceRefs': []}],
        'repairPlan': 'Repair the unsupported cap while preserving the approved plan.'}
    calls = []
    def respond(client, request, **options):
        calls.append((copy.deepcopy(request), options))
        payload = invalid if len(calls) == 1 else corrected
        return json.dumps(payload), None, None
    monkeypatch.setattr(assessment, '_review_call', respond)

    result = assessment.assess_findings(None, context, review)

    assert result['groups'][0]['disposition'] == 'repair'
    assert result['groups'][0]['findingIndexes'] == [0]
    assert len(calls) == 2
    assert calls[0][1]['max_tokens'] == calls[1][1]['max_tokens'] == 24576
    assert calls[0][1]['timeout'] is calls[1][1]['timeout'] is None
    assert calls[0][1]['reasoning_effort'] == 'low' and calls[1][1]['reasoning_effort'] is None
    correction = json.loads(calls[1][0][-1]['content'])
    assert correction['allFindingIndexes'] == [0]
    assert 'blocking finding' in correction['task']
    original_context = json.loads(calls[1][0][1]['content'])['context']
    original_context.pop('reviewErrorEvidencePolicy')
    from workout_generator_pkg.repair_capabilities import repair_capability_contract
    assert original_context.pop('repairCapabilityContract') == repair_capability_contract()
    assert original_context == context


def test_unresolved_capability_preserves_blocking_finding_without_authorizing_repair():
    from workout_generator_pkg.repair_capabilities import has_unresolved_capabilities

    review = {'inputHash': 'review-input', 'findings': [
        {'severity': 'blocking', 'message': 'Automatically lower working-set load after a failed target.'}]}
    review['assessment'] = {'version': assessment.VERSION, 'inputHash': assessment.assessment_hash(review),
        'groups': [{'findingIndexes': [0], 'disposition': 'unresolved_capability', 'repairDimensions': [],
            'reason': 'The request requires automatic within-session load reduction, which this generator does not support.'}],
        'repairPlan': ''}

    validated = assessment.validate_assessment(review)

    assert has_unresolved_capabilities(validated)
    assert validated['groups'][0]['disposition'] == 'unresolved_capability'
    assert validated['groups'][0]['findingIndexes'] == [0]


def test_assessment_exposes_shared_capabilities_and_keeps_missing_behavior_unresolved(monkeypatch):
    from workout_generator_pkg.repair_capabilities import repair_capability_contract

    review = {'inputHash': 'review-input', 'findings': [
        {'severity': 'blocking', 'message': 'Automatically reduce load after a failed working set.'}]}
    context = {'draft': {'workouts': [{'name': 'candidate'}]}, 'sourceMessages': [{'text': 'request'}]}
    response = {'groups': [{'findingIndexes': [0], 'disposition': 'unresolved_capability',
        'repairDimensions': [], 'reason': 'Automatic load reduction is not supported.', 'errorKind': 'none',
        'authorityEvidenceRefs': [], 'currentDataEvidenceRefs': []}], 'repairPlan': ''}
    requests = []

    def respond(client, messages, **options):
        requests.append(copy.deepcopy(messages))
        return json.dumps(response), None, None

    monkeypatch.setattr(assessment, '_review_call', respond)
    result = assessment.assess_findings(None, context, review)

    assert result['groups'][0]['disposition'] == 'unresolved_capability'
    submitted_context = json.loads(requests[0][-1]['content'])['context']
    contract = submitted_context['repairCapabilityContract']
    assert contract['unsupportedBehaviors'] == repair_capability_contract()['unsupportedBehaviors']
    assert 'automatic_load_reduction' in contract['unsupportedBehaviors']
    visible_refs = set()
    def collect_refs(value):
        if isinstance(value, dict):
            if isinstance(value.get('_reviewRef'), str):
                visible_refs.add(value['_reviewRef'])
            for child in value.values():
                collect_refs(child)
        elif isinstance(value, list):
            for child in value:
                collect_refs(child)
    collect_refs(submitted_context)
    evidence_policy = submitted_context['reviewErrorEvidencePolicy']
    assert set(evidence_policy['authoritativeSourceOrPolicyFacts']) <= visible_refs


def test_coordinated_repair_tool_uses_the_same_capability_contract():
    from workout_generator_pkg.repair_capabilities import repair_capability_contract
    from workout_generator_pkg.planning_tools import coordinated_repair_tool

    description = coordinated_repair_tool({})['function']['description']

    assert json.dumps(repair_capability_contract(), separators=(',', ':')) in description


def test_direct_repair_compilation_and_scope_validation_fail_closed_on_unresolved_capability():
    from workout_generator_pkg.planning_tools import (
        PlanningInputError, _structured_repair_coverage, compile_coordinated_repair, validate_repair_scope,
    )

    task = {'baseDraftId': 'REVISION_1', 'findingsAssessment': {'groups': [
        {'findingIndexes': [0], 'disposition': 'unresolved_capability', 'repairDimensions': [],
         'reason': 'Automatic within-session load reduction is unsupported.'}]}}
    current = {'workouts': [{'name': 'Day', 'exercises': []}]}
    direct_paths = [
        lambda: validate_repair_scope({}, task, current),
        lambda: _structured_repair_coverage({}, task, current),
        lambda: compile_coordinated_repair({}, task, current),
    ]

    for invoke in direct_paths:
        with pytest.raises(PlanningInputError, match='cannot provide') as error:
            invoke()
        assert error.value.code == 'unresolved_review_capability'


def test_invalid_assessment_correction_still_fails_closed(monkeypatch):
    review = {'inputHash': 'review-input', 'findings': [{'severity': 'blocking', 'message': 'Claim.'}]}
    monkeypatch.setattr(plan_review, '_with_review_refs', lambda value: (copy.deepcopy(value), {}))
    invalid = {'groups': [{'findingIndexes': [0], 'disposition': 'advisory', 'repairDimensions': [], 'reason': 'Unsupported.',
        'errorKind': 'none', 'authorityEvidenceRefs': [], 'currentDataEvidenceRefs': []}], 'repairPlan': ''}
    calls = []
    def respond(*args, **kwargs):
        calls.append(1)
        return json.dumps(invalid), None, None
    monkeypatch.setattr(assessment, '_review_call', respond)
    with pytest.raises(ValueError, match='waive'):
        assessment.assess_findings(None, {}, review)
    assert len(calls) == 2


def test_withdrawal_correction_exposes_and_requires_both_evidence_categories(monkeypatch):
    context = {'sourceMessages': {'SOURCE_0': {'text': 'No per-session minimum.'}},
        'draft': {'workouts': [{'pushSets': 4}]}}
    review = {'inputHash': 'review-input', 'findings': [{'severity': 'blocking', 'message': 'Invented five-set minimum.'}]}
    facts = {'FACT_0': '/sourceMessages/SOURCE_0', 'FACT_1': '/draft/workouts/0'}
    monkeypatch.setattr(plan_review, '_with_review_refs', lambda value: (copy.deepcopy(value), facts))
    rejected = {'groups': [{'findingIndexes': [0], 'disposition': 'withdrawn_review_error', 'repairDimensions': [],
        'reason': 'The requirement has no such minimum.', 'errorKind': 'unsupported_requirement',
        'authorityEvidenceRefs': [], 'currentDataEvidenceRefs': ['FACT_1']}], 'repairPlan': ''}
    corrected = {'groups': [{'findingIndexes': [0], 'disposition': 'withdrawn_review_error', 'repairDimensions': [],
        'reason': 'The source has no per-session minimum and the current four sets do not violate one.',
        'errorKind': 'unsupported_requirement', 'authorityEvidenceRefs': ['FACT_0'],
        'currentDataEvidenceRefs': ['FACT_1']}], 'repairPlan': ''}
    calls = []
    def respond(client, request, **options):
        calls.append((copy.deepcopy(request), options))
        return json.dumps(rejected if len(calls) == 1 else corrected), None, None
    monkeypatch.setattr(assessment, '_review_call', respond)

    result = assessment.assess_findings(None, context, review)

    assert result['groups'][0]['evidencePaths'] == ['/sourceMessages/SOURCE_0', '/draft/workouts/0']
    policy = json.loads(calls[0][0][-1]['content'])['context']['reviewErrorEvidencePolicy']
    assert policy['authoritativeSourceOrPolicyFacts'] == ['FACT_0']
    assert policy['currentCandidateAndDataFacts'] == ['FACT_1']
    correction = json.loads(calls[1][0][-1]['content'])
    assert 'missing authoritative policy/source evidence' in correction['validationError']
    assert len(calls) == 2


def test_failed_assessment_resumes_from_saved_response_with_one_correction(monkeypatch):
    context = {'sourceMessages': {'SOURCE_0': {'text': 'No per-session minimum.'}},
        'draft': {'workouts': [{'pushSets': 4}]}}
    review = {'inputHash': 'review-input', 'findings': [{'severity': 'blocking', 'message': 'Invented five-set minimum.'}]}
    facts = {'FACT_0': '/sourceMessages/SOURCE_0', 'FACT_1': '/draft/workouts/0'}
    monkeypatch.setattr(plan_review, '_with_review_refs', lambda value: (copy.deepcopy(value), facts))
    invalid = {'groups': [{'findingIndexes': [0], 'disposition': 'withdrawn_review_error', 'repairDimensions': [],
        'reason': 'The requirement has no such minimum.', 'errorKind': 'unsupported_requirement',
        'authorityEvidenceRefs': [], 'currentDataEvidenceRefs': ['FACT_1']}], 'repairPlan': ''}
    corrected = {'groups': [{'findingIndexes': [0], 'disposition': 'withdrawn_review_error', 'repairDimensions': [],
        'reason': 'The source has no per-session minimum and the current four sets do not violate one.',
        'errorKind': 'unsupported_requirement', 'authorityEvidenceRefs': ['FACT_0'],
        'currentDataEvidenceRefs': ['FACT_1']}], 'repairPlan': ''}
    calls = []
    def respond(client, request, **options):
        calls.append((copy.deepcopy(request), options))
        # Fail both the original answer and its bounded correction; the next
        # call should continue from the saved correction response only.
        return json.dumps(invalid), None, None
    monkeypatch.setattr(assessment, '_review_call', respond)
    with pytest.raises(ValueError, match='missing authoritative'):
        assessment.assess_findings(None, context, review)
    assert review['assessmentFailure']['rejectedResponse'] == json.dumps(invalid)
    assert len(calls) == 2

    resumed_calls = []
    def resume(client, request, **options):
        resumed_calls.append((copy.deepcopy(request), options))
        return json.dumps(corrected), None, None
    monkeypatch.setattr(assessment, '_review_call', resume)
    result = assessment.assess_findings(None, context, review)

    assert result['groups'][0]['disposition'] == 'withdrawn_review_error'
    assert len(resumed_calls) == 1
    assert resumed_calls[0][1]['reasoning_effort'] is None
    assert resumed_calls[0][0][-1]['content'].find('rejectedAssessment') >= 0
    assert 'assessmentFailure' not in review


def test_saved_assessment_that_now_validates_is_reused_without_another_call(monkeypatch):
    context = {'draft': {'workouts': [{'name': 'A'}]}}
    review = {'inputHash': 'review-input', 'findings': [{'severity': 'warning', 'message': 'Fix title.'}]}
    monkeypatch.setattr(plan_review, '_with_review_refs', lambda value: (copy.deepcopy(value), {'FACT_0': '/draft/workouts/0'}))
    valid = {'groups': [{'findingIndexes': [0], 'disposition': 'repair', 'repairDimensions': ['guidance'], 'reason': 'The title is inaccurate.',
        'errorKind': 'none', 'authorityEvidenceRefs': [], 'currentDataEvidenceRefs': []}],
        'repairPlan': 'Correct the title.'}
    review['assessmentFailure'] = {'version': assessment.VERSION,
        'inputHash': assessment.assessment_hash(review), 'rejectedResponse': json.dumps(valid),
        'validationError': 'Old contract failure.'}
    monkeypatch.setattr(assessment, '_review_call', lambda *a, **k: pytest.fail('A valid saved assessment needs no call'))

    result = assessment.assess_findings(None, context, review)

    assert result['groups'][0]['disposition'] == 'repair'
    assert 'assessmentFailure' not in review


def test_cached_review_receipt_resumes_only_assessment_correction(monkeypatch):
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    raw = audit_workout_plan(draft, equipment, messages)
    context = {'draft': {'workouts': [{'name': 'A'}]}, 'requirements': {'goal': 'strength'}}
    monkeypatch.setattr(plan_review, '_context', lambda *args: context)
    monkeypatch.setattr(plan_review, '_review_checklist', lambda *args: None)
    finding = {'severity': 'blocking', 'action': 'repair', 'message': 'Correct a coordinated exercise-order issue.'}
    boundary = next(i for i in range(len(messages) - 1, -1, -1) if messages[i].get('role') == 'user')
    review = {'version': plan_review.REVIEW_VERSION,
        'inputHash': plan_review._review_input_hash(context, raw.get('currentDraftId')),
        'reviewBaseHash': plan_review._review_base_hash(context),
        'reviewLedgerOutputFingerprint': plan_review._review_ledger_fingerprint(context),
        'instructionBoundary': boundary, 'findings': [finding], 'scopeResults': {}, 'evidenceUnits': {},
        'failure': 'ValueError: prior assessment could not be validated',
        'assessmentFailure': {'version': assessment.VERSION,
            'inputHash': assessment.assessment_hash({'inputHash': plan_review._review_input_hash(context, raw.get('currentDraftId')), 'findings': [finding]}),
            'rejectedResponse': json.dumps({'groups': [{'findingIndexes': [0], 'disposition': 'advisory', 'repairDimensions': [],
                'reason': 'Unsupported.', 'errorKind': 'none', 'authorityEvidenceRefs': [],
                'currentDataEvidenceRefs': []}], 'repairPlan': ''}),
            'validationError': 'Assessment cannot waive a blocking finding.',
            'stage': 'independent_findings_assessment_correction'}}
    previous = {**raw, 'review': review}
    messages.extend([{'role': 'assistant', 'tool_calls': [{'id': 'prior', 'function': {'name': 'audit_workout_plan'}}]},
        {'role': 'tool', 'tool_call_id': 'prior', 'content': json.dumps(previous)}])
    response = {'groups': [{'findingIndexes': [0], 'disposition': 'repair', 'repairDimensions': ['guidance'],
        'reason': 'The order issue remains actionable.', 'errorKind': 'none',
        'authorityEvidenceRefs': [], 'currentDataEvidenceRefs': []}],
        'repairPlan': 'Fix the order issue with the other supported changes.'}
    calls = []
    def respond(client, request, **options):
        calls.append((copy.deepcopy(request), options))
        return json.dumps(response), None, None
    monkeypatch.setattr(assessment, '_review_call', respond)
    monkeypatch.setattr(plan_review, 'chat_call', lambda *a, **k: pytest.fail('Cached reviewer scopes must not rerun'))

    result = plan_review.review_draft(None, raw, messages, equipment)

    assert result['review']['assessment']['groups'][0]['disposition'] == 'repair'
    assert 'failure' not in result['review']
    assert len(calls) == 1 and calls[0][1]['reasoning_effort'] is None


def test_cached_confirmation_failure_reuses_valid_assessment_after_boundary_moves(monkeypatch):
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    raw = audit_workout_plan(draft, equipment, messages)
    context = {'draft': {'workouts': [{'name': 'A'}]}, 'requirements': {'goal': 'strength'}}
    monkeypatch.setattr(plan_review, '_context', lambda *args: context)
    monkeypatch.setattr(plan_review, '_review_checklist', lambda *args: None)
    prior_boundary = next(i for i in range(len(messages) - 1, -1, -1) if messages[i].get('role') == 'user')
    finding = {'severity': 'warning', 'action': 'repair', 'message': 'A supported issue remains.'}
    cached_review = {'version': plan_review.REVIEW_VERSION,
        'inputHash': plan_review._review_input_hash(context, raw.get('currentDraftId')),
        'reviewBaseHash': plan_review._review_base_hash(context),
        'reviewLedgerOutputFingerprint': plan_review._review_ledger_fingerprint(context),
        'instructionBoundary': prior_boundary, 'findings': [finding], 'scopeResults': {}, 'evidenceUnits': {},
        'failure': 'RuntimeError: confirmation interrupted', 'failureStage': 'independent_review_confirmation',
        'assessment': {'version': assessment.VERSION, 'inputHash': assessment.assessment_hash({
                'inputHash': plan_review._review_input_hash(context, raw.get('currentDraftId')), 'findings': [finding]}), 'groups': [
                {'findingIndexes': [0], 'disposition': 'repair', 'repairDimensions': ['guidance'], 'reason': 'The review issue remains actionable.'}],
            'repairPlan': 'Fix the issue.'}}
    assert plan_review._cached_confirmation_receipt_is_valid(cached_review, context)
    previous = {**raw, 'review': cached_review}
    messages.extend([{'role': 'user', 'content': 'Continue with the same approved plan.'},
        {'role': 'assistant', 'tool_calls': [{'id': 'prior', 'function': {'name': 'audit_workout_plan'}}]},
        {'role': 'tool', 'tool_call_id': 'prior', 'content': json.dumps(previous)}])
    assert json.loads(messages[-1]['content'])['review']['inputHash'] == plan_review._review_input_hash(context, raw.get('currentDraftId'))
    cached_calls = {call['id'] for message in messages for call in message.get('tool_calls', [])
                    if call['function']['name'] == 'audit_workout_plan'}
    assert cached_calls == {'prior'} and messages[-1]['tool_call_id'] == 'prior'
    retry_checks = []
    check_retry = plan_review._cached_confirmation_receipt_is_valid
    monkeypatch.setattr(plan_review, '_cached_confirmation_receipt_is_valid',
        lambda cached, current: (retry_checks.append(cached.get('failureStage')) or check_retry(cached, current)))
    monkeypatch.setattr(plan_review, 'assess_findings', lambda *a, **k: pytest.fail('Validated assessment must be reused'))
    monkeypatch.setattr(plan_review, 'chat_call', lambda *a, **k: pytest.fail('Completed review scopes must not rerun'))

    result = plan_review.review_draft(None, raw, messages, equipment)

    assert 'independent_review_confirmation' in retry_checks
    assert result['review']['instructionBoundary'] != prior_boundary
    assert result['review']['assessment'] == cached_review['assessment']
    assert 'failure' not in result['review']


def test_actionable_warning_prevents_preview_and_export_without_changing_its_severity(monkeypatch):
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    raw = audit_workout_plan(draft, equipment, messages)
    finding = {'severity': 'warning', 'action': 'repair', 'basis': 'uncertainty', 'muscleTargets': [],
        'path': '/draft/workouts/0/name', 'message': 'Title contradicts final composition.',
        'evidencePaths': ['/draft/workouts/0/name'], 'repair': 'Correct title.', 'action': 'repair'}
    monkeypatch.setattr(plan_review, 'chat_call', lambda *a, **k: (json.dumps({'findings': [finding]}), None, None))
    monkeypatch.setattr(assessment, '_review_call', lambda *a, **k: (json.dumps({'groups': [
        {'findingIndexes': [0], 'disposition': 'repair', 'repairDimensions': ['guidance'], 'reason': 'Supported, correctable metadata contradiction.'}],
        'repairPlan': 'Correct the title with the other supported changes.'}), None, None))
    result = plan_review.review_draft(None, raw, messages, equipment)
    assert not result['passed'] and 'preview' not in result and 'planIndex' not in result
    assert result['errors'][0]['severity'] == 'warning'
    assert result['errors'][0]['code'] == 'independent_review_finding'
    assert 'together' in result['instruction']


def test_unmet_allocation_preferences_require_structural_edit_before_another_allocation():
    from workout_generator_pkg.interactive_shell import _messages_for_api
    from workout_generator_pkg.planner_context import request_planning_state
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    raw = audit_workout_plan(draft, equipment, messages)
    raw.update(passed=False, errors=[{'code': 'independent_review_finding', 'path': '/draft',
        'reviewScope': 'execution', 'message': 'Redistribute direct arm occurrences.'}])
    def tool(name, payload, key):
        messages.extend([{'role': 'assistant', 'tool_calls': [{'id': key, 'function': {'name': name, 'arguments': '{}'}}]},
            {'role': 'tool', 'tool_call_id': key, 'content': json.dumps(payload)}])
    tool('audit_workout_plan', raw, 'audit')
    allocation = {'feasible': True, 'baseDraftId': raw['currentDraftId'],
        'summary': {'preferenceDifferences': {'SLOT_0': {'preferred': 3, 'allocated': 8}}}}
    tool('allocate_workout_sets', allocation, 'allocation')
    state = request_planning_state(_messages_for_api(messages, True, provided_equipment=equipment))
    assert state['repairTask']['allocationNeedsStructuralChange']
    assert state['repairTask']['unmetAllocationPreferences']['SLOT_0']['allocated'] == 8
    allocation['baseDraftId'] = 'REVISION_OLD'
    tool('allocate_workout_sets', allocation, 'old')
    state = request_planning_state(_messages_for_api(messages, True, provided_equipment=equipment))
    assert not state['repairTask'].get('allocationNeedsStructuralChange')


def test_joint_allocation_can_relocate_existing_recipes_when_counts_cannot():
    from workout_generator_pkg.allocation import allocate_workout_sets
    from workout_generator_pkg.planning_tools import set_workout_requirements
    equipment, requirements, _, draft = planning_case()
    arm = copy.deepcopy(equipment['exerciseDefinitions'][0])
    arm.update(id='z_arm', name='Arm movement', muscleGroups=['FRONT_BICEPS'], secondaryMuscleGroups=[])
    equipment['exerciseDefinitions'].append(arm)
    requirements['sessionsPerWeek'] = 3
    requirements['auditTargets']['weeklyEffectiveSets'] = {'chest': {'minimum': 15, 'maximum': 18}, 'biceps': {'minimum': 15, 'maximum': 18}}
    requirements['auditTargets']['perSessionEffectiveSets'] = {'chest': {'minimum': 5, 'maximum': 6}, 'biceps': {'minimum': 5, 'maximum': 6}}
    requirements['auditTargets']['maximumSessionSeconds'] = 4000
    stored = set_workout_requirements(requirements, [{'role': 'user', 'content': 'Three sessions with five to six chest and biceps sets each.'}], equipment)
    draft['requirementsId'] = stored['requirementsId']
    template = copy.deepcopy(draft['workouts'][0])
    draft['workouts'] = []
    for i in range(3):
        day = copy.deepcopy(template)
        day.update(name=f'Day {i}', trainingDays=[2*i])
        day['exercises'][0]['numWorkSets'] = 5
        if i == 0:
            other = copy.deepcopy(day['exercises'][0])
            other.update(definition_id='LIBRARY_1', numWorkSets=15)
            day['exercises'].append(other)
        draft['workouts'].append(day)
    messages = requirement_messages(stored)
    raw = audit_workout_plan(draft, equipment, messages)
    messages.extend([{'role': 'assistant', 'tool_calls': [{'id': 'audit', 'function': {'name': 'audit_workout_plan'}}]},
        {'role': 'tool', 'tool_call_id': 'audit', 'content': json.dumps(raw)}])
    arguments = {'requirementsId': stored['requirementsId'], 'baseDraftId': raw['currentDraftId'], 'reallocateAcrossSessions': True}
    result = allocate_workout_sets(arguments, equipment, messages)
    assert result['feasible'], result
    assert result['scope'] == 'joint_selection_placement_prescriptions'
    for day in result['proposedWorkouts']:
        assert any(item['definition_id'] == 'LIBRARY_1' and 5 <= item['numWorkSets'] <= 6 for item in day['exercises'])
    assert not result['summary']['errors']
    assert not allocate_workout_sets({**arguments, 'preferredSetsBySlot': {'SLOT_0': 3}}, equipment, messages)['feasible']


def test_description_repair_uses_retained_proposal_without_a_model_or_mutation():
    from workout_generator_pkg.planner_context import pending_reaudit
    _, requirements, stored, draft = planning_case()
    state = {'requirementsId': stored['requirementsId'], 'currentDraftId': 'REVISION_0',
        'currentDraft': draft, 'requirements': requirements, 'repairTask': {
        'metadataFields': {'/workouts/0/description': {'maximumCharacters': 32, 'derivedReplacement': 'Timed training'}},
        'rejectedSubmission': {'patch': [{'op': 'replace', 'path': '/workouts/0/exercises/0/durationSeconds', 'value': 30}]}}}
    before = copy.deepcopy(state)
    request = pending_reaudit(state, '/continue')
    assert request['patch'] == [{'op': 'replace', 'path': '/workouts/0/description', 'value': 'Timed training'}]
    assert request['_internalAuditAction'] == 'deterministic_metadata_correction'
    assert state == before


def test_prior_review_assessment_remains_background_after_numerical_feedback(monkeypatch):
    from workout_generator_pkg.interactive_shell import _messages_for_api
    from workout_generator_pkg.planner_context import request_planning_state
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    raw = audit_workout_plan(draft, equipment, messages)
    from workout_generator_pkg.planning_tools import library_fingerprint
    raw['libraryFingerprint'] = library_fingerprint(equipment)
    finding = {'severity': 'warning', 'action': 'repair', 'basis': 'uncertainty', 'muscleTargets': [],
        'path': '/draft', 'message': 'Coordinate distribution and progression.',
        'evidencePaths': ['/draft'], 'repair': 'Repair both together.'}
    monkeypatch.setattr(plan_review, 'chat_call', lambda *a, **k: (json.dumps({'findings': [finding]}), None, None))
    monkeypatch.setattr(assessment, '_review_call', lambda *a, **k: (json.dumps({'groups': [
        {'findingIndexes': [0], 'disposition': 'repair', 'repairDimensions': ['guidance'], 'reason': 'Supported coordinated repair.'}],
        'repairPlan': 'Repair distribution and progression together.'}), None, None))
    reviewed = plan_review.review_draft(None, raw, messages, equipment)
    def tool(payload, key):
        messages.extend([{'role': 'assistant', 'tool_calls': [{'id': key, 'function': {'name': 'audit_workout_plan', 'arguments': '{}'}}]},
            {'role': 'tool', 'tool_call_id': key, 'content': json.dumps(payload)}])
    tool(reviewed, 'reviewed')
    tool({'passed': False, 'errors': [{'code': 'invalid_draft_patch', 'path': '/patch'}]}, 'malformed')
    invalid = copy.deepcopy(raw)
    invalid.update(passed=False, errors=[{'code': 'duration_exceeded', 'path': '/workouts/0'}])
    carried = plan_review.review_draft(None, invalid, messages, equipment)
    assert carried['findingsAssessment'] == reviewed['review']['assessment']
    tool(carried, 'numerical')
    state = request_planning_state(_messages_for_api(messages, True, provided_equipment=equipment))
    assert 'findingsAssessment' not in state['repairTask']
    assert 'previousReviewFindings' not in state['lastAudit']
    pending = state['repairTask']['pendingReviewObligations']
    assert len(pending) == len(reviewed['review']['findings'])
    assert all(item['mappingStatus'] in ('mapped', 'ambiguous', 'source_unavailable', 'changed', 'requires_current_reassessment')
               for item in pending)
    from workout_generator_pkg.planner_context import planner_response_profile
    profile = planner_response_profile(state)
    assert profile['reasoning_effort'] == 'low' and profile['max_tokens'] == 16384
    # An unchanged, source-accounted refresh retains the known candidate feedback.
    from workout_generator_pkg.planning_tools import set_workout_requirements, requirements_metadata_equivalent
    refreshed = set_workout_requirements({'baseRequirementsId': stored['requirementsId'],
        'requirementAccounting': [{'instruction': 'Plan 5-6 chest sets', 'sourceReferences': ['SOURCE_0'],
            'requirementPaths': ['/auditTargets/weeklyEffectiveSets/chest/minimum',
                                 '/auditTargets/weeklyEffectiveSets/chest/maximum'],
            'priority': 'mandatory', 'enforcement': 'constraint',
            'reason': 'The user explicitly requested a weekly chest-set range.'}]}, messages, equipment)
    assert requirements_metadata_equivalent(stored, refreshed)
    messages.extend(requirement_messages(refreshed)[1:])
    updated = request_planning_state(_messages_for_api(messages, True, provided_equipment=equipment))
    assert updated['draftRequiresReaudit'] and not updated.get('savedDraftReaudit')
    assert 'findingsAssessment' not in updated['repairTask']
    assert 'previousReviewFindings' not in updated['lastAudit']
    assert len(updated['repairTask']['pendingReviewObligations']) == len(reviewed['review']['findings'])
    assert updated['lastAudit']['priorRequirementsFeedback']
    assert requirements_metadata_equivalent(stored, refreshed)
    changed = copy.deepcopy(refreshed)
    changed['requirements']['auditTargets']['maximumSessionSeconds'] = 2000
    assert not requirements_metadata_equivalent(stored, changed)


@pytest.mark.parametrize('as_patch', [False, True])
def test_complete_candidate_uses_owned_contracts_and_joint_solver_before_review(monkeypatch, as_patch):
    from workout_generator_pkg.interactive_shell import handle_function_call
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    prior = audit_workout_plan(draft, equipment, messages)
    review = {'inputHash': 'prior-review', 'findings': [{'severity': 'warning', 'message': 'Repair progression and placement.',
        'draftPath': '/workouts/0/exercises/0/progressionPlan'}]}
    review['assessment'] = {'version': assessment.VERSION, 'inputHash': assessment.assessment_hash(review),
        'groups': [{'findingIndexes': [0], 'disposition': 'repair', 'repairDimensions': ['guidance'], 'reason': 'Supported source goals.'}],
        'repairPlan': 'Repair both together.'}
    prior.update(passed=False, review=review)
    messages.extend([{'role': 'assistant', 'tool_calls': [{'id': 'prior', 'function': {'name': 'audit_workout_plan'}}]},
        {'role': 'tool', 'tool_call_id': 'prior', 'content': json.dumps(prior)}])
    seen = []
    def qualify(client, prepared, *args, **kwargs):
        seen.append(prepared['reviewFeedbackByDefinition'])
        return {'inputHash': 'owned-contract', 'contracts': [{'definition_id': 'LIBRARY_0', 'satisfiesCoverage': [],
            'progressionPlan': {'kind': 'reps', 'nextDefinitionId': None, 'nextDefinitionName': None}}]}
    monkeypatch.setattr('workout_generator_pkg.recipe_contracts.qualify_recipe_contracts', qualify)
    monkeypatch.setattr(plan_review, 'chat_call', lambda *a, **k: ('{"findings":[]}', None, None))
    before = copy.deepcopy(draft)
    submission = ({'requirementsId': stored['requirementsId'], 'baseDraftId': prior['currentDraftId'],
        'patch': [{'op': 'replace', 'path': '/workouts/0/exercises/0/placementNotes', 'value': 'Coordinated patch candidate'}]}
        if as_patch else draft)
    expected_placement_notes = ('Coordinated patch candidate' if as_patch
        else draft['workouts'][0]['exercises'][0]['placementNotes'])
    ownership_context = {'workoutRefsByPosition': ['WORKOUT_0'],
        'exerciseRefsByWorkout': {'WORKOUT_0': ['EXERCISE_0']},
        'initialExerciseRefsByWorkout': {'WORKOUT_0': ['EXERCISE_0']},
        'initialDefinitionByExerciseRef': {'EXERCISE_0': 'LIBRARY_0'}, 'typedEdits': {}}
    result = json.loads(handle_function_call(None, messages, 'audit_workout_plan', submission, equipment,
        coordinated_repair=ownership_context)['result'])
    assert result['passed'] and result['coordinatedJointPlanning']['feasible']
    assert len(seen) == 1 and list(seen[0]) == ['LIBRARY_0'] and draft == before
    item = result['submittedDraft']['workouts'][0]['exercises'][0]
    assert item['progressionPlan']['kind'] == 'reps' and item['progressionMethod'] == 'sourceDefined'
    assert result['recipeQualification']['inputHash'] == 'owned-contract'
    assert item['placementNotes'] == expected_placement_notes
    assert result['submittedDraft']['name'] == draft['name']


def test_qualified_candidate_with_only_solver_numeric_errors_reaches_joint_solver(monkeypatch):
    from workout_generator_pkg import interactive_shell
    from workout_generator_pkg.joint_planning import solve_prescribed_week
    from workout_generator_pkg.planning_tools import set_workout_requirements

    equipment, requirements, _, draft = planning_case()
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 1, 'maximum': 6}
    requirements['auditTargets']['perSessionEffectiveSets']['chest'] = {'minimum': 1, 'maximum': 6}
    requirements['auditTargets']['maximumSessionSeconds'] = 600
    stored = set_workout_requirements(requirements, [{'role': 'user', 'content':
        'Plan 1 to 6 chest sets, with a maximum session duration of 10 minutes.'}], equipment)
    draft['requirementsId'] = stored['requirementsId']
    messages = requirement_messages(stored)
    baseline = audit_workout_plan(draft, equipment, messages)
    assert not baseline['passed'] and [error['code'] for error in baseline['errors']] == ['duration_exceeded']
    real_audit = interactive_shell.audit_workout_plan
    audit_calls = []

    def counted_audit(*args, **kwargs):
        result = real_audit(*args, **kwargs)
        audit_calls.append(result)
        return result

    solve_calls = []
    def counted_solve(*args, **kwargs):
        result = solve_prescribed_week(*args, **kwargs)
        solve_calls.append(result)
        return result

    monkeypatch.setattr(interactive_shell, 'audit_workout_plan', counted_audit)
    monkeypatch.setattr('workout_generator_pkg.allocation.qualify_coordinated_candidate',
        lambda _client, args, *_a, **_k: (args, {'inputHash': 'qualified', 'contracts': []}))
    monkeypatch.setattr('workout_generator_pkg.joint_planning.solve_prescribed_week', counted_solve)
    monkeypatch.setattr(plan_review, 'chat_call', lambda *a, **k: ('{"findings":[]}', None, None))

    result = json.loads(interactive_shell.handle_function_call(None, messages, 'audit_workout_plan',
        draft, equipment, coordinated_repair=True)['result'])

    assert len(solve_calls) == 1 and solve_calls[0]['feasible']
    assert len(audit_calls) == 2 and audit_calls[1]['passed']
    assert result['passed'] and result['coordinatedJointPlanning']['feasible']
    assert result['submittedDraft']['workouts'][0]['exercises'][0]['numWorkSets'] < draft['workouts'][0]['exercises'][0]['numWorkSets']


def test_coordinated_repair_reuses_valid_objective_receipt_after_candidate_audit(monkeypatch):
    from workout_generator_pkg.interactive_shell import handle_function_call
    from workout_generator_pkg.joint_planning import SELECTION_POLICY_VERSION, joint_objective_input_fingerprint
    from workout_generator_pkg.planning_tools import library_fingerprint

    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    prior = audit_workout_plan(draft, equipment, messages)
    prior.update(requirementsId=stored['requirementsId'], libraryFingerprint=library_fingerprint(equipment),
        historyFingerprint=None, review={'inputHash': 'prior-review', 'findings': [{'severity': 'warning'}],
            'assessment': {'version': assessment.VERSION, 'inputHash': 'assessment-hash',
                'groups': [{'findingIndexes': [0], 'disposition': 'repair', 'repairDimensions': ['guidance'], 'reason': 'Reorder while preserving the prescription.'}],
                'repairPlan': 'Change the exercise order only.'}})
    prior['coordinatedJointPlanning'] = {'feasible': True, 'status': 'optimal',
        'selectionPolicyVersion': SELECTION_POLICY_VERSION, 'objectivePolicy': 'preserve_candidate_only',
        'preserveSourceSelection': True,
        'approvedObjectiveOrder': None, 'objectiveInputFingerprint': joint_objective_input_fingerprint(
            draft['workouts'], stored['requirements'], equipment, preserve_source_selection=True), 'objectiveProgress': []}
    messages.extend([{'role': 'assistant', 'tool_calls': [{'id': 'prior', 'function': {'name': 'audit_workout_plan'}}]},
        {'role': 'tool', 'tool_call_id': 'prior', 'content': json.dumps(prior)}])
    monkeypatch.setattr('workout_generator_pkg.allocation.qualify_coordinated_candidate',
        lambda _client, args, *_a, **_k: (args, {'inputHash': 'fresh-qualification', 'contracts': []}))
    monkeypatch.setattr('workout_generator_pkg.joint_planning.solve_prescribed_week',
        lambda *_a, **_k: pytest.fail('A matching feasible objective receipt should avoid reoptimization'))
    monkeypatch.setattr(plan_review, 'chat_call', lambda *a, **k: ('{"findings":[]}', None, None))

    result = json.loads(handle_function_call(None, messages, 'audit_workout_plan', draft, equipment,
        coordinated_repair=True)['result'])

    assert result['passed'] and result['coordinatedJointPlanning']['reusedForValidatedCandidate']
    assert result['coordinatedJointPlanning']['status'] == 'optimal'


def test_unproven_joint_receipt_cannot_shortcut_coordinated_solve():
    from workout_generator_pkg.allocation import reusable_joint_receipt
    from workout_generator_pkg.joint_planning import SELECTION_POLICY_VERSION, joint_objective_input_fingerprint
    from workout_generator_pkg.planning_tools import library_fingerprint

    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    owner = {'requirementsId': stored['requirementsId'], 'libraryFingerprint': library_fingerprint(equipment),
        'historyFingerprint': None, 'coordinatedJointPlanning': {'feasible': False, 'status': 'unproven',
            'selectionPolicyVersion': SELECTION_POLICY_VERSION, 'objectivePolicy': 'preserve_candidate_only',
            'preserveSourceSelection': False,
            'approvedObjectiveOrder': None, 'objectiveInputFingerprint': joint_objective_input_fingerprint(
                draft['workouts'], stored['requirements'], equipment, messages=messages)}}
    assert reusable_joint_receipt(owner, stored['requirementsId'], draft['workouts'], stored['requirements'],
        equipment, messages) is None


@pytest.mark.parametrize('change_source, expected_reuse', [(False, True), (True, False)])
def test_coordinated_repair_reuses_findings_across_equivalent_metadata_refresh_only(
        monkeypatch, change_source, expected_reuse):
    from workout_generator_pkg.allocation import qualify_coordinated_candidate
    from workout_generator_pkg.planning_tools import _latest_result

    equipment, _, stored, draft = planning_case()
    draft['workouts'][0]['exercises'][0]['placementNotes'] = 'Use a controlled, repeatable range of motion.'
    messages = requirement_messages(stored)
    _, original_receipt = _latest_result(messages, 'set_workout_requirements')
    prior = audit_workout_plan(draft, equipment, messages)
    review = {'inputHash': 'prior-review', 'findings': [{'severity': 'warning', 'message': 'Repair progression.',
        'draftPath': '/workouts/0/exercises/0'}]}
    review['assessment'] = {'version': assessment.VERSION, 'inputHash': assessment.assessment_hash(review),
        'groups': [{'findingIndexes': [0], 'disposition': 'repair', 'repairDimensions': ['guidance'], 'reason': 'Supported source goals.'}],
        'repairPlan': 'Repair progression.'}
    prior.update(passed=False, review=review)
    messages.extend([{'role': 'assistant', 'tool_calls': [{'id': 'prior', 'function': {'name': 'audit_workout_plan'}}]},
        {'role': 'tool', 'tool_call_id': 'prior', 'content': json.dumps(prior)}])

    refreshed = copy.deepcopy(original_receipt)
    refreshed['requirementsId'] = 'REQUIREMENTS_METADATA_REFRESH'
    refreshed['requirements']['notes'] = refreshed['requirements'].get('notes', '') + ' Keep the user wording.'
    if change_source:
        refreshed['sourceMessages'] = [*refreshed['sourceMessages'],
            {'role': 'user', 'content': 'A newly clarified source requirement.'}]
    messages.extend(requirement_messages(refreshed))

    calls = []
    def qualify(client, prepared, active_requirements, *args, **kwargs):
        calls.append((prepared['reviewFeedbackByDefinition'].get('LIBRARY_0'), active_requirements['requirementsId']))
        return {'inputHash': 'fresh-contract', 'contracts': [{'definition_id': 'LIBRARY_0',
            'satisfiesCoverage': [],
            'progressionPlan': {'kind': 'reps', 'nextDefinitionId': None, 'nextDefinitionName': None}}]}
    monkeypatch.setattr('workout_generator_pkg.recipe_contracts.qualify_recipe_contracts', qualify)

    candidate, qualification = qualify_coordinated_candidate(None,
        {'requirementsId': refreshed['requirementsId'], 'name': draft['name'],
         'workouts': copy.deepcopy(draft['workouts'])},
        equipment, messages)
    if expected_reuse:
        assert qualification['inputHash'] == 'fresh-contract'
        assert calls == [([{'findingIndex': 0, 'reason': 'Supported source goals.',
            'finding': review['findings'][0]}], refreshed['requirementsId'])]
        assert 'progressionMethod' not in candidate['workouts'][0]['exercises'][0]
        assert candidate['workouts'][0]['exercises'][0]['placementNotes'] == 'Use a controlled, repeatable range of motion.'
    else:
        assert qualification is None and calls == []


def test_coordinated_selection_qualification_preserves_goal_fields_and_occurrence_ownership(monkeypatch):
    from workout_generator_pkg.allocation import qualify_coordinated_candidate

    equipment, _, stored, draft = planning_case()
    second_definition = copy.deepcopy(equipment['exerciseDefinitions'][0])
    second_definition['id'] = 'LIBRARY_1'
    second_definition['name'] = 'Alternate press'
    equipment['exerciseDefinitions'].append(second_definition)
    first = copy.deepcopy(draft['workouts'][0]['exercises'][0])
    messages = requirement_messages(stored)
    prior = audit_workout_plan(draft, equipment, messages)
    review = {'inputHash': 'selection-review', 'findings': [{'severity': 'warning', 'message': 'Repair progression.',
        'draftPath': '/workouts/0/exercises/0/progressionPlan'}]}
    review['assessment'] = {'version': assessment.VERSION, 'inputHash': assessment.assessment_hash(review),
        'groups': [{'findingIndexes': [0], 'disposition': 'repair', 'repairDimensions': ['progression'],
                    'reason': 'Repair progression for this occurrence.'}], 'repairPlan': 'Repair progression.'}
    prior.update(passed=False, review=review)
    messages.extend([{'role': 'assistant', 'tool_calls': [{'id': 'selection-review',
        'function': {'name': 'audit_workout_plan'}}]},
        {'role': 'tool', 'tool_call_id': 'selection-review', 'content': json.dumps(prior)}])
    monkeypatch.setattr('workout_generator_pkg.review_assessment.latest_assessment',
        lambda *_args, **_kwargs: review['assessment'])

    monkeypatch.setattr('workout_generator_pkg.exercise_library_tools.get_exercise_candidates',
        lambda args, *_: {'exercises': [copy.deepcopy(item) for item in equipment['exerciseDefinitions']
            if item['id'] in args['definition_ids']]})
    monkeypatch.setattr('workout_generator_pkg.recipe_contracts.qualify_recipe_contracts',
        lambda *_args, **_kwargs: {'inputHash': 'qualified-all', 'contracts': [
                {'definition_id': 'LIBRARY_0', 'progressionPlan': {'kind': 'reps', 'nextDefinitionId': None,
                    'nextDefinitionName': None},
             'satisfiesCoverage': ['original']},
            {'definition_id': 'LIBRARY_1', 'progressionMethod': 'sourceDefined',
                 'progressionPlan': {'kind': 'reps', 'nextDefinitionId': None,
                    'nextDefinitionName': None}, 'satisfiesCoverage': ['alternate']}]})

    candidate = copy.deepcopy(draft)
    candidate['workouts'][0]['exercises'][0].update(
        definition_id='LIBRARY_1', progressionMethod='doubleProgression',
            progressionPlan={'kind': 'reps', 'nextDefinitionId': None, 'nextDefinitionName': None})
    unchanged_duplicate = copy.deepcopy(candidate['workouts'][0]['exercises'][0])
    unchanged_duplicate.update(definition_id='LIBRARY_0', progressionMethod='sourceDefined')
    unchanged_duplicate['progressionPlan'] = {'kind': 'reps', 'nextDefinitionId': None,
        'nextDefinitionName': None, 'atCeilingAction': 're_audit_higher_reps'}
    candidate['workouts'][0]['exercises'].append(unchanged_duplicate)
    added_occurrence = copy.deepcopy(candidate['workouts'][0]['exercises'][0])
    added_occurrence['satisfiesCoverage'] = ['authored_for_new_exercise']
    candidate['workouts'][0]['exercises'].append(added_occurrence)
    context = {'workoutRefsByPosition': ['WORKOUT_0'],
        'exerciseRefsByWorkout': {'WORKOUT_0': ['EXERCISE_0', 'EXERCISE_1', 'NEW_EXERCISE_0']},
        'initialExerciseRefsByWorkout': {'WORKOUT_0': ['EXERCISE_0', 'EXERCISE_1']},
        'initialDefinitionByExerciseRef': {'EXERCISE_0': 'LIBRARY_0', 'EXERCISE_1': 'LIBRARY_0'},
        'typedEdits': {'exerciseUpdates': [{'exerciseRef': 'EXERCISE_0', 'setFields': {
            'definition_id': 'LIBRARY_1', 'progressionMethod': 'doubleProgression',
                    'progressionPlan': {'kind': 'reps', 'nextDefinitionId': None, 'nextDefinitionName': None}}}],
            'exerciseAdditions': [{'temporaryId': 'NEW_EXERCISE_0', 'exercise': added_occurrence}]}}

    result, qualification = qualify_coordinated_candidate(None,
        candidate, equipment, messages,
        coordinated_repair_context=context)

    selected, unchanged_duplicate, added_result = result['workouts'][0]['exercises']
    assert qualification['inputHash'] == 'qualified-all'
    assert selected['definition_id'] == 'LIBRARY_1'
    assert selected['progressionMethod'] == 'doubleProgression'
    assert selected['progressionPlan'] == {'kind': 'reps', 'nextDefinitionId': None, 'nextDefinitionName': None}
    assert selected['satisfiesCoverage'] == ['alternate']
    assert unchanged_duplicate['definition_id'] == 'LIBRARY_0'
    assert unchanged_duplicate['progressionMethod'] == 'sourceDefined'
    assert unchanged_duplicate['progressionPlan']['atCeilingAction'] == 're_audit_higher_reps'
    assert 'satisfiesCoverage' not in unchanged_duplicate
    assert added_result['progressionMethod'] == 'doubleProgression'
    assert added_result['progressionPlan'] == selected['progressionPlan']
    assert added_result['satisfiesCoverage'] == ['authored_for_new_exercise']


def test_latest_recipe_qualification_survives_a_later_tool_result_without_it():
    from workout_generator_pkg.allocation import _latest_recipe_qualification
    cached = {'inputHash': 'cached', 'inputHashes': {'LIBRARY_0': 'definition-hash'},
        'contracts': [{'definition_id': 'LIBRARY_0', 'progressionPlan': {'kind': 'reps'}}]}
    messages = [
        {'role': 'assistant', 'tool_calls': [{'id': 'draft', 'function': {'name': 'draft_workout_sessions'}}]},
        {'role': 'tool', 'tool_call_id': 'draft', 'content': json.dumps({'recipeQualification': cached})},
        {'role': 'assistant', 'tool_calls': [{'id': 'metadata-failure', 'function': {'name': 'audit_workout_plan'}}]},
        {'role': 'tool', 'tool_call_id': 'metadata-failure', 'content': json.dumps({'passed': False, 'errors': [{'code': 'invalid_draft_patch'}]})},
    ]
    assert _latest_recipe_qualification(messages) == cached


def test_open_finding_is_rebased_after_reordering_instead_of_copying_stale_indices(monkeypatch):
    from workout_generator_pkg.planning_tools import set_workout_requirements
    equipment, requirements, _, draft = planning_case()
    equipment['exerciseDefinitions'].append({**copy.deepcopy(equipment['exerciseDefinitions'][0]), 'id': 'z_other', 'name': 'Other press'})
    requirements['auditTargets']['maximumSessionSeconds'] = 3000
    stored = set_workout_requirements(requirements, [{'role': 'user', 'content': 'Use the available presses.'}], equipment)
    draft['requirementsId'] = stored['requirementsId']
    first = draft['workouts'][0]['exercises'][0]
    first.update(numWorkSets=2, placementNotes='Use an unconfirmed band.')
    second = {**copy.deepcopy(first), 'definition_id': 'LIBRARY_1', 'numWorkSets': 3, 'placementNotes': 'No band.'}
    draft['workouts'][0]['exercises'].append(second)
    messages = requirement_messages(stored)
    def respond(client, request, **options):
        context = json.loads(request[-1]['content'])
        if context.get('previousBlockingFindings'):
            return json.dumps({'findings': [], 'blockerResolutions': {key: {'status': 'open', 'action': 'repair',
                'reason': 'The moved exercise at position 1 still needs an unconfirmed band.',
                'evidencePaths': ['/draft/exercises/1/placementNotes']} for key in context['previousBlockingFindings']}}), None, None
        return json.dumps({'findings': [{'severity': 'blocking', 'action': 'repair', 'basis': 'established_violation', 'muscleTargets': [],
            'path': '/draft/exercises/0/placementNotes', 'message': 'EXERCISE_0 needs an unconfirmed band.',
            'evidencePaths': ['/draft/exercises/0/placementNotes'], 'repair': 'Remove the unconfirmed band.'}]}), None, None
    monkeypatch.setattr(plan_review, 'chat_call', respond)
    monkeypatch.setattr(assessment, '_review_call', lambda *a, **k: (json.dumps({'groups': [
        {'findingIndexes': [0], 'disposition': 'repair', 'repairDimensions': ['guidance'], 'reason': 'A supported setup contradiction remains.'}], 'repairPlan': 'Correct the cited current setup.'}), None, None))
    initial = plan_review.review_draft(None, audit_workout_plan(draft, equipment, messages), messages, equipment)
    messages.extend([{'role': 'assistant', 'tool_calls': [{'id': 'prior', 'function': {'name': 'audit_workout_plan'}}]},
        {'role': 'tool', 'tool_call_id': 'prior', 'content': json.dumps(initial)}])
    raw = audit_workout_plan({'requirementsId': stored['requirementsId'], 'baseDraftId': initial['currentDraftId'],
        'patch': [{'op': 'replace', 'path': '/workouts/0/exercises', 'value': [second, first]}]}, equipment, messages)
    result = plan_review.review_draft(None, raw, messages, equipment)
    assert not result['passed']
    assert result['errors'][0]['message'] == 'The moved exercise at position 1 still needs an unconfirmed band.'
    assert result['errors'][0]['draftPath'] == '/workouts/0/exercises/1/placementNotes'


def test_review_error_requires_current_source_and_data_proof_and_cannot_waive_numeric_failure(monkeypatch):
    from workout_generator_pkg.repair_capabilities import repair_capability_contract

    context = {'requirements': {'perSessionPushMinimum': None, 'auditTargets': {}}, 'draft': {'workouts': [{'pushSets': 4}]}}
    context['repairCapabilityContract'] = repair_capability_contract()
    reviewed = {'inputHash': 'current-context', 'findings': [{'severity': 'blocking', 'message': 'Five push sets are mandatory.'}]}
    _, facts = plan_review._with_review_refs(context)
    refs = {path: reference for reference, path in facts.items()}
    group = {'findingIndexes': [0], 'disposition': 'withdrawn_review_error', 'repairDimensions': [],
        'reason': 'The approved requirements contain no per-session push minimum; four sets do not violate an invented five-set requirement.',
        'errorKind': 'unsupported_requirement', 'authorityEvidenceRefs': [refs['/requirements']],
        'currentDataEvidenceRefs': [refs['/draft/workouts/0']]}
    monkeypatch.setattr(assessment, '_review_call', lambda *a, **k: (json.dumps({'groups': [group], 'repairPlan': ''}), None, None))
    reviewed['assessment'] = assessment.assess_findings(None, context, reviewed)
    assessment.validate_assessment(reviewed, context)
    changed = copy.deepcopy(context)
    changed['draft']['workouts'][0]['pushSets'] = 0
    with pytest.raises(ValueError, match='stale'):
        assessment.validate_assessment(reviewed, changed)
    del reviewed['assessment']['groups'][0]['evidenceHash']
    with pytest.raises(ValueError, match='missing'):
        assessment.validate_assessment(reviewed, context)
    equipment, _, stored, draft = planning_case()
    raw = audit_workout_plan(draft, equipment, requirement_messages(stored))
    raw.update(passed=False, errors=[{'code': 'volume_below_target', 'path': '/workouts'}])
    monkeypatch.setattr(plan_review, 'assess_findings', lambda *a, **k: pytest.fail('Numerical failures cannot be adjudicated away'))
    result = plan_review.review_draft(None, raw, requirement_messages(stored), equipment)
    assert not result['passed'] and result['errors'][0]['code'] == 'volume_below_target'


def _bind_disputed_assessment(review, context):
    context.setdefault('requirements', {})
    for finding in review['findings']:
        finding.setdefault('severity', 'warning')
    for group in review['assessment']['groups']:
        group.update(errorKind='unsupported_requirement', evidencePaths=['/requirements', '/draft'])
        group['evidenceHash'] = assessment._error_evidence(context, group)
    review['assessment'].update(version=assessment.VERSION, inputHash=assessment.assessment_hash(review))


def test_review_corrections_batch_all_disputes_by_scope_and_fail_closed(monkeypatch):
    review = {'inputHash': 'current-review', 'findings': [
        {'message': 'Execution claim A.', 'reviewScope': 'execution'},
        {'message': 'Evidence claim B.', 'reviewScope': 'evidence'},
        {'message': 'Execution claim B.', 'reviewScope': 'execution'},
        {'message': 'Evidence claim C.', 'reviewScope': 'evidence'}],
        'assessment': {'repairPlan': 'Original plan.', 'groups': [
            {'findingIndexes': [0], 'disposition': 'withdrawn_review_error', 'repairDimensions': [], 'reason': 'A is unsupported.'},
            {'findingIndexes': [1, 2], 'disposition': 'withdrawn_review_error', 'repairDimensions': [], 'reason': 'B is unsupported.'},
            {'findingIndexes': [3], 'disposition': 'withdrawn_review_error', 'repairDimensions': [], 'reason': 'C is unsupported.'}]}}
    calls = []
    monkeypatch.setattr(plan_review, '_execution_review_context', lambda context: {'scope': 'execution'})
    monkeypatch.setattr(plan_review, '_evidence_review_context', lambda context, ids: {'scope': 'evidence'})
    def confirm(client, scope, part, *args):
        calls.append((scope, copy.deepcopy(part)))
        resolutions = {key: {'status': 'withdrawn_review_error', 'reason': 'Confirmed from current source and data.',
                            'evidencePaths': ['/requirements', '/draft']}
                      for key in part['previousBlockingFindings']}
        if scope == 'execution':
            resolutions['DISPUTE_2'].update(status='open', disposition='repair', repairDimensions=['guidance'])
        return {'findings': [],
                'blockerResolutions': resolutions}
    monkeypatch.setattr(plan_review, '_review_part', confirm)

    context = {'draft': {'exercises': []}, 'sourceMessages': []}
    _bind_disputed_assessment(review, context)
    plan_review._confirm_review_corrections(None, context, review, {}, [], 0, None)

    assert [scope for scope, _ in calls] == ['execution', 'evidence']
    assert all(part['confirmationOnly'] is True for _, part in calls)
    assert set(calls[0][1]['previousBlockingFindings']) == {'DISPUTE_0', 'DISPUTE_2'}
    assert set(calls[1][1]['previousBlockingFindings']) == {'DISPUTE_1', 'DISPUTE_3'}
    groups = review['assessment']['groups']
    assert groups[0]['reviewerConfirmation']['inputHash'] == 'current-review'
    assert [group['findingIndexes'] for group in groups] == [[0], [1], [2], [3]]
    assert [group['disposition'] for group in groups] == [
        'withdrawn_review_error', 'withdrawn_review_error', 'repair', 'withdrawn_review_error']
    assert groups[2]['repairDimensions'] == ['guidance']
    assert set(groups[1]['reviewerConfirmation']['resolutions']) == {'DISPUTE_1'}
    assessment.validate_assessment(review, context, require_confirmation=True)
    assert 'do not waive them' in review['assessment']['repairPlan']


def test_confirmation_only_review_skips_full_required_checks(monkeypatch):
    part = {'reviewedExerciseIds': ['EXERCISE_0'], 'previousBlockingFindings': {
        'DISPUTE_0': {'message': 'The claim conflicts with the source.'}}, 'confirmationOnly': True,
        'sourceMessages': [{'role': 'user', 'content': 'Preserve the requested equipment restriction.'}],
        'requirements': {'equipmentRestrictions': ['barbell']},
        'history': {'entries': [{'exercise': 'Row', 'weight': 40}]},
        'auditPolicy': {'supportedMuscleTargets': []}}
    context = {'draft': {'workouts': [{'id': 'WORKOUT_0', 'name': 'Session'}],
                        'exercises': [{'id': 'EXERCISE_0'}]},
        'auditPolicy': {'supportedMuscleTargets': []}, 'sourceMessages': []}
    result = {'planIndex': {}, 'submittedDraft': {}}
    monkeypatch.setattr(plan_review, '_with_review_refs', lambda value: (copy.deepcopy(value), {'FACT_0': '/draft/exercises/0'}))
    monkeypatch.setattr(plan_review, '_review_pointer', lambda context, path, root='/draft': path)
    seen = {}
    calls = []
    def call(client, request, **kwargs):
        seen['request'] = request
        seen['schema'] = kwargs['output_schema']
        calls.append(request)
        status = 'resolved_by_change' if len(calls) == 1 else 'withdrawn_review_error'
        return json.dumps({'findings': [], 'blockerResolutions': {'ISSUE_0': {
            'status': status, 'reason': 'Current evidence disproves the claim.',
            'disposition': 'withdrawn_review_error', 'repairDimensions': [],
            'evidencePaths': ['FACT_0']}}}), None, None
    monkeypatch.setattr(plan_review, '_review_call', call)

    checked = plan_review._review_part(None, 'evidence', part, context, result, [], 0, None)

    request_context = json.loads(calls[0][-1]['content'])
    assert 'requiredChecks' not in request_context
    assert request_context['confirmationOnly'] is True
    assert all(key in request_context for key in ('sourceMessages', 'requirements', 'history', 'auditPolicy'))
    assert 'confirmation-only pass' in calls[0][0]['content']
    assert 'do not run a second review or return findings' in calls[0][0]['content']
    assert not checked['findings']
    assert checked['blockerResolutions']['DISPUTE_0']['status'] == 'withdrawn_review_error'
    assert seen['schema']['properties']['blockerResolutions']['properties']['ISSUE_0']['properties']['status']['enum'] == [
        'open', 'withdrawn_review_error']
    assert len(calls) == 2
    assert 'Correct only the response contract error' in calls[1][-1]['content']

    def unexpected_finding(client, request, **kwargs):
        return json.dumps({'findings': [{'severity': 'warning', 'basis': 'uncertainty', 'path': 'FACT_0',
            'evidencePaths': ['FACT_0'], 'message': 'Invented additional finding.', 'repair': 'Repair it.',
            'action': 'repair', 'decisionId': None, 'newConflictEvidencePaths': [], 'muscleTargets': []}],
            'blockerResolutions': {'ISSUE_0': {'status': 'withdrawn_review_error',
                'reason': 'Current evidence disproves the claim.', 'evidencePaths': ['FACT_0']}}}), None, None
    monkeypatch.setattr(plan_review, '_review_call', unexpected_finding)
    with pytest.raises(ValidationError):
        plan_review._review_part(None, 'evidence', part, context, result, [], 0, None)


def test_confirmation_response_corrects_missing_repair_owner_without_repeating_review(monkeypatch):
    context = {'draft': {'exercises': [{'id': 'EXERCISE_0'}], 'workouts': []}, 'sourceMessages': [],
               'auditPolicy': {'supportedMuscleTargets': []}}
    part = {'confirmationOnly': True, 'previousBlockingFindings': {
        'DISPUTE_0': {'severity': 'blocking', 'message': 'The prescription remains unsuitable.'}}}
    monkeypatch.setattr(plan_review, '_with_review_refs', lambda value: (copy.deepcopy(value), {'FACT_0': '/draft'}))
    monkeypatch.setattr(plan_review, '_review_pointer', lambda context, path, root='/draft': path)
    calls = []
    def respond(client, request, **options):
        calls.append((request, options))
        return json.dumps({'findings': [], 'blockerResolutions': {'ISSUE_0': {
            'status': 'open', 'disposition': 'repair',
            'repairDimensions': [] if len(calls) == 1 else ['prescription'],
            'reason': 'Change the supported prescription within approved constraints.',
            'evidencePaths': ['FACT_0']}}}), None, None
    monkeypatch.setattr(plan_review, '_review_call', respond)

    checked = plan_review._review_part(None, 'evidence', part, context, {}, [], 0, None)

    assert len(calls) == 2
    assert checked['findings'] == []
    assert checked['blockerResolutions']['DISPUTE_0']['repairDimensions'] == ['prescription']
    assert checked['blockerResolutions']['DISPUTE_0']['evidencePaths'] == ['/draft']
    correction = json.loads(calls[1][0][-1]['content'])
    assert 'Correct only the response contract error' in correction['task']
    assert 'supported repair dimensions' in correction['validationError']


def test_completed_confirmation_scope_is_reused_after_later_scope_failure(monkeypatch):
    review = {'inputHash': 'review-hash', 'findings': [
        {'message': 'Execution claim.', 'reviewScope': 'execution'},
        {'message': 'Evidence claim.', 'reviewScope': 'evidence'}],
        'assessment': {'repairPlan': 'Keep valid source corrections.', 'groups': [
            {'findingIndexes': [0], 'disposition': 'withdrawn_review_error', 'repairDimensions': [], 'reason': 'Execution claim unsupported.'},
            {'findingIndexes': [1], 'disposition': 'withdrawn_review_error', 'repairDimensions': [], 'reason': 'Evidence claim contradicted.'}]}}
    monkeypatch.setattr(plan_review, '_execution_review_context', lambda context: {'scope': 'execution'})
    monkeypatch.setattr(plan_review, '_evidence_review_context', lambda context, ids: {'scope': 'evidence'})
    calls = []
    fail_evidence = True
    def confirm(client, scope, part, *args):
        nonlocal fail_evidence
        calls.append(scope)
        if scope == 'evidence' and fail_evidence:
            fail_evidence = False
            raise RuntimeError('temporary evidence confirmation error')
        return {'findings': [], 'blockerResolutions': {
            key: {'status': 'withdrawn_review_error', 'reason': 'Current source and evidence disprove the claim.',
                  'evidencePaths': ['/draft/workouts/0/name']}
            for key in part['previousBlockingFindings']}}
    monkeypatch.setattr(plan_review, '_review_part', confirm)
    context = {'draft': {'exercises': [], 'workouts': []}, 'sourceMessages': []}
    _bind_disputed_assessment(review, context)

    with pytest.raises(RuntimeError, match='temporary'):
        plan_review._confirm_review_corrections(None, context, review, {}, [], 0, None)
    assert review['confirmationProgress']['outcomes']['execution']['disputeIds'] == ['DISPUTE_0']

    changed_assessment = copy.deepcopy(review)
    changed_assessment['assessment']['repairPlan'] += ' Revised coordinated decision.'
    plan_review._confirm_review_corrections(None, context, changed_assessment, {}, [], 0, None)
    assert calls == ['execution', 'evidence', 'execution', 'evidence']
    calls.clear()
    malformed_cache = copy.deepcopy(review)
    malformed_cache['confirmationProgress']['outcomes']['execution']['resolutions'] = []
    plan_review._confirm_review_corrections(None, context, malformed_cache, {}, [], 0, None)
    assert calls == ['execution', 'evidence']
    calls.clear()
    plan_review._confirm_review_corrections(None, context, review, {}, [], 0, None)

    assert calls == ['evidence']
    assert all(group.get('reviewerConfirmation', {}).get('inputHash') == 'review-hash'
               for group in review['assessment']['groups'])
    assert 'confirmationProgress' not in review


@pytest.mark.parametrize(('severity', 'disposition', 'dimensions'), [
    ('blocking', 'repair', ['prescription']),
    ('warning', 'advisory', []),
    ('blocking', 'unresolved_capability', []),
])
def test_upheld_dispute_becomes_a_valid_assessment_without_guessing_an_owner(
        monkeypatch, severity, disposition, dimensions):
    context = {'draft': {'exercises': []}, 'sourceMessages': []}
    review = {'inputHash': 'retained-confirmation-transition',
        'findings': [{'severity': severity, 'reviewScope': 'execution', 'message': 'Disputed finding.',
                      'repair': 'Resolve against the current source and supported fields.'}],
        'assessment': {'repairPlan': '', 'groups': [{'findingIndexes': [0],
            'disposition': 'withdrawn_review_error', 'repairDimensions': [], 'reason': 'Proposed withdrawal.'}]}}
    _bind_disputed_assessment(review, context)
    monkeypatch.setattr(plan_review, '_execution_review_context', lambda context: {})
    monkeypatch.setattr(plan_review, '_review_part', lambda *args: {'findings': [], 'blockerResolutions': {
        'DISPUTE_0': {'status': 'open', 'disposition': disposition, 'repairDimensions': dimensions,
            'reason': 'Current evidence establishes the stated disposition.', 'evidencePaths': ['/draft']}}})

    plan_review._confirm_review_corrections(None, context, review, {}, [], 0, None)

    validated = assessment.validate_assessment(review, context, require_confirmation=True)
    assert validated['groups'][0]['disposition'] == disposition
    assert validated['groups'][0]['repairDimensions'] == dimensions
    assert bool(validated['repairPlan']) == (disposition == 'repair')
    assert bool(plan_review._actionable_review_errors(review)) == (disposition != 'advisory')


@pytest.mark.parametrize('resolution', [
    {},
    {'status': 'open', 'disposition': 'repair', 'repairDimensions': []},
    {'status': 'open', 'disposition': 'advisory', 'repairDimensions': []},
    {'status': 'open', 'disposition': 'repair', 'repairDimensions': ['invented']},
])
def test_invalid_confirmation_cannot_mutate_assessment_or_waive_a_blocker(monkeypatch, resolution):
    context = {'draft': {'exercises': []}, 'sourceMessages': []}
    review = {'inputHash': 'unchanged-review', 'findings': [{'severity': 'blocking', 'reviewScope': 'execution'}],
        'assessment': {'repairPlan': '', 'groups': [{'findingIndexes': [0],
            'disposition': 'withdrawn_review_error', 'repairDimensions': [], 'reason': 'Proposed withdrawal.'}]}}
    _bind_disputed_assessment(review, context)
    original = copy.deepcopy(review['assessment'])
    monkeypatch.setattr(plan_review, '_execution_review_context', lambda context: {})
    result = ({'DISPUTE_0': {'reason': 'Still unresolved.', 'evidencePaths': ['/draft'], **resolution}}
              if resolution else {})
    monkeypatch.setattr(plan_review, '_review_part', lambda *args: {'findings': [], 'blockerResolutions': result})

    with pytest.raises(ValueError):
        plan_review._confirm_review_corrections(None, context, review, {}, [], 0, None)

    assert review['assessment'] == original


def test_metadata_response_budget_scales_with_all_required_fields():
    from workout_generator_pkg.planner_context import planner_response_profile
    small = planner_response_profile({'metadataOnlyRepair': True, 'repairTask': {'metadataFields': {'/one': {}}}})
    large = planner_response_profile({'metadataOnlyRepair': True, 'repairTask': {'metadataFields': {str(i): {} for i in range(33)}}})
    assert small['max_tokens'] == 2048
    assert large['max_tokens'] == 12672 and large['timeout'] is None


def test_recipe_feedback_is_scoped_to_repair_findings_and_source_exercise():
    from workout_generator_pkg.allocation import _qualification_review_feedback

    findings = [
        {'draftPath': '/workouts/0/exercises/0/restBetweenSetsSeconds', 'message': 'Rest is too short.'},
        {'draftPath': '/workouts/0/exercises/1/progressionPlan', 'message': 'Progression route is invalid.'},
        {'draftPath': '/workouts/0/exercises/2', 'message': 'Whole-exercise suitability needs repair.'},
    ]
    assessment = {'groups': [
        {'findingIndexes': [0], 'disposition': 'repair', 'repairDimensions': ['guidance'], 'reason': 'Correct the rest.'},
        {'findingIndexes': [1], 'disposition': 'repair', 'repairDimensions': ['guidance'], 'reason': 'Correct progression.'},
        {'findingIndexes': [2], 'disposition': 'repair', 'repairDimensions': ['guidance'], 'reason': 'Clarify this exercise.'},
    ], 'repairPlan': 'Preserve LIBRARY_0, repair LIBRARY_1 and LIBRARY_2 together.'}
    audit_result = {'review': {'findings': findings, 'assessment': assessment}, 'submittedDraft': {'workouts': [
        {'exercises': [{'definition_id': 'LIBRARY_0'}, {'definition_id': 'LIBRARY_1'}, {'definition_id': 'LIBRARY_2'}]}]}}

    feedback = _qualification_review_feedback(assessment, audit_result)

    assert set(feedback) == {'LIBRARY_1', 'LIBRARY_2'}
    assert feedback['LIBRARY_1'][0]['findingIndex'] == 1
    assert feedback['LIBRARY_2'][0]['findingIndex'] == 2
