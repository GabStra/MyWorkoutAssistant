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


def test_capability_pause_allows_new_human_resolution_without_dropping_the_finding():
    from workout_generator_pkg.interactive_shell import _repair_capability_pause

    state = {'repairCapabilityUnresolved': {'currentDraftId': 'REVISION_1', 'findingIndexes': [1]}}
    assert _repair_capability_pause(state)
    assert _repair_capability_pause({**state, 'newInstructionPending': True}) is None
    assert _repair_capability_pause({**state, 'planningDecisionNeeded': True}) is None
    assert state['repairCapabilityUnresolved']['findingIndexes'] == [1]


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


def test_assessed_repair_rejects_count_edits_without_silently_dropping_them():
    from workout_generator_pkg.planning_tools import compile_coordinated_repair, coordinated_repair_tool
    _, _, _, current = planning_case()
    before = copy.deepcopy(current)
    task = {'requirementsId': current['requirementsId'], 'baseDraftId': 'REVISION_4',
            'findingsAssessment': {'groups': [{'findingIndexes': [0], 'disposition': 'repair',
                'repairDimensions': ['session_timing']}]}}
    schema = coordinated_repair_tool({**task, 'currentDraft': current})['function']['parameters']
    assert 'numWorkSets' not in schema['properties']['edits']['properties']['exerciseUpdates']['items']['properties']['setFields']['properties']
    arguments = {'requirementsId': current['requirementsId'], 'baseDraftId': 'REVISION_4',
        'addressedFindingIndexes': [0], 'edits': {'exerciseUpdates': [
            {'exerciseRef': 'EXERCISE_0', 'setFields': {'numWorkSets': 99, 'setupSeconds': 90}}]}}
    with pytest.raises(ValidationError, match='numWorkSets'):
        compile_coordinated_repair(arguments, task, current)
    assert current == before and arguments['edits']['exerciseUpdates'][0]['setFields']['numWorkSets'] == 99
    arguments['edits']['exerciseUpdates'][0]['setFields'].pop('numWorkSets')
    compiled, _ = compile_coordinated_repair(arguments, task, current)
    assert compiled['patch'] == [{'op': 'replace', 'path': '/workouts/0/exercises/0/setupSeconds', 'value': 90}]


def test_explicit_superset_detachment_normalizes_only_detached_or_singleton_members():
    from workout_generator_pkg.json_patching import apply_json_patch
    from workout_generator_pkg.planning_tools import compile_coordinated_repair

    _, _, _, current = planning_case()
    first = current['workouts'][0]['exercises'][0]
    first.update(superset='PAIR', restBetweenSetsSeconds=0,
                 restAfterSupersetExerciseSeconds=20)
    second = copy.deepcopy(first)
    second.update(restAfterSupersetExerciseSeconds=90)
    current['workouts'][0]['exercises'].append(second)
    task = {'requirementsId': current['requirementsId'], 'baseDraftId': 'REVISION_21',
        'findingCode': 'independent_review_finding'}
    arguments = {'requirementsId': task['requirementsId'], 'baseDraftId': task['baseDraftId'],
        'edits': {'exerciseUpdates': [
            {'exerciseRef': 'EXERCISE_0', 'setFields': {
                'superset': None, 'restBetweenSetsSeconds': 75}}]}}

    compiled, source_refs = compile_coordinated_repair(arguments, task, current)
    repaired = apply_json_patch(current, compiled['patch'])
    assert repaired['workouts'][0]['exercises'][0]['superset'] is None
    assert repaired['workouts'][0]['exercises'][1]['superset'] is None
    assert [item['restBetweenSetsSeconds'] for item in repaired['workouts'][0]['exercises']] == [75, 90]
    assert all(item['restAfterSupersetExerciseSeconds'] == 0
               for item in repaired['workouts'][0]['exercises'])
    assert any('EXERCISE_1' in refs for refs in source_refs)

    after_rest_only = copy.deepcopy(arguments)
    after_rest_only['edits']['exerciseUpdates'][0]['setFields'] = {
        'superset': None, 'restAfterSupersetExerciseSeconds': 80}
    after_rest_compiled, _ = compile_coordinated_repair(after_rest_only, task, current)
    after_rest_repaired = apply_json_patch(current, after_rest_compiled['patch'])
    assert after_rest_repaired['workouts'][0]['exercises'][0]['restBetweenSetsSeconds'] == 90
    assert after_rest_repaired['workouts'][0]['exercises'][0]['restAfterSupersetExerciseSeconds'] == 0


def test_explicit_detachment_does_not_overwrite_a_partners_new_group():
    from workout_generator_pkg.json_patching import apply_json_patch
    from workout_generator_pkg.planning_tools import compile_coordinated_repair

    _, _, _, current = planning_case()
    first = current['workouts'][0]['exercises'][0]
    first.update(superset='OLD', restBetweenSetsSeconds=0, restAfterSupersetExerciseSeconds=90)
    current['workouts'][0]['exercises'].extend([copy.deepcopy(first), copy.deepcopy(first)])
    current['workouts'][0]['exercises'][2]['superset'] = None
    task = {'requirementsId': current['requirementsId'], 'baseDraftId': 'REVISION_21',
            'findingCode': 'independent_review_finding'}
    updates = [
        {'exerciseRef': 'EXERCISE_0', 'setFields': {'superset': None, 'restBetweenSetsSeconds': 75}},
        {'exerciseRef': 'EXERCISE_1', 'setFields': {'superset': 'NEW', 'restAfterSupersetExerciseSeconds': 20}},
        {'exerciseRef': 'EXERCISE_2', 'setFields': {'superset': 'NEW', 'restAfterSupersetExerciseSeconds': 90}}]
    compiled, _ = compile_coordinated_repair({
        'requirementsId': current['requirementsId'], 'baseDraftId': task['baseDraftId'],
        'edits': {'exerciseUpdates': updates}}, task, current)
    repaired = apply_json_patch(current, compiled['patch'])['workouts'][0]['exercises']
    assert [item['superset'] for item in repaired] == [None, 'NEW', 'NEW']
    assert repaired[1]['restAfterSupersetExerciseSeconds'] == 20


def test_explicit_detachment_preserves_remaining_pair_and_accepts_explicit_reorder():
    from workout_generator_pkg.json_patching import apply_json_patch
    from workout_generator_pkg.planning_tools import compile_coordinated_repair

    _, _, _, current = planning_case()
    first = current['workouts'][0]['exercises'][0]
    first.update(superset='TRIO', restBetweenSetsSeconds=0,
                 restAfterSupersetExerciseSeconds=20)
    for recovery in (30, 90):
        member = copy.deepcopy(first)
        member['restAfterSupersetExerciseSeconds'] = recovery
        current['workouts'][0]['exercises'].append(member)
    task = {'requirementsId': current['requirementsId'], 'baseDraftId': 'REVISION_22',
        'findingCode': 'independent_review_finding'}

    arguments = {'requirementsId': task['requirementsId'], 'baseDraftId': task['baseDraftId'],
        'edits': {'exerciseUpdates': [
            {'exerciseRef': 'EXERCISE_0', 'setFields': {'superset': None}}]}}
    compiled, _ = compile_coordinated_repair(arguments, task, current)
    repaired = apply_json_patch(current, compiled['patch'])
    assert repaired['workouts'][0]['exercises'][0]['superset'] is None
    assert [item['superset'] for item in repaired['workouts'][0]['exercises'][1:]] == ['TRIO', 'TRIO']

    middle_detach = copy.deepcopy(arguments)
    middle_detach['edits']['exerciseUpdates'][0]['exerciseRef'] = 'EXERCISE_1'
    unordered, _ = compile_coordinated_repair(middle_detach, task, current)
    assert unordered['patch']

    middle_detach['edits']['exerciseOrders'] = [{'workoutRef': 'WORKOUT_0',
        'exerciseRefs': ['EXERCISE_0', 'EXERCISE_2', 'EXERCISE_1']}]
    compiled, _ = compile_coordinated_repair(middle_detach, task, current)
    repaired = apply_json_patch(current, compiled['patch'])
    assert [item['superset'] for item in repaired['workouts'][0]['exercises']] == ['TRIO', 'TRIO', None]


def test_assessed_redistribution_owns_superset_recovery_in_combined_repair():
    from workout_generator_pkg.json_patching import apply_json_patch
    from workout_generator_pkg.planning_tools import compile_coordinated_repair, set_workout_requirements

    equipment, requirements, _, current = planning_case()
    requirements['sessionsPerWeek'] = 2
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 11, 'maximum': 11}
    requirements['auditTargets']['perSessionEffectiveSets'] = {}
    stored = set_workout_requirements(requirements,
        [{'role': 'user', 'content': 'Two weekly sessions with eleven chest sets total.'}], equipment)
    current['requirementsId'] = stored['requirementsId']
    source = copy.deepcopy(current['workouts'][0]['exercises'][0])
    source.update(superset='GROUP_A', restBetweenSetsSeconds=0,
                  restAfterSupersetExerciseSeconds=20)
    current['workouts'][0]['exercises'][0] = source
    companion = copy.deepcopy(source)
    companion.update(minReps=6, maxReps=8, restAfterSupersetExerciseSeconds=90)
    current['workouts'][0]['exercises'].append(companion)
    second_day = copy.deepcopy(current['workouts'][0])
    second_day['name'] = 'Day B'
    second_day['exercises'] = [copy.deepcopy(source)]
    second_day['exercises'][0].update(superset=None, numWorkSets=1, restBetweenSetsSeconds=90,
                                      restAfterSupersetExerciseSeconds=0)
    unrelated_first = copy.deepcopy(source)
    unrelated_first.update(minReps=7, maxReps=9, superset='GROUP_B',
                           restAfterSupersetExerciseSeconds=30)
    unrelated_second = copy.deepcopy(unrelated_first)
    unrelated_second['restAfterSupersetExerciseSeconds'] = 60
    second_day['exercises'].extend([unrelated_first, unrelated_second])
    current['workouts'].append(second_day)

    task = {'requirementsId': stored['requirementsId'], 'baseDraftId': 'REVISION_24',
        'requirements': stored['requirements'],
        'findingsAssessment': {'groups': [{'findingIndexes': [0], 'disposition': 'repair',
            'repairDimensions': ['superset', 'session_timing'],
            'repairObjectives': [{'kind': 'redistribute_work',
                'exerciseRefs': ['EXERCISE_0', 'EXERCISE_2'], 'minimumSessions': 2}]}]}}
    arguments = {'requirementsId': stored['requirementsId'], 'baseDraftId': task['baseDraftId'],
        'addressedFindingIndexes': [0], 'edits': {
            'redistributionTargets': {'REDISTRIBUTION_0': ['WORKOUT_0', 'WORKOUT_1']},
            'exerciseUpdates': [{'exerciseRef': 'EXERCISE_3', 'setFields': {'superset': None}}]}}

    compiled, operation_refs, reference_map = compile_coordinated_repair(
        arguments, task, current, return_reference_map=True)
    repaired = apply_json_patch(current, compiled['patch'])
    assert all(item['superset'] is None for item in repaired['workouts'][0]['exercises'])
    assert repaired['workouts'][0]['exercises'][0]['restBetweenSetsSeconds'] == 90
    assert repaired['workouts'][0]['exercises'][1]['restBetweenSetsSeconds'] == 90
    assert all(item['superset'] is None for item in repaired['workouts'][1]['exercises'])
    assert [item['restBetweenSetsSeconds'] for item in repaired['workouts'][1]['exercises'][1:]] == [60, 60]
    assert reference_map['redistributionManifest'][0]['minimumSessions'] == 2
    updates = reference_map['composedEdits']['exerciseUpdates']
    assert len({update['exerciseRef'] for update in updates}) == len(updates)
    referenced = {reference for refs in operation_refs for reference in refs}
    assert {'EXERCISE_0', 'EXERCISE_1'} <= referenced


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


def test_rejected_typed_repair_is_evidence_not_implicitly_applied():
    from workout_generator_pkg.json_patching import apply_json_patch
    from workout_generator_pkg.planning_tools import compile_coordinated_repair, coordinated_repair_tool
    _, _, _, current = planning_case()
    previous = {'workoutUpdates': [{'workoutRef': 'WORKOUT_0', 'setFields': {'description': 'Rejected focus'}}],
                'exerciseUpdates': [{'exerciseRef': 'EXERCISE_0', 'setFields': {'setupSeconds': 45}}]}
    task = {'requirementsId': current['requirementsId'], 'baseDraftId': 'REVISION_8',
        'rejectedCoordinatedRepair': {'requirementsId': current['requirementsId'], 'baseDraftId': 'REVISION_8',
            'currentDraftId': 'REVISION_8', 'submittedEdits': previous}}
    assert 'replaceRejectedRepair' not in coordinated_repair_tool({**task, 'currentDraft': current})['function']['parameters']['properties']
    correction = {'requirementsId': current['requirementsId'], 'baseDraftId': 'REVISION_8',
        'edits': {'exerciseUpdates': [{'exerciseRef': 'EXERCISE_0', 'setFields': {'setupSeconds': 90}}]}}
    context = {}
    compiled, _ = compile_coordinated_repair(correction, task, current, proposal_context=context)
    updated = apply_json_patch(current, compiled['patch'])
    assert updated['workouts'][0].get('description') == current['workouts'][0].get('description')
    assert updated['workouts'][0]['exercises'][0]['setupSeconds'] == 90
    assert context['submittedEdits'] == correction['edits']
    assert context['replacedSubmittedEdits'] == previous == task['rejectedCoordinatedRepair']['submittedEdits']


def test_rejected_removal_cannot_poison_a_later_valid_update():
    from workout_generator_pkg.json_patching import apply_json_patch
    from workout_generator_pkg.planning_tools import compile_coordinated_repair
    _, _, _, current = planning_case()
    task = {'requirementsId': current['requirementsId'], 'baseDraftId': 'REVISION_9',
        'rejectedCoordinatedRepair': {'requirementsId': current['requirementsId'], 'baseDraftId': 'REVISION_9',
            'currentDraftId': 'REVISION_9', 'submittedEdits': {'exerciseRemovals': ['EXERCISE_0']}}}
    correction = {'requirementsId': current['requirementsId'], 'baseDraftId': 'REVISION_9',
        'edits': {'exerciseUpdates': [{'exerciseRef': 'EXERCISE_0', 'setFields': {'setupSeconds': 90}}]}}
    compiled, _ = compile_coordinated_repair(correction, task, current)
    assert len(apply_json_patch(current, compiled['patch'])['workouts'][0]['exercises']) == 1
    assert not any(op['op'] == 'remove' for op in compiled['patch'])


def test_malformed_retained_proposal_does_not_block_an_independent_valid_edit():
    from workout_generator_pkg.planning_tools import compile_coordinated_repair
    _, _, _, current = planning_case()
    previous = {'exerciseUpdates': [{'exerciseRef': 'EXERCISE_0', 'setFields': {'staleUnknownField': 'evidence'}}]}
    task = {'requirementsId': current['requirementsId'], 'baseDraftId': 'REVISION_10',
        'rejectedCoordinatedRepair': {'requirementsId': current['requirementsId'], 'baseDraftId': 'REVISION_10',
            'currentDraftId': 'REVISION_10', 'submittedEdits': previous}}
    correction = {'requirementsId': current['requirementsId'], 'baseDraftId': 'REVISION_10',
        'edits': {'exerciseUpdates': [{'exerciseRef': 'EXERCISE_0', 'setFields': {'setupSeconds': 90}}]}}
    compiled, _ = compile_coordinated_repair(correction, task, current)
    assert compiled['patch'] == [{'op': 'replace', 'path': '/workouts/0/exercises/0/setupSeconds', 'value': 90}]
    assert task['rejectedCoordinatedRepair']['submittedEdits'] == previous


def test_invalid_correction_leaves_evidence_and_next_valid_edit_uses_saved_candidate():
    from workout_generator_pkg.json_patching import apply_json_patch
    from workout_generator_pkg.planning_tools import compile_coordinated_repair
    _, _, _, current = planning_case()
    previous = {'workoutUpdates': [{'workoutRef': 'WORKOUT_0', 'setFields': {'description': 'Rejected focus'}}]}
    task = {'requirementsId': current['requirementsId'], 'baseDraftId': 'REVISION_14',
        'rejectedCoordinatedRepair': {'requirementsId': current['requirementsId'], 'baseDraftId': 'REVISION_14',
            'currentDraftId': 'REVISION_14', 'submittedEdits': previous}}
    malformed = {'requirementsId': current['requirementsId'], 'baseDraftId': 'REVISION_14',
        'edits': {'exerciseUpdates': [{'exerciseRef': 'EXERCISE_0', 'setFields': {'unknownTypedField': 'bad'}}]}}
    with pytest.raises(ValidationError):
        compile_coordinated_repair(malformed, task, current)
    valid = copy.deepcopy(malformed)
    valid['edits']['exerciseUpdates'][0]['setFields'] = {'setupSeconds': 90}
    compiled, _ = compile_coordinated_repair(valid, task, current)
    updated = apply_json_patch(current, compiled['patch'])
    assert updated['workouts'][0].get('description') == current['workouts'][0].get('description')
    assert task['rejectedCoordinatedRepair']['submittedEdits'] == previous


def test_scope_rejection_records_only_the_submitted_proposal():
    from workout_generator_pkg.interactive_shell import _admit_repair_scope
    from workout_generator_pkg.planning_tools import PlanningInputError
    _, _, _, current = planning_case()
    task = {'requirementsId': current['requirementsId'], 'baseDraftId': 'REVISION_11',
        'rejectedCoordinatedRepair': {'requirementsId': current['requirementsId'], 'baseDraftId': 'REVISION_11',
            'currentDraftId': 'REVISION_11', 'submittedEdits': {'exerciseRemovals': ['EXERCISE_0']}}}
    arguments = {'requirementsId': current['requirementsId'], 'baseDraftId': 'REVISION_11',
        'edits': {'exerciseUpdates': [{'exerciseRef': 'EXERCISE_0', 'setFields': {'setupSeconds': 90}}]}}
    def reject(*args):
        raise PlanningInputError('scope_rejected', 'Keep the original draft.', '/edits', 'Correct the scope.')
    context = {}
    with pytest.raises(PlanningInputError, match='Keep the original draft'):
        _admit_repair_scope(arguments, task, current, [], 0, 3, scope_validator=reject, submission_context=context)
    assert context['submittedEdits'] == arguments['edits'] and context['proposalCompiled']


def test_rejected_structural_addition_and_order_are_not_inherited():
    from workout_generator_pkg.json_patching import apply_json_patch
    from workout_generator_pkg.planning_tools import compile_coordinated_repair
    _, _, _, current = planning_case()
    previous = {'exerciseAdditions': [{'temporaryId': 'NEW_EXERCISE_rejected', 'workoutRef': 'WORKOUT_0',
        'exercise': copy.deepcopy(current['workouts'][0]['exercises'][0])}],
        'exerciseOrders': [{'workoutRef': 'WORKOUT_0', 'exerciseRefs': ['NEW_EXERCISE_rejected', 'EXERCISE_0']}]}
    task = {'requirementsId': current['requirementsId'], 'baseDraftId': 'REVISION_12',
        'rejectedCoordinatedRepair': {'requirementsId': current['requirementsId'], 'baseDraftId': 'REVISION_12',
            'currentDraftId': 'REVISION_12', 'submittedEdits': previous}}
    correction = {'requirementsId': current['requirementsId'], 'baseDraftId': 'REVISION_12',
        'edits': {'exerciseUpdates': [{'exerciseRef': 'EXERCISE_0', 'setFields': {'setupSeconds': 90}}]}}
    compiled, _ = compile_coordinated_repair(correction, task, current)
    assert len(apply_json_patch(current, compiled['patch'])['workouts'][0]['exercises']) == 1
    assert not any(op['op'] in ('add', 'move') for op in compiled['patch'])
    assert task['rejectedCoordinatedRepair']['submittedEdits'] == previous


def test_independent_repair_still_must_cover_every_assessed_group():
    from workout_generator_pkg.planning_tools import PlanningInputError, compile_coordinated_repair, validate_repair_scope
    _, _, _, current = planning_case()
    task = {'requirementsId': current['requirementsId'], 'baseDraftId': 'REVISION_13',
        'findingsAssessment': {'groups': [
            {'findingIndexes': [0], 'disposition': 'repair', 'repairDimensions': ['session_timing']},
            {'findingIndexes': [1], 'disposition': 'repair', 'repairDimensions': ['coverage']}]},
        'reviewFindings': [{'draftPath': '/workouts/0/exercises/0/setupSeconds'},
                           {'draftPath': '/workouts/0/exercises/0/satisfiesCoverage'}]}
    arguments = {'requirementsId': current['requirementsId'], 'baseDraftId': 'REVISION_13',
        'addressedFindingIndexes': [0, 1], 'edits': {'exerciseUpdates': [
            {'exerciseRef': 'EXERCISE_0', 'setFields': {'setupSeconds': 90}}]}}
    compiled, refs = compile_coordinated_repair(arguments, task, current)
    with pytest.raises(PlanningInputError, match='matching structured field'):
        validate_repair_scope(compiled, {**task, '_compiledRepairOperationRefs': refs}, current)


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


def test_metadata_repair_does_not_replay_rejected_candidate_operations():
    from workout_generator_pkg.json_patching import apply_json_patch
    from workout_generator_pkg.interactive_shell import _admit_repair_scope
    _, _, _, saved = planning_case()
    saved['workouts'][0]['description'] = 'Original focus'
    path = '/workouts/0/description'
    rejected = {'requirementsId': saved['requirementsId'], 'baseDraftId': 'REVISION_7', 'patch': [
        {'op': 'replace', 'path': '/workouts/0/exercises/0/numWorkSets', 'value': 99},
        {'op': 'replace', 'path': path, 'value': 'Rejected long focus'}]}
    task = {'requirementsId': saved['requirementsId'], 'baseDraftId': 'REVISION_7',
        'rejectedSubmission': rejected, 'permittedPatchPaths': [path],
        'metadataFields': {path: {'maximumCharacters': 25}}}
    arguments = {'requirementsId': saved['requirementsId'], 'baseDraftId': 'REVISION_7', 'edits': {
        'workoutUpdates': [{'workoutRef': 'WORKOUT_0', 'setFields': {'description': 'Short focus'}}]}}
    admitted = _admit_repair_scope(arguments, task, saved, [], 0, 3)
    final = apply_json_patch(saved, admitted['patch'])
    assert final['workouts'][0]['description'] == 'Short focus'
    assert final['workouts'][0]['exercises'] == saved['workouts'][0]['exercises']
    assert admitted['patch'] == [{'op': 'replace', 'path': path, 'value': 'Short focus'}]


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
    assert not _repair_requires_coordinated_qualification({'exerciseUpdates': [{'exerciseRef': 'EXERCISE_0',
        'removeOptionalFields': ['progressionMethod']}]}, draft)
    assert _repair_requires_coordinated_qualification({'exerciseUpdates': [{'exerciseRef': 'EXERCISE_0',
        'setFields': {'progressionPlan': {'kind': 'reps'}}}]}, draft)
    assert _repair_requires_coordinated_qualification({'exerciseUpdates': [{'exerciseRef': 'EXERCISE_0',
        'removeOptionalFields': ['satisfiesCoverage']}]}, draft)
    assert _repair_requires_coordinated_qualification({'exerciseUpdates': [{'exerciseRef': 'EXERCISE_0',
        'setFields': {'definition_id': 'LIBRARY_2'}}]}, draft)
    assert _repair_requires_coordinated_qualification({'exerciseAdditions': [{'temporaryId': 'NEW_EXERCISE_1'}]}, draft)
    assert _repair_requires_coordinated_qualification({'exerciseMoves': [{'exerciseRef': 'EXERCISE_0',
        'workoutRef': 'WORKOUT_1'}]}, draft)
    assert _repair_requires_coordinated_qualification({'exerciseOrders': [{'workoutRef': 'WORKOUT_0',
        'exerciseRefs': ['EXERCISE_0', 'EXERCISE_1']}]}, draft)
    assert _repair_requires_coordinated_qualification({'exerciseUpdates': [{'exerciseRef': 'EXERCISE_0',
        'setFields': {'superset': 'A'}}]}, draft)
    assert _repair_requires_coordinated_qualification({'exerciseUpdates': [{'exerciseRef': 'EXERCISE_0',
        'removeOptionalFields': ['superset']}]}, draft)


def test_structural_exercise_layout_edits_require_coordinated_qualification():
    from workout_generator_pkg.interactive_shell import _repair_requires_coordinated_qualification

    draft = {'workouts': [{'exercises': [{'definition_id': 'LIBRARY_1'}]}]}
    for edits in (
            {'exerciseAdditions': [{'temporaryId': 'NEW_EXERCISE_1'}]},
            {'exerciseRemovals': ['EXERCISE_0']},
            {'exerciseMoves': [{'exerciseRef': 'EXERCISE_0', 'workoutRef': 'WORKOUT_1'}]},
            {'exerciseOrders': [{'workoutRef': 'WORKOUT_0', 'exerciseRefs': ['EXERCISE_0']}]},
            {'exerciseUpdates': [{'exerciseRef': 'EXERCISE_0', 'setFields': {'superset': 'A'}}]},
            {'exerciseUpdates': [{'exerciseRef': 'EXERCISE_0', 'removeOptionalFields': ['superset']}]},):
        assert _repair_requires_coordinated_qualification(edits, draft)


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
    current['workouts'][0]['exercises'][1]['restBetweenSetsSeconds'] = 90
    task = {'baseDraftId': 'REVISION_1', 'findingsAssessment': {'groups': [
        {'findingIndexes': [0], 'disposition': 'repair', 'repairDimensions': ['session_timing']} ]},
        'reviewFindings': [{'draftPath': '/workouts/0/exercises/0/restBetweenSetsSeconds'}]}
    sibling_edit = {'requirementsId': current['requirementsId'], 'baseDraftId': 'REVISION_1',
        'addressedFindingIndexes': [0], 'patch': [{'op': 'replace',
            'path': '/workouts/0/exercises/1/restBetweenSetsSeconds', 'value': 120}]}

    with pytest.raises(PlanningInputError, match='matching structured field'):
        validate_repair_scope({**sibling_edit, 'patch': copy.deepcopy(sibling_edit['patch'])},
            {**task, '_compiledRepairOperationRefs': [['EXERCISE_1', 'WORKOUT_0']]}, current)

    target_edit = {**sibling_edit, 'patch': [{'op': 'replace',
        'path': '/workouts/0/exercises/0/restBetweenSetsSeconds', 'value': 180}]}
    validate_repair_scope(target_edit,
        {**task, '_compiledRepairOperationRefs': [['EXERCISE_0', 'WORKOUT_0']]}, current)

    mixed_task = {**task, 'findingsAssessment': {'groups': [
        {'findingIndexes': [0], 'disposition': 'repair', 'repairDimensions': ['session_timing', 'ordering']} ]}}
    mixed_patch = {'requirementsId': current['requirementsId'], 'baseDraftId': 'REVISION_1',
        'addressedFindingIndexes': [0], 'patch': [
            {'op': 'replace', 'path': '/workouts/0/exercises/1/restBetweenSetsSeconds', 'value': 120}]}
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


def test_assessment_reuse_depends_on_current_content_and_valid_shape_instead_of_version():
    review = {'inputHash': 'saved-review', 'findings': [{'severity': 'warning',
        'action': 'advisory', 'message': 'An optional review note.'}]}
    review['assessment'] = {'version': assessment.VERSION - 1,
        'inputHash': assessment.assessment_hash(review),
        'groups': [{'findingIndexes': [0], 'disposition': 'advisory', 'repairDimensions': [],
            'reason': 'The optional note does not require a repair.'}], 'repairPlan': ''}
    assert assessment.validate_assessment(review) is review['assessment']
    review['findings'][0]['message'] = 'Changed current finding.'
    with pytest.raises(ValueError, match='missing or stale'):
        assessment.validate_assessment(review)


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




def _current_repair_response(request, options, *, subject='EXERCISE_0', concern='NEW', dimension='session_labels'):
    from test_workout_generator_single_review import request_data, response_for
    data = request_data(request)
    current_ref = data['finalArtifact']['_reviewRef']
    finding = {'message': 'source_compliance', 'reason': 'source_conflict',
        'subjectRefs': [subject], 'basis': 'established_violation', 'disposition': 'repair',
        'repairDimensions': [dimension], 'repairObjectiveChoiceIds': [],
        'evidenceRefs': [data['sourceMessages']['SOURCE_0']['_reviewRef'], current_ref],
        'concernGroup': concern, 'decisionId': 'none', 'errorKind': 'none'}
    payload = response_for(data, options['output_schema'], [finding])
    if concern != 'NEW':
        payload['blockerResolutions'][concern] = {'reason': 'source_conflict', 'evidenceRefs': [current_ref]}
    return json.dumps(payload), None, None


def test_actionable_semantic_finding_prevents_preview_and_export(monkeypatch):
    from test_workout_generator_single_review import setup_case
    equipment, messages, raw, _ = setup_case()
    monkeypatch.setattr(plan_review, '_review_call',
        lambda client, request, **options: _current_repair_response(request, options))
    result = plan_review.review_draft(None, raw, messages, equipment)
    assert not result['passed'] and 'preview' not in result and 'planIndex' not in result
    assert result['errors'][0]['severity'] == 'blocking'
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
    from test_workout_generator_single_review import setup_case
    equipment, messages, raw, _ = setup_case()
    _, stored = plan_review._latest_result(messages, 'set_workout_requirements')
    monkeypatch.setattr(plan_review, '_review_call',
        lambda client, request, **options: _current_repair_response(request, options))
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


@pytest.mark.parametrize('rest_error', [False, True])
def test_qualified_candidate_with_only_solver_numeric_errors_reaches_joint_solver(monkeypatch, rest_error):
    from workout_generator_pkg import interactive_shell
    from workout_generator_pkg.joint_planning import solve_prescribed_week
    from workout_generator_pkg.planning_tools import set_workout_requirements

    equipment, requirements, _, draft = planning_case()
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 1, 'maximum': 6}
    requirements['auditTargets']['perSessionEffectiveSets']['chest'] = {'minimum': 1, 'maximum': 6}
    requirements['auditTargets']['maximumSessionSeconds'] = 600
    if rest_error:
        requirements['executionRules'] = [{'kind': 'rest', 'context': 'straightSets',
            'coverageKey': None, 'minimumSeconds': 90, 'maximumSeconds': 180}]
        draft['workouts'][0]['exercises'][0]['restBetweenSetsSeconds'] = 60
    stored = set_workout_requirements(requirements, [{'role': 'user', 'content':
        'Plan 1 to 6 chest sets, with a maximum session duration of 10 minutes.'}], equipment)
    draft['requirementsId'] = stored['requirementsId']
    messages = requirement_messages(stored)
    baseline = audit_workout_plan(draft, equipment, messages)
    assert not baseline['passed']
    assert {error['code'] for error in baseline['errors']} == ({'duration_exceeded', 'execution_rest'}
        if rest_error else {'duration_exceeded'})
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


@pytest.mark.parametrize('stale_qualification', [True, False])
@pytest.mark.parametrize('prior_gate', [True, False])
def test_saved_comparison_gate_refreshes_only_stale_recipe_qualification_before_solver(
        monkeypatch, stale_qualification, prior_gate):
    from workout_generator_pkg import allocation, interactive_shell
    from workout_generator_pkg.planning_tools import library_fingerprint, set_workout_requirements

    equipment, requirements, _, draft = planning_case()
    requirements['requiredCoverage'] = []
    stored = set_workout_requirements(requirements, [{'role': 'user', 'content': 'Keep the selected plan.'}], equipment)
    draft['requirementsId'] = stored['requirementsId']
    messages = requirement_messages(stored)
    _, fresh_qualification = allocation.qualify_workout_recipes(None, draft['workouts'], stored,
        equipment, messages)
    saved_qualification = copy.deepcopy(fresh_qualification)
    if stale_qualification:
        saved_qualification['inputHashes']['LIBRARY_0'] = 'old-source-context'
    prior = {'passed': False, 'requirementsId': stored['requirementsId'],
        'currentDraftId': 'REVISION_1', 'submittedDraft': copy.deepcopy(draft),
        'libraryFingerprint': library_fingerprint(equipment), 'historyFingerprint': None,
        'resolvedDecisions': {}, 'coordinatedCandidatePending': prior_gate,
        'recipeQualification': saved_qualification}
    if prior_gate:
        prior['jointPromotionGate'] = {'decision': 'incomparable', 'reason': 'baseline_not_eligible_for_comparison',
            'baselineAuditErrors': ['exercise_outside_shared_qualification_union'],
            'candidateAuditErrors': ['exercise_outside_shared_qualification_union']}
    else:
        prior.update(passed=True, audit={'errors': []}, review={'findings': []},
            coordinatedJointPlanning={'feasible': True, 'status': 'optimal'})
    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': 'prior-gate', 'function': {
            'name': 'audit_workout_plan', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'prior-gate', 'content': json.dumps(prior)},
    ])

    qualification_calls = []
    def refresh(_client, candidate, *_args, **_kwargs):
        qualification_calls.append(True)
        return candidate, copy.deepcopy(fresh_qualification)

    monkeypatch.setattr(allocation, 'qualify_coordinated_candidate', refresh)
    checkpoints = []
    audit_result = {'passed': True, 'errors': [], 'requirementsId': stored['requirementsId'],
        'currentDraftId': 'REVISION_2', 'submittedDraft': copy.deepcopy(draft),
        'libraryFingerprint': library_fingerprint(equipment), 'historyFingerprint': None,
        'resolvedDecisions': {}, 'audit': {'errors': []}, 'preview': 'candidate'}
    monkeypatch.setattr(interactive_shell, 'audit_workout_plan', lambda *_args, **_kwargs:
        copy.deepcopy(audit_result))

    def solve(*_args, **_kwargs):
        assert checkpoints and checkpoints[-1]['recipeQualification'] == fresh_qualification
        return ({'feasible': True, 'status': 'optimal', 'sessions': copy.deepcopy(draft['workouts']),
            'objectiveProgress': [], 'sourceWorkingSetBudget': None}, None, None, [])

    monkeypatch.setattr('workout_generator_pkg.repair_execution.solve_repair_candidate', solve)
    monkeypatch.setattr(allocation, 'reusable_joint_receipt', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(interactive_shell, 'review_draft', lambda _client, result, *_args, **_kwargs:
        {**result, 'passed': True, 'errors': [], 'review': {'findings': []}})

    result = interactive_shell.handle_function_call(None, messages, 'audit_workout_plan', draft, equipment,
        checkpoint=checkpoints.append)
    payload = json.loads(result['result'])

    assert len(qualification_calls) == int(stale_qualification)
    if stale_qualification:
        assert checkpoints and checkpoints[-1]['recipeQualification'] == fresh_qualification
        assert payload['recipeQualification'] == fresh_qualification


def test_newly_selected_exercise_refreshes_nonpending_recipe_lineage_before_auto_allocation(monkeypatch):
    from workout_generator_pkg import allocation, interactive_shell, recipe_contracts
    from workout_generator_pkg.planning_tools import library_fingerprint, set_workout_requirements

    equipment, requirements, _, source = planning_case()
    second = copy.deepcopy(equipment['exerciseDefinitions'][0])
    second.update(id='press-variant', name='Second Push-Up Variant')
    equipment['exerciseDefinitions'].append(second)
    requirements['requiredCoverage'] = [{'key': 'push', 'description': 'A pushing movement',
        'scope': 'eachSession'}]
    source['requirementsId'] = None
    stored = set_workout_requirements(requirements, [{'role': 'user',
        'content': 'Use a pushing movement in each session.'}], equipment)
    source['requirementsId'] = stored['requirementsId']
    messages = requirement_messages(stored)
    monkeypatch.setattr(recipe_contracts, 'chat_call', lambda _client, request, **_kwargs: (
        json.dumps({'contracts': [{'definition_id': item['definition_id'], 'satisfiesCoverage': []}
            for item in json.loads(request[-1]['content'])['recipes']]}), None, None))

    original_exercises, old_qualification = allocation.qualify_workout_recipes(
        None, source['workouts'], stored, equipment, messages)
    assert original_exercises[0]['exercises'][0]['satisfiesCoverage'] == []
    prior = {'passed': True, 'requirementsId': stored['requirementsId'],
        'currentDraftId': 'REVISION_1', 'draftId': 'REVISION_1',
        'submittedDraft': {**copy.deepcopy(source), 'workouts': original_exercises},
        'libraryFingerprint': library_fingerprint(equipment), 'historyFingerprint': None,
        'resolvedDecisions': {}, 'audit': {'errors': []}, 'review': {'findings': []},
        'coordinatedJointPlanning': {'feasible': True, 'status': 'optimal'},
        'recipeQualification': old_qualification}
    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': 'prior-audit', 'function': {
            'name': 'audit_workout_plan', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'prior-audit', 'content': json.dumps(prior)},
    ])

    candidate = copy.deepcopy(source)
    new_occurrence = copy.deepcopy(candidate['workouts'][0]['exercises'][0])
    new_occurrence.update(definition_id='LIBRARY_1', satisfiesCoverage=[])
    candidate['workouts'][0]['exercises'].append(new_occurrence)
    qualification = {'inputHashes': {'LIBRARY_0': 'current-0', 'LIBRARY_1': 'current-1'},
        'contracts': [{'definition_id': 'LIBRARY_0', 'satisfiesCoverage': ['push']},
                      {'definition_id': 'LIBRARY_1', 'satisfiesCoverage': ['push']}]}
    qualification_inputs = []
    def qualify(_client, exact_submission, *_args, **_kwargs):
        qualification_inputs.append(copy.deepcopy(exact_submission))
        qualified = copy.deepcopy(exact_submission)
        for day in qualified['workouts']:
            for item in day['exercises']:
                item['satisfiesCoverage'] = ['push']
        return qualified, copy.deepcopy(qualification)

    monkeypatch.setattr(allocation, 'qualify_coordinated_candidate', qualify)
    audit_submissions = []
    def audit(submission, *_args, **_kwargs):
        audit_submissions.append(copy.deepcopy(submission))
        return {'passed': True, 'errors': [], 'requirementsId': stored['requirementsId'],
            'currentDraftId': f'REVISION_{len(audit_submissions) + 1}',
            'draftId': f'REVISION_{len(audit_submissions) + 1}',
            'submittedDraft': copy.deepcopy(submission),
            'libraryFingerprint': library_fingerprint(equipment), 'historyFingerprint': None,
            'resolvedDecisions': {}, 'audit': {'errors': []}, 'preview': 'audited selection'}

    monkeypatch.setattr(interactive_shell, 'audit_workout_plan', audit)
    auto_allocation_inputs = []
    def auto_allocate(result, *_args, **_kwargs):
        auto_allocation_inputs.append(copy.deepcopy(result))
        return result

    monkeypatch.setattr(interactive_shell, 'auto_allocate_workout', auto_allocate)
    monkeypatch.setattr(interactive_shell, 'review_draft', lambda _client, result, *_args, **_kwargs:
        {**result, 'passed': True, 'review': {'findings': []}})
    checkpoints = []
    response = interactive_shell.handle_function_call(None, messages, 'audit_workout_plan', candidate,
        provided_equipment=equipment, checkpoint=checkpoints.append)
    payload = json.loads(response['result'])

    assert len(qualification_inputs) == 1
    assert [item['definition_id'] for item in qualification_inputs[0]['workouts'][0]['exercises']] == [
        'LIBRARY_0', 'LIBRARY_1']
    assert len(audit_submissions) == 2
    assert [item['satisfiesCoverage'] for item in audit_submissions[-1]['workouts'][0]['exercises']] == [
        ['push'], ['push']]
    assert checkpoints[-1]['recipeQualification'] == qualification
    assert auto_allocation_inputs[0]['recipeQualification'] == qualification
    assert payload['recipeQualification'] == qualification


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


@pytest.mark.parametrize('source_plan_index_retained', [True, False])
def test_pure_execution_order_repair_skips_joint_reoptimization_and_preserves_dose(
        monkeypatch, source_plan_index_retained):
    from workout_generator_pkg import interactive_shell
    from workout_generator_pkg.planning_tools import set_workout_requirements

    equipment, requirements, _, draft = planning_case()
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 5, 'maximum': 6}
    requirements['auditTargets']['perSessionEffectiveSets']['chest'] = {'minimum': 5, 'maximum': 6}
    isolation = copy.deepcopy(equipment['exerciseDefinitions'][0])
    isolation.update(id='zz_isolation', name='Cable Fly', exerciseCategory='ISOLATION')
    equipment['exerciseDefinitions'][0]['exerciseCategory'] = 'MODERATE_COMPOUND'
    equipment['exerciseDefinitions'].append(isolation)
    stored = set_workout_requirements(requirements,
        [{'role': 'user', 'content': 'Plan 5-6 chest sets.'}], equipment)
    draft['requirementsId'] = stored['requirementsId']
    moderate, isolation_item = draft['workouts'][0]['exercises'][0], copy.deepcopy(draft['workouts'][0]['exercises'][0])
    moderate.update(numWorkSets=3, definition_id='LIBRARY_0')
    isolation_item.update(numWorkSets=2, definition_id='LIBRARY_1')
    draft['workouts'][0]['exercises'] = [isolation_item, moderate]
    messages = requirement_messages(stored)
    prior = audit_workout_plan(draft, equipment, messages)
    assert not prior['passed'] and {error['code'] for error in prior['errors']} == {'execution_order'}
    prior.update(requirementsId=stored['requirementsId'], historyFingerprint=None,
        coordinatedJointPlanning={'feasible': True, 'status': 'optimal', 'preserveSourceSelection': True})
    if not source_plan_index_retained:
        prior.pop('planIndex', None)  # A failed semantic review drops this non-export artifact.
    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': 'prior-audit', 'function': {'name': 'audit_workout_plan'}}]},
        {'role': 'tool', 'tool_call_id': 'prior-audit', 'content': json.dumps(prior)},
    ])
    from workout_generator_pkg.programming_guidelines import canonical_execution_order_draft
    corrected = canonical_execution_order_draft(draft, stored['requirements'], equipment)
    monkeypatch.setattr('workout_generator_pkg.allocation.qualify_coordinated_candidate',
        lambda _client, args, *_a, **_k: (args, {'inputHash': 'qualified', 'contracts': []}))
    monkeypatch.setattr('workout_generator_pkg.joint_planning.solve_prescribed_week',
        lambda *_a, **_k: pytest.fail('A pure canonical order repair must preserve reviewed prescriptions.'))
    def passing_review(_client, candidate, *_args, **_kwargs):
        candidate['review'] = {'findings': []}
        return candidate
    monkeypatch.setattr(interactive_shell, 'review_draft', passing_review)

    result = json.loads(interactive_shell.handle_function_call(None, messages, 'audit_workout_plan',
        corrected, equipment, coordinated_repair=True)['result'])

    assert result['passed'], result.get('errors')
    assert [item['definition_id'] for item in result['submittedDraft']['workouts'][0]['exercises']] == [
        'LIBRARY_0', 'LIBRARY_1']
    assert [item['numWorkSets'] for item in result['submittedDraft']['workouts'][0]['exercises']] == [3, 2]


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
    from workout_generator_pkg.planning_tools import _latest_result, set_workout_requirements

    equipment, requirements, _, draft = planning_case()
    requirements['requiredCoverage'] = [{'key': 'horizontal_push',
        'description': 'Horizontal pushing work', 'scope': 'weekly'}]
    stored = set_workout_requirements(requirements, [{'role': 'user',
        'content': 'Include horizontal pushing work.'}], equipment)
    draft['requirementsId'] = stored['requirementsId']
    for exercise in draft['workouts'][0]['exercises']:
        exercise.pop('placementNotes', None)
    draft['workouts'][0]['exercises'][0]['satisfiesCoverage'] = ['horizontal_push']
    messages = requirement_messages(stored)
    _, original_receipt = _latest_result(messages, 'set_workout_requirements')
    prior = audit_workout_plan(draft, equipment, messages)
    review = {'inputHash': 'prior-review', 'findings': [{'severity': 'warning', 'message': 'Re-audit this role assignment.',
        'draftPath': '/workouts/0/exercises/0/satisfiesCoverage'}]}
    review['assessment'] = {'version': assessment.VERSION, 'inputHash': assessment.assessment_hash(review),
        'groups': [{'findingIndexes': [0], 'disposition': 'repair', 'repairDimensions': ['coverage'], 'reason': 'Supported source goals.'}],
        'repairPlan': 'Re-audit the role assignment.'}
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
            'satisfiesCoverage': ['horizontal_push'],
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
        assert candidate['workouts'][0]['exercises'][0]['satisfiesCoverage'] == ['horizontal_push']
    else:
        assert qualification['inputHash'] == 'fresh-contract'
        assert calls == [(None, refreshed['requirementsId'])]
        assert candidate['workouts'][0]['exercises'][0]['satisfiesCoverage'] == ['horizontal_push']


def test_coordinated_selection_qualification_normalizes_roles_for_every_occurrence(monkeypatch):
    from workout_generator_pkg.allocation import qualify_coordinated_candidate
    from workout_generator_pkg.planning_tools import set_workout_requirements

    equipment, requirements, _, draft = planning_case()
    requirements['requiredCoverage'] = [
        {'key': 'original', 'description': 'Original role', 'scope': 'weekly'},
        {'key': 'alternate', 'description': 'Alternate role', 'scope': 'weekly'}]
    stored = set_workout_requirements(requirements, [{'role': 'user', 'content':
        'Include movements supporting the original role and alternate role.'}], equipment)
    draft['requirementsId'] = stored['requirementsId']
    for exercise in draft['workouts'][0]['exercises']:
        exercise.pop('placementNotes', None)
    draft['workouts'][0]['exercises'][0]['satisfiesCoverage'] = ['original']
    second_definition = copy.deepcopy(equipment['exerciseDefinitions'][0])
    second_definition['id'] = 'LIBRARY_1'
    second_definition['name'] = 'Alternate press'
    equipment['exerciseDefinitions'].append(second_definition)
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
                {'definition_id': 'LIBRARY_0', 'satisfiesCoverage': ['original']},
                {'definition_id': 'LIBRARY_1', 'satisfiesCoverage': ['alternate']}]})

    candidate = copy.deepcopy(draft)
    candidate['workouts'][0]['exercises'][0].update(
        definition_id='LIBRARY_1', satisfiesCoverage=['original'])
    unchanged_duplicate = copy.deepcopy(candidate['workouts'][0]['exercises'][0])
    unchanged_duplicate.update(definition_id='LIBRARY_0', satisfiesCoverage=['alternate'])
    candidate['workouts'][0]['exercises'].append(unchanged_duplicate)
    added_occurrence = copy.deepcopy(candidate['workouts'][0]['exercises'][0])
    added_occurrence['satisfiesCoverage'] = ['original']
    candidate['workouts'][0]['exercises'].append(added_occurrence)
    context = {'workoutRefsByPosition': ['WORKOUT_0'],
        'exerciseRefsByWorkout': {'WORKOUT_0': ['EXERCISE_0', 'EXERCISE_1', 'NEW_EXERCISE_0']},
        'typedEdits': {'exerciseUpdates': [{'exerciseRef': 'EXERCISE_0', 'setFields': {
            'definition_id': 'LIBRARY_1', 'satisfiesCoverage': ['original']}}],
            'exerciseAdditions': [{'temporaryId': 'NEW_EXERCISE_0', 'exercise': added_occurrence}]}}

    result, qualification = qualify_coordinated_candidate(None,
        candidate, equipment, messages,
        coordinated_repair_context=context)

    selected, unchanged_duplicate, added_result = result['workouts'][0]['exercises']
    assert qualification['inputHash'] == 'qualified-all'
    assert selected['definition_id'] == 'LIBRARY_1'
    assert selected['numWorkSets'] == 5
    assert selected['minReps'] == 8 and selected['maxReps'] == 10
    assert selected['setupSeconds'] == 60
    assert selected['effortAcceptance']['acceptanceCriterion'] == 'Each repetition reaches the same controlled range of motion.'
    assert selected['satisfiesCoverage'] == ['alternate']
    assert unchanged_duplicate['definition_id'] == 'LIBRARY_0'
    assert unchanged_duplicate['numWorkSets'] == 5
    assert unchanged_duplicate['satisfiesCoverage'] == ['original']
    assert added_result['numWorkSets'] == selected['numWorkSets']
    assert added_result['minReps'] == selected['minReps']
    assert added_result['satisfiesCoverage'] == ['alternate']
    assert selected['satisfiesCoverage'] == ['alternate']


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
    from test_workout_generator_planning_tools import capability_requirement_messages
    equipment, requirements, _, draft = planning_case()
    equipment['exerciseDefinitions'].append({**copy.deepcopy(equipment['exerciseDefinitions'][0]), 'id': 'z_other', 'name': 'Other press'})
    requirements['auditTargets']['maximumSessionSeconds'] = 3000
    stored = set_workout_requirements(requirements, [{'role': 'user', 'content': 'Use the available presses.'}], equipment)
    draft['requirementsId'] = stored['requirementsId']
    first = draft['workouts'][0]['exercises'][0]
    first.update(numWorkSets=2, placementNotes='Use an unconfirmed band.')
    second = {**copy.deepcopy(first), 'definition_id': 'LIBRARY_1', 'numWorkSets': 3, 'placementNotes': 'No band.'}
    draft['workouts'][0]['exercises'].append(second)
    messages = capability_requirement_messages(stored, equipment)
    capability = json.loads(messages[-1]['content'])
    capability['decisions']['DECISION_1'] = {**copy.deepcopy(capability['decisions']['DECISION_0']),
        'confirmedCapabilityReference': 'LIBRARY_1'}
    messages[-1]['content'] = json.dumps(capability)
    def respond(client, request, **options):
        from test_workout_generator_single_review import request_data
        carried = bool(request_data(request).get('previousBlockingFindings'))
        return _current_repair_response(request, options,
            subject='EXERCISE_1' if carried else 'EXERCISE_0',
            concern='ISSUE_0' if carried else 'NEW', dimension='exercise_selection')
    monkeypatch.setattr(plan_review, '_review_call', respond)
    initial = plan_review.review_draft(None, audit_workout_plan(draft, equipment, messages), messages, equipment)
    messages.extend([{'role': 'assistant', 'tool_calls': [{'id': 'prior', 'function': {'name': 'audit_workout_plan'}}]},
        {'role': 'tool', 'tool_call_id': 'prior', 'content': json.dumps(initial)}])
    raw = audit_workout_plan({'requirementsId': stored['requirementsId'], 'baseDraftId': initial['currentDraftId'],
        'patch': [{'op': 'replace', 'path': '/workouts/0/exercises', 'value': [second, first]}]}, equipment, messages)
    result = plan_review.review_draft(None, raw, messages, equipment)
    assert not result['passed']
    assert 'review' in result, result.get('errors')
    assert result['review']['findings'][0]['subjectExerciseRefs'] == ['EXERCISE_1']
    assert result['errors'][0]['draftPath'] == '/workouts/0/exercises/1'


def _bind_disputed_assessment(review, context):
    context.setdefault('requirements', {})
    for finding in review['findings']:
        finding.setdefault('severity', 'warning')
    for group in review['assessment']['groups']:
        group.update(errorKind='unsupported_requirement', evidencePaths=['/requirements', '/draft'])
        group['evidenceHash'] = assessment._error_evidence(context, group)
    review['assessment'].update(version=assessment.VERSION, inputHash=assessment.assessment_hash(review))


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

@pytest.mark.parametrize('data_path', ['/programmingSummary/exposures/LIBRARY_0', '/inventedSummary'])
def test_withdrawal_recognizes_computed_programming_summary_but_requires_authority(data_path):
    context = {'requirements': {'goal': 'Spread work.'},
        'programmingSummary': {'exposures': {'LIBRARY_0': {'weeklyWorkingSets': 3}}}}
    group = {'errorKind': 'contradicted_by_current_data', 'reason': 'The computed exposure contradicts the complaint.',
        'evidencePaths': ['/requirements/goal', data_path]}
    if data_path.startswith('/programmingSummary/'):
        assert assessment._error_evidence(context, group)
        group['evidencePaths'] = [data_path]
    with pytest.raises(ValueError):
        assessment._error_evidence(context, group)

@pytest.mark.parametrize('mismatch', [None, 'draft', 'requirements', 'pending', 'assessment'])
def test_new_repair_transaction_requires_complete_review_of_exact_candidate(mismatch):
    from workout_generator_pkg.review_assessment import reviewed_candidate_matches, assessment_hash, VERSION
    from workout_generator_pkg.plan_review import REVIEW_VERSION
    draft = {'requirementsId': 'REQ', 'workouts': []}
    review = {'version': REVIEW_VERSION, 'inputHash': 'review-input', 'findings': []}
    review['assessment'] = {'version': VERSION, 'inputHash': assessment_hash(review), 'groups': [], 'repairPlan': ''}
    owner = {'requirementsId': 'REQ', 'currentDraftId': 'REVISION_1', 'submittedDraft': copy.deepcopy(draft), 'review': review}
    if mismatch == 'draft': owner['submittedDraft']['name'] = 'Another candidate'
    if mismatch == 'requirements': owner['requirementsId'] = 'OTHER'
    if mismatch == 'pending': owner['reviewPending'] = True
    if mismatch == 'assessment': review['assessment']['inputHash'] = 'stale'
    assert reviewed_candidate_matches(owner, draft, 'REQ') is (mismatch is None)


def test_correcting_rejected_container_does_not_retain_misplaced_edit_metadata():
    from workout_generator_pkg.planning_tools import compile_coordinated_repair
    from workout_generator_pkg.json_patching import apply_json_patch
    _, _, _, current = planning_case()
    current['workouts'][0]['exercises'][0].pop('placementNotes', None)
    previous = {'exerciseUpdates': [{'exerciseRef': 'EXERCISE_0', 'setFields': {
        'numWorkSets': 4, 'removeOptionalFields': ['targetSetPrescriptions']}}]}
    task = {'requirementsId': current['requirementsId'], 'baseDraftId': 'REVISION_8',
        'rejectedCoordinatedRepair': {'requirementsId': current['requirementsId'],
            'baseDraftId': 'REVISION_8', 'submittedEdits': previous}}
    correction = {'requirementsId': current['requirementsId'], 'baseDraftId': 'REVISION_8',
        'edits': {'exerciseUpdates': [{'exerciseRef': 'EXERCISE_0', 'setFields': {'setupSeconds': 90}}]}}
    compiled, _ = compile_coordinated_repair(correction, task, current)
    exercise = apply_json_patch(current, compiled['patch'])['workouts'][0]['exercises'][0]
    assert exercise['numWorkSets'] == current['workouts'][0]['exercises'][0]['numWorkSets']
    assert exercise['setupSeconds'] == 90
    assert 'removeOptionalFields' not in exercise
    unrelated = {**correction, 'edits': {'workoutUpdates': [
        {'workoutRef': 'WORKOUT_0', 'setFields': {'description': 'Still rejected'}}]}}
    independent, _ = compile_coordinated_repair(unrelated, task, current)
    assert apply_json_patch(current, independent['patch'])['workouts'][0]['exercises'] == current['workouts'][0]['exercises']
    assert 'removeOptionalFields' in previous['exerciseUpdates'][0]['setFields']


def test_nested_optional_removal_is_unambiguous_idempotent_and_not_a_repair_change():
    from workout_generator_pkg.planning_tools import compile_coordinated_repair, PlanningInputError
    _, _, _, current = planning_case()
    current['workouts'][0]['exercises'][0].pop('placementNotes', None)
    task = {'requirementsId': current['requirementsId'], 'baseDraftId': 'REVISION_8'}
    args = {**task, 'edits': {'exerciseUpdates': [{'exerciseRef': 'EXERCISE_0',
        'setFields': {'removeOptionalFields': ['targetSetPrescriptions']}}]}}
    before = copy.deepcopy(args)
    with pytest.raises(PlanningInputError) as noop:
        compile_coordinated_repair(args, task, current)
    assert noop.value.code == 'empty_coordinated_edits' and args == before
    revalidation = {**task, 'edits': {}}
    compiled, _ = compile_coordinated_repair(revalidation, task, current)
    assert compiled['patch'] == []
    with pytest.raises(PlanningInputError, match='stale'):
        compile_coordinated_repair({**revalidation, 'baseDraftId': 'OLD'}, task, current)
    args['edits']['exerciseUpdates'][0]['setFields']['numWorkSets'] = 4
    compiled, _ = compile_coordinated_repair(args, task, current)
    assert compiled['patch'] == [{'op': 'replace', 'path': '/workouts/0/exercises/0/numWorkSets', 'value': 4}]
    args['edits']['exerciseUpdates'][0]['removeOptionalFields'] = ['workSetTemplate']
    with pytest.raises(PlanningInputError) as error:
        compile_coordinated_repair(args, task, current)
    assert error.value.code == 'conflicting_field_removals'
