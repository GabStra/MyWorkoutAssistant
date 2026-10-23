import copy
import json

import pytest

from workout_generator_pkg.repair_contract import (
    RepairContractError,
    build_repair_contract,
    carry_repair_contract,
    expand_redistributions,
    repair_contract_errors,
    validated_repair_contract,
)


def _exercise(sets=4, **changes):
    value = {
        'definition_id': 'press', 'name': 'Press', 'exerciseType': 'WEIGHT',
        'numWorkSets': sets, 'minReps': 8, 'maxReps': 12,
        'targetSetPrescriptions': [{'workSetIndex': index, 'reps': 8 + index, 'weight': 20 + index}
                                   for index in range(sets)],
        'satisfiesCoverage': ['upper_push_each_session'], 'superset': None,
    }
    value.update(changes)
    return value


def _draft():
    return {'workouts': [
        {'name': 'A', 'timesCompletedInAWeek': 1, 'exercises': [_exercise()]},
        {'name': 'B', 'timesCompletedInAWeek': 1, 'exercises': []},
        {'name': 'C', 'timesCompletedInAWeek': 1, 'exercises': []},
    ]}


@pytest.mark.parametrize('rejection', ['audit', 'infeasible', 'unproven'])
def test_rejected_redistribution_does_not_become_conservation_authority(rejection):
    authority = {'requirementsId': 'REQ-1', 'libraryFingerprint': 'LIB-1',
                 'historyFingerprint': 'HISTORY-1', 'resolvedDecisions': {}}
    valid_contract = {'requirementsId': 'REQ-1', 'redistributions': []}
    valid = {**authority, 'audit': {'errors': []}, 'repairContract': valid_contract}
    rejected = {**authority, 'audit': {'errors': []},
                'repairContract': {'requirementsId': 'REQ-1', 'redistributions': [{'weeklyWorkSets': 12}]}}
    if rejection == 'audit':
        rejected['audit']['errors'] = [{'code': 'volume_below_target'}]
    else:
        rejected['coordinatedJointPlanning'] = {'status': rejection, 'feasible': False}
    messages = [
        {'role': 'assistant', 'tool_calls': [{'id': 'valid', 'function': {'name': 'audit_workout_plan'}},
                                           {'id': 'rejected', 'function': {'name': 'audit_workout_plan'}}]},
        {'role': 'tool', 'tool_call_id': 'valid', 'content': json.dumps(valid)},
        {'role': 'tool', 'tool_call_id': 'rejected', 'content': json.dumps(rejected)}]
    assert validated_repair_contract(rejected, messages) == valid_contract
    assert validated_repair_contract(rejected, messages[2:]) is None
    changed_authority = {**rejected, 'historyFingerprint': 'OTHER-HISTORY'}
    assert validated_repair_contract(changed_authority, messages) is None


def test_audited_redistribution_stays_protected_after_a_rejected_proposal():
    source = _draft()
    _, manifest = expand_redistributions({'exerciseRedistributions': [{
        'exerciseRefs': ['EXERCISE_0'], 'workoutRefs': ['WORKOUT_0', 'WORKOUT_1']}]}, source)
    contract = build_repair_contract([], source, {}, manifest, requirements_id='REQ-1')
    valid = {'requirementsId': 'REQ-1', 'audit': {'errors': []}, 'repairContract': contract}
    rejected = {**valid, 'audit': {'errors': [{'code': 'volume_below_target'}]},
                'repairContract': {'requirementsId': 'REQ-1', 'redistributions': []}}
    messages = [{'role': 'assistant', 'tool_calls': [{'id': 'valid', 'function': {'name': 'audit_workout_plan'}}]},
                {'role': 'tool', 'tool_call_id': 'valid', 'content': json.dumps(valid)}]
    assert validated_repair_contract(rejected, messages) == contract


def test_redistribution_expands_to_even_code_owned_set_allocation_and_conserves_exact_targets():
    source = _draft()
    expanded, manifest = expand_redistributions({'exerciseRedistributions': [
        {'exerciseRefs': ['EXERCISE_0'], 'workoutRefs': ['WORKOUT_0', 'WORKOUT_1', 'WORKOUT_2']}
    ]}, source)

    assert [item['setFields']['numWorkSets'] for item in expanded['exerciseUpdates']] == [2]
    assert [item['exercise']['numWorkSets'] for item in expanded['exerciseAdditions']] == [1, 1]
    assert [item['temporaryId'] for item in expanded['exerciseAdditions']] == [
        'NEW_EXERCISE_REDIST_0_1', 'NEW_EXERCISE_REDIST_0_2']
    assert not expanded['exerciseRemovals'] and not expanded['exerciseMoves']
    assert manifest[0]['weeklyWorkSets'] == 4
    assert manifest[0]['minimumSessions'] == 3
    assert [len(item['exercise'].get('targetSetPrescriptions', [])) for item in expanded['exerciseAdditions']] == [1, 1]
    assert [[target['workSetIndex'] for target in item['exercise']['targetSetPrescriptions']]
            for item in expanded['exerciseAdditions']] == [[0], [0]]

    candidate = {'workouts': [
        {'exercises': [copy.deepcopy(source['workouts'][0]['exercises'][0])]},
        {'exercises': [copy.deepcopy(expanded['exerciseAdditions'][0]['exercise'])]},
        {'exercises': [copy.deepcopy(expanded['exerciseAdditions'][1]['exercise'])]},
    ]}
    candidate['workouts'][0]['exercises'][0].update(expanded['exerciseUpdates'][0]['setFields'])
    objective = {'kind': 'redistribute_work', 'exerciseRefs': ['EXERCISE_0'], 'minimumSessions': 3}
    contract = build_repair_contract([objective], source,
        {'sessionsPerWeek': 3, 'requiredCoverage': [{'key': 'upper_push_each_session', 'scope': 'eachSession'}]}, manifest)
    assert repair_contract_errors(contract, candidate) == []


def test_redistribution_round_trips_through_production_patch_compiler_with_reindexed_targets():
    from test_workout_generator_planning_tools import planning_case
    from workout_generator_pkg.json_patching import apply_json_patch
    from workout_generator_pkg.planning_tools import _validate_draft_schema, compile_coordinated_repair

    _, requirements, stored, source = planning_case()
    source['workouts'][0]['exercises'][0].pop('placementNotes', None)
    source['workouts'] = [copy.deepcopy(source['workouts'][0]) for _ in range(3)]
    source['workouts'][0]['exercises'][0]['numWorkSets'] = 4
    source['workouts'][0]['exercises'][0]['targetSetPrescriptions'] = [
        {'workSetIndex': index, 'reps': 8 + index, 'weight': 30 + index} for index in range(4)]
    for workout in source['workouts'][1:]:
        workout['exercises'] = []
    requirements['sessionsPerWeek'] = 3
    source['requirementsId'] = stored['requirementsId']
    task = {'requirementsId': stored['requirementsId'], 'baseDraftId': 'REVISION_1', 'currentDraft': source}
    arguments = {'requirementsId': stored['requirementsId'], 'baseDraftId': 'REVISION_1', 'edits': {
        'exerciseRedistributions': [{'exerciseRefs': ['EXERCISE_0'],
            'workoutRefs': ['WORKOUT_0', 'WORKOUT_1', 'WORKOUT_2']}],
    }}

    compiled, _ = compile_coordinated_repair(arguments, task, source)
    candidate = apply_json_patch(source, compiled['patch'])
    _validate_draft_schema(candidate)
    _, manifest = expand_redistributions(arguments['edits'], source)
    contract = build_repair_contract([], source, {'sessionsPerWeek': 3}, manifest)
    assert repair_contract_errors(contract, candidate) == []
    by_workout = [workout['exercises'][0]['targetSetPrescriptions'] for workout in candidate['workouts']]
    assert [[target['workSetIndex'] for target in targets] for targets in by_workout] == [[0, 1], [0], [0]]
    assert sorted((target['reps'], target['weight']) for targets in by_workout for target in targets) == [
        (8, 30), (9, 31), (10, 32), (11, 33)]


def test_redistribution_target_sessions_follow_declared_workout_order():
    from test_workout_generator_planning_tools import planning_case
    from workout_generator_pkg.planning_tools import compile_coordinated_repair

    _, _, stored, source = planning_case()
    source['workouts'][0]['exercises'][0].pop('placementNotes', None)
    source['workouts'] = [copy.deepcopy(source['workouts'][0]) for _ in range(3)]
    for workout in source['workouts'][1:]:
        workout['exercises'] = []
    edits = {'exerciseRedistributions': [{'exerciseRefs': ['EXERCISE_0'],
                'workoutRefs': ['WORKOUT_0', 'WORKOUT_2']}],
             'workoutOrder': ['WORKOUT_1', 'WORKOUT_2', 'WORKOUT_0']}
    expanded, manifest = expand_redistributions(edits, source)
    assert expanded['workoutOrder'] == edits['workoutOrder']
    contract = build_repair_contract([], source, {'sessionsPerWeek': 3}, manifest)
    assert contract['redistributions'][0]['targetWorkoutIndexes'] == [2, 1]

    task = {'requirementsId': stored['requirementsId'], 'baseDraftId': 'REVISION_2', 'currentDraft': source}
    compiled, _ = compile_coordinated_repair({'requirementsId': stored['requirementsId'],
        'baseDraftId': 'REVISION_2', 'edits': edits}, task, source)
    from workout_generator_pkg.json_patching import apply_json_patch
    assert repair_contract_errors(contract, apply_json_patch(source, compiled['patch'])) == []


def test_carried_redistribution_keeps_reordered_targets_and_refreshes_occurrence_refs():
    from test_workout_generator_planning_tools import planning_case
    from workout_generator_pkg.json_patching import apply_json_patch
    from workout_generator_pkg.planning_tools import compile_coordinated_repair

    _, _, stored, source = planning_case()
    source['workouts'][0]['exercises'][0].pop('placementNotes', None)
    source['workouts'] = [copy.deepcopy(source['workouts'][0]) for _ in range(3)]
    for workout in source['workouts'][1:]:
        workout['exercises'] = []
    source['requirementsId'] = stored['requirementsId']
    order = ['WORKOUT_1', 'WORKOUT_2', 'WORKOUT_0']
    edits = {'exerciseRedistributions': [{'exerciseRefs': ['EXERCISE_0'],
                'workoutRefs': ['WORKOUT_0', 'WORKOUT_2']}], 'workoutOrder': order}
    expanded, manifest = expand_redistributions(edits, source)
    task = {'requirementsId': stored['requirementsId'], 'baseDraftId': 'REVISION_3',
            'currentDraft': source}
    compiled, _ = compile_coordinated_repair({'requirementsId': stored['requirementsId'],
        'baseDraftId': 'REVISION_3', 'edits': edits}, task, source)
    candidate = apply_json_patch(source, compiled['patch'])
    contract = build_repair_contract([], source, {'sessionsPerWeek': 3}, manifest,
                                     requirements_id=stored['requirementsId'])

    first_snapshot = carry_repair_contract(None, contract, source, candidate,
        requirements_id=stored['requirementsId'], workout_order=order)
    later_candidate = copy.deepcopy(candidate)
    later_candidate['programGuidance'] = 'Preserve the approved plan.'
    second_snapshot = carry_repair_contract(first_snapshot, {}, candidate, later_candidate,
        requirements_id=stored['requirementsId'])

    expected_target_refs = ['WORKOUT_2', 'WORKOUT_1']
    assert first_snapshot['redistributions'][0]['targetWorkoutRefs'] == expected_target_refs
    assert second_snapshot['redistributions'][0]['targetWorkoutRefs'] == expected_target_refs
    assert second_snapshot['redistributions'][0]['targetWorkoutIndexes'] == [2, 1]
    assert all(position[0] in {1, 2}
               for position in second_snapshot['redistributions'][0]['sourcePositions'].values())
    assert repair_contract_errors(second_snapshot, later_candidate) == []


def test_repair_contract_rejects_lost_session_role_and_changed_weekly_count():
    source = _draft()
    _, manifest = expand_redistributions({'exerciseRedistributions': [
        {'exerciseRefs': ['EXERCISE_0'], 'workoutRefs': ['WORKOUT_0', 'WORKOUT_1', 'WORKOUT_2']}
    ]}, source)
    contract = build_repair_contract([
        {'kind': 'redistribute_work', 'exerciseRefs': ['EXERCISE_0'], 'minimumSessions': 3}], source,
        {'sessionsPerWeek': 3, 'requiredCoverage': [{'key': 'upper_push_each_session', 'scope': 'eachSession'}]}, manifest)
    candidate = {'workouts': [
        {'exercises': [_exercise(2)]}, {'exercises': []}, {'exercises': []}]}

    codes = {error['code'] for error in repair_contract_errors(contract, candidate)}
    assert codes == {'required_coverage_missing', 'redistribution_weekly_sets_changed',
                     'redistribution_sessions_not_met', 'redistribution_set_targets_changed'}


def test_redistribution_contract_rejects_matching_recipe_outside_targets():
    source = _draft()
    source['workouts'][0]['exercises'][0].pop('targetSetPrescriptions')
    _, manifest = expand_redistributions({'exerciseRedistributions': [{
        'exerciseRefs': ['EXERCISE_0'], 'workoutRefs': ['WORKOUT_0', 'WORKOUT_1']}]}, source)
    contract = build_repair_contract([], source, {}, manifest)
    candidate = {'workouts': [
        {'timesCompletedInAWeek': 1, 'exercises': [_exercise(1, targetSetPrescriptions=None)]},
        {'timesCompletedInAWeek': 1, 'exercises': [_exercise(2, targetSetPrescriptions=None)]},
        {'timesCompletedInAWeek': 1, 'exercises': [_exercise(1, targetSetPrescriptions=None)]},
    ]}

    errors = repair_contract_errors(contract, candidate)

    assert 'redistribution_recipe_outside_targets' in {error['code'] for error in errors}
    assert 'redistribution_weekly_sets_changed' not in {error['code'] for error in errors}


def test_redistribution_validator_conserves_weekly_sets_using_session_frequency():
    source = _draft()
    source['workouts'][0]['exercises'][0].pop('targetSetPrescriptions')
    _, manifest = expand_redistributions({'exerciseRedistributions': [{
        'exerciseRefs': ['EXERCISE_0'], 'workoutRefs': ['WORKOUT_0', 'WORKOUT_1']}]}, source)
    contract = build_repair_contract([], source, {}, manifest)
    candidate = {'workouts': [
        {'timesCompletedInAWeek': 2, 'exercises': [_exercise(1, targetSetPrescriptions=None)]},
        {'timesCompletedInAWeek': 1, 'exercises': [_exercise(2, targetSetPrescriptions=None)]},
        {'timesCompletedInAWeek': 1, 'exercises': []},
    ]}

    assert repair_contract_errors(contract, candidate) == []


def test_redistribution_does_not_split_two_sets_below_source_minimum_of_two():
    source = _draft()
    source_item = source['workouts'][0]['exercises'][0]
    source_item.pop('targetSetPrescriptions')
    source_item.update(numWorkSets=2, allocationBounds={'minimum': 2, 'maximum': 20})

    with pytest.raises(RepairContractError) as error:
        expand_redistributions({'exerciseRedistributions': [{
            'exerciseRefs': ['EXERCISE_0'], 'workoutRefs': ['WORKOUT_0', 'WORKOUT_1']}]}, source)

    assert error.value.code == 'redistribution_target_below_minimum'


def _spread(source, targets):
    edits, _ = expand_redistributions({'exerciseRedistributions': [
        {'exerciseRefs': ['EXERCISE_0'], 'workoutRefs': targets}
    ]}, source)
    return _apply_redistribution_edits(source, edits)


def _apply_redistribution_edits(source, edits):
    candidate = copy.deepcopy(source)
    exercise_by_ref = {}
    ref_by_position = {}
    next_ref = 0
    for workout_index, workout in enumerate(source['workouts']):
        for exercise_index, exercise in enumerate(workout['exercises']):
            ref = f'EXERCISE_{next_ref}'
            next_ref += 1
            exercise_by_ref[ref] = copy.deepcopy(exercise)
            ref_by_position[(workout_index, exercise_index)] = ref
    candidate['workouts'] = [{**copy.deepcopy(workout), 'exercises': []} for workout in source['workouts']]
    moved = {item['exerciseRef']: item['workoutRef'] for item in edits.get('exerciseMoves', [])}
    removed = set(edits.get('exerciseRemovals', []))
    for ref, exercise in exercise_by_ref.items():
        if ref in removed:
            continue
        target_ref = moved.get(ref)
        if target_ref is None:
            position = next(position for position, current_ref in ref_by_position.items() if current_ref == ref)
            target_index = position[0]
        else:
            target_index = int(target_ref.split('_')[1])
        candidate['workouts'][target_index]['exercises'].append(exercise)
    for update in edits.get('exerciseUpdates', []):
        exercise = exercise_by_ref[update['exerciseRef']]
        exercise.update(update.get('setFields', {}))
    for addition in edits.get('exerciseAdditions', []):
        target_index = int(addition['workoutRef'].split('_')[1])
        candidate['workouts'][target_index]['exercises'].append(copy.deepcopy(addition['exercise']))
    return candidate


def _contract(source, targets, requirements_id='REQ-1'):
    _, manifest = expand_redistributions({'exerciseRedistributions': [
        {'exerciseRefs': ['EXERCISE_0'], 'workoutRefs': targets}
    ]}, source)
    return build_repair_contract([], source, {'sessionsPerWeek': 3}, manifest,
                                 requirements_id=requirements_id)


def test_carried_contract_survives_guidance_repair_and_rebases_session_order():
    source = _draft()
    previous = _contract(source, ['WORKOUT_0', 'WORKOUT_1'])
    before = _spread(source, ['WORKOUT_0', 'WORKOUT_1'])
    after = copy.deepcopy(before)
    after['programGuidance'] = 'Keep the approved progression guidance.'
    order = ['WORKOUT_2', 'WORKOUT_1', 'WORKOUT_0']
    after['workouts'] = [copy.deepcopy(before['workouts'][2]),
                         copy.deepcopy(before['workouts'][1]),
                         copy.deepcopy(before['workouts'][0])]

    carried = carry_repair_contract(previous, {'requirementsId': 'REQ-1'}, before, after,
                                    requirements_id='REQ-1', workout_order=order)

    assert carried['redistributions'][0]['targetWorkoutIndexes'] == [2, 1]
    assert repair_contract_errors(carried, after) == []


def test_carried_contract_rejects_recipe_change_and_requirement_change():
    source = _draft()
    previous = _contract(source, ['WORKOUT_0', 'WORKOUT_1'])
    before = _spread(source, ['WORKOUT_0', 'WORKOUT_1'])
    changed = copy.deepcopy(before)
    changed['workouts'][0]['exercises'][0]['minReps'] = 6
    with pytest.raises(RepairContractError) as recipe_error:
        carry_repair_contract(previous, {}, before, changed, requirements_id='REQ-1')
    assert recipe_error.value.code == 'carried_repair_contract_changed'

    with pytest.raises(RepairContractError) as requirement_error:
        carry_repair_contract(previous, {}, before, before, requirements_id='REQ-2')
    assert requirement_error.value.code == 'repair_contract_requirements_changed'


def test_explicit_same_recipe_redistribution_replaces_carried_targets():
    source = _draft()
    previous = _contract(source, ['WORKOUT_0', 'WORKOUT_1'])
    before = _spread(source, ['WORKOUT_0', 'WORKOUT_1'])
    current_edits, manifest = expand_redistributions({'exerciseRedistributions': [
        {'exerciseRefs': ['EXERCISE_0', 'EXERCISE_1'],
         'workoutRefs': ['WORKOUT_1', 'WORKOUT_2']}
    ]}, before)
    current = build_repair_contract([], before, {'sessionsPerWeek': 3}, manifest,
                                    requirements_id='REQ-1')
    candidate = _apply_redistribution_edits(before, current_edits)

    merged = carry_repair_contract(previous, current, before, candidate, requirements_id='REQ-1')

    assert len(merged['redistributions']) == 1
    assert merged['redistributions'][0]['targetWorkoutIndexes'] == [1, 2]
    assert repair_contract_errors(merged, candidate) == []


def test_explicit_same_recipe_redistribution_cannot_weaken_validated_spread():
    source = _draft()
    previous = _contract(source, ['WORKOUT_0', 'WORKOUT_1', 'WORKOUT_2'])
    before = _spread(source, ['WORKOUT_0', 'WORKOUT_1', 'WORKOUT_2'])
    references = ['EXERCISE_0', 'EXERCISE_1', 'EXERCISE_2']
    edits, manifest = expand_redistributions({'exerciseRedistributions': [
        {'exerciseRefs': references, 'workoutRefs': ['WORKOUT_0', 'WORKOUT_1']}
    ]}, before)
    current = build_repair_contract([], before, {'sessionsPerWeek': 3}, manifest,
                                    requirements_id='REQ-1')
    candidate = _apply_redistribution_edits(before, edits)

    with pytest.raises(RepairContractError) as error:
        carry_repair_contract(previous, current, before, candidate, requirements_id='REQ-1')

    assert error.value.code == 'carried_repair_objective_weakened'


@pytest.mark.parametrize('mutate,code', [
    (lambda draft: draft['workouts'][1].update({'timesCompletedInAWeek': 2}), 'redistribution_frequency_unsupported'),
])
def test_redistribution_rejects_unsupported_source_state(mutate, code):
    source = _draft()
    mutate(source)
    with pytest.raises(RepairContractError) as error:
        expand_redistributions({'exerciseRedistributions': [
            {'exerciseRefs': ['EXERCISE_0'], 'workoutRefs': ['WORKOUT_0', 'WORKOUT_1']}
        ]}, source)
    assert error.value.code == code


def test_redistribution_requires_all_exact_recipe_occurrences_and_rejects_manual_conflict():
    source = _draft()
    source['workouts'][1]['exercises'] = [_exercise(2)]
    with pytest.raises(RepairContractError, match='every occurrence'):
        expand_redistributions({'exerciseRedistributions': [
            {'exerciseRefs': ['EXERCISE_0'], 'workoutRefs': ['WORKOUT_0', 'WORKOUT_2']}
        ]}, source)
    with pytest.raises(RepairContractError, match='manual update'):
        expand_redistributions({'exerciseRedistributions': [
            {'exerciseRefs': ['EXERCISE_0'], 'workoutRefs': ['WORKOUT_0', 'WORKOUT_1']}
        ], 'exerciseUpdates': [{'exerciseRef': 'EXERCISE_0', 'setFields': {'minReps': 6}}]}, _draft())


def test_redistribution_rejects_mixed_recipes():
    source = _draft()
    source['workouts'][1]['exercises'] = [_exercise(2, minReps=6)]
    with pytest.raises(RepairContractError, match='one exact exercise recipe'):
        expand_redistributions({'exerciseRedistributions': [
            {'exerciseRefs': ['EXERCISE_0', 'EXERCISE_1'], 'workoutRefs': ['WORKOUT_0', 'WORKOUT_1']}
        ]}, source)


def test_redistribution_reports_mixed_exact_target_modes_without_partial_expansion():
    source = _draft()
    uniform = _exercise(2)
    uniform.pop('targetSetPrescriptions')
    source['workouts'][1]['exercises'] = [uniform]
    before = copy.deepcopy(source)
    with pytest.raises(RepairContractError) as error:
        expand_redistributions({'exerciseRedistributions': [{
            'exerciseRefs': ['EXERCISE_0', 'EXERCISE_1'], 'workoutRefs': ['WORKOUT_0', 'WORKOUT_1']}]}, source)
    assert error.value.code == 'redistribution_mixed_target_modes_unsupported'
    assert source == before


def test_warmup_capability_normalization_does_not_change_conserved_working_recipe():
    from workout_generator_pkg.repair_contract import redistribution_recipe_signature
    exercise = _exercise()
    exercise['generateWarmUpSets'] = True
    canonical = copy.deepcopy(exercise)
    canonical['generateWarmUpSets'] = False
    assert redistribution_recipe_signature(exercise) == redistribution_recipe_signature(canonical)
    canonical['minReps'] = 6
    assert redistribution_recipe_signature(exercise) != redistribution_recipe_signature(canonical)


@pytest.mark.parametrize('fields, retained, outside', [({'setupSeconds': 45}, True, False),
    ({'minReps': 9}, False, False), ({'minReps': 9}, True, True)])
def test_completed_review_releases_only_explicitly_replaced_recipe(fields, retained, outside):
    from test_workout_generator_planning_tools import planning_case
    from workout_generator_pkg import interactive_shell as shell
    from workout_generator_pkg.planning_tools import compile_coordinated_repair
    from workout_generator_pkg.json_patching import apply_json_patch
    from workout_generator_pkg.review_assessment import assessment_hash, VERSION
    from workout_generator_pkg.plan_review import REVIEW_VERSION
    _, requirements, stored, source = planning_case()
    source['workouts'][0]['exercises'][0].pop('placementNotes', None)
    source['workouts'].append(copy.deepcopy(source['workouts'][0]))
    source['workouts'][1]['exercises'] = []
    task = {'requirementsId': stored['requirementsId'], 'baseDraftId': 'REVISION_1'}
    edits = {'exerciseRedistributions': [{'exerciseRefs': ['EXERCISE_0'],
        'workoutRefs': ['WORKOUT_0', 'WORKOUT_1']}]}
    compiled, _ = compile_coordinated_repair({**task, 'edits': edits}, task, source)
    current = apply_json_patch(source, compiled['patch'])
    _, manifest = expand_redistributions(edits, source)
    contract = build_repair_contract([], source, requirements, manifest, requirements_id=stored['requirementsId'])
    if outside:
        current['workouts'].append({**copy.deepcopy(current['workouts'][0]),
            'exercises': [copy.deepcopy(current['workouts'][0]['exercises'][0])]})
    review = {'version': REVIEW_VERSION, 'inputHash': 'review-input', 'findings': []}
    review['assessment'] = {'version': VERSION, 'inputHash': assessment_hash(review), 'groups': [], 'repairPlan': ''}
    owner = {**task, 'currentDraftId': 'REVISION_1', 'submittedDraft': current,
        'repairContract': contract, 'review': review}
    messages = [{'role': 'assistant', 'tool_calls': [{'id': 'saved', 'type': 'function',
        'function': {'name': 'audit_workout_plan', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'saved', 'content': __import__('json').dumps(owner)}]
    messages.extend([{'role': 'assistant', 'tool_calls': [{'id': 'rejected', 'type': 'function',
        'function': {'name': 'audit_workout_plan', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'rejected', 'content': __import__('json').dumps({
            'requirementsId': stored['requirementsId'], 'currentDraftId': 'REVISION_1',
            'passed': False, 'currentDraft': current, 'errors': [{'code': 'rejected_edit'}]})}])
    args = {**task, 'edits': {'exerciseUpdates': [{'exerciseRef': 'EXERCISE_2' if outside else 'EXERCISE_0', 'setFields': fields}]}}
    _, context = shell._admit_repair_scope(args, task, current, messages, len(messages), 2,
        scope_validator=lambda compiled, *_: compiled, return_context=True)
    assert bool(context['repairContract']['redistributions']) is retained
    if retained:
        assert context['repairContract']['redistributions'][0]['weeklyWorkSets'] == manifest[0]['weeklyWorkSets']


def test_carried_dose_rejects_matching_recipe_added_outside_declared_destinations():
    source = _draft()
    previous = _contract(source, ['WORKOUT_0', 'WORKOUT_1'])
    before = _spread(source, ['WORKOUT_0', 'WORKOUT_1'])
    after = copy.deepcopy(before)
    after['workouts'][2]['exercises'] = [_exercise(3)]
    with pytest.raises(RepairContractError, match='redistribution_recipe_outside_targets'):
        carry_repair_contract(previous, {}, before, after, requirements_id='REQ-1')
    carried = previous
    changed = copy.deepcopy(before)
    changed['workouts'][0]['exercises'][0]['numWorkSets'] += 1
    assert 'redistribution_weekly_sets_changed' in {e['code'] for e in repair_contract_errors(carried, changed)}
    changed = copy.deepcopy(after)
    changed['workouts'][0]['exercises'][0]['targetSetPrescriptions'][0]['weight'] += 1
    assert 'redistribution_set_targets_changed' in {e['code'] for e in repair_contract_errors(carried, changed)}


def test_repair_source_selection_policy_requires_a_validated_carried_domain():
    from workout_generator_pkg.repair_capabilities import preserve_source_selection_for_repair

    assert preserve_source_selection_for_repair() is True
    assert preserve_source_selection_for_repair({'preserveSourceSelection': True}) is True
    unpinned_receipt = {'preserveSourceSelection': False}
    assert preserve_source_selection_for_repair(unpinned_receipt) is True
    assert preserve_source_selection_for_repair(unpinned_receipt, valid_carried_domain=True) is False


def test_shared_repair_solver_carries_contract_and_keeps_selected_session_placement(monkeypatch):
    from workout_generator_pkg.repair_execution import solve_repair_candidate

    workouts = [{'name': 'Selected day', 'timesCompletedInAWeek': 1,
        'exercises': [{'definition_id': 'LIBRARY_1', 'numWorkSets': 2}]}]
    contract = {'requirementsId': 'REQ-1', 'redistributions': []}
    observed = {}

    def solve(sessions, requirements, equipment, restriction_policy, **kwargs):
        observed.update(kwargs)
        assert sessions == workouts
        return {'feasible': True, 'status': 'optimal', 'sessions': copy.deepcopy(sessions)}

    monkeypatch.setattr('workout_generator_pkg.joint_planning.solve_prescribed_week', solve)
    joint, carried, carry_error, contract_errors = solve_repair_candidate(
        workouts, {}, {}, {}, repair_contract=contract, requirements_id='REQ-1',
        allow_educated_load_guesses=True, training_history=None, messages=[],
        preserve_source_selection=True, redistribution_constraints=[])

    assert joint['sessions'] == workouts
    assert carried['requirementsId'] == contract['requirementsId']
    assert carry_error is None and contract_errors == []
    assert observed['preserve_source_selection'] is True


def test_shared_repair_solver_keeps_prior_coverage_invariants_when_current_contract_is_empty(monkeypatch):
    from workout_generator_pkg.repair_execution import solve_repair_candidate

    workouts = [{'name': 'Selected day', 'timesCompletedInAWeek': 1,
        'exercises': [{'definition_id': 'LIBRARY_1', 'numWorkSets': 2,
                      'satisfiesCoverage': ['hip_extension']}]}]
    contract = {'requirementsId': 'REQ-1', 'sessionsPerWeek': 1,
        'requiredCoverage': [{'key': 'hip_extension', 'scope': 'weekly'}], 'redistributions': []}

    def solve(sessions, requirements, equipment, restriction_policy, **kwargs):
        candidate = copy.deepcopy(sessions)
        candidate[0]['exercises'][0]['satisfiesCoverage'] = []
        return {'feasible': True, 'status': 'optimal', 'sessions': candidate}

    monkeypatch.setattr('workout_generator_pkg.joint_planning.solve_prescribed_week', solve)
    joint, carried, carry_error, contract_errors = solve_repair_candidate(
        workouts, {}, {}, {}, repair_contract=contract, requirements_id='REQ-1',
        allow_educated_load_guesses=True, training_history=None, messages=[],
        preserve_source_selection=True, redistribution_constraints=[])

    assert joint['feasible']
    assert carried['requiredCoverage'] == contract['requiredCoverage']
    assert carried['sessionsPerWeek'] == 1
    assert carry_error is not None and carry_error.code == 'carried_repair_contract_changed'
    assert 'required_coverage_missing' in str(carry_error)
    assert contract_errors == []


@pytest.mark.parametrize('current', [
    {'sessionsPerWeek': 2},
    {'requiredCoverage': []},
])
def test_carried_contract_rejects_explicitly_changed_approved_invariants(current):
    source = _draft()
    previous = {'requirementsId': 'REQ-1', 'sessionsPerWeek': 3,
        'requiredCoverage': [{'key': 'hip_extension', 'scope': 'weekly'}], 'redistributions': []}

    with pytest.raises(RepairContractError) as error:
        carry_repair_contract(previous, current, source, source, requirements_id='REQ-1')

    assert error.value.code == 'carried_repair_invariants_changed'


@pytest.mark.parametrize('current', [None, {}])
def test_carried_contract_inherits_invariants_omitted_by_current_contract(current):
    source = _draft()
    source['workouts'][0]['exercises'][0]['satisfiesCoverage'].append('hip_extension')
    previous = {'requirementsId': 'REQ-1', 'sessionsPerWeek': 3,
        'requiredCoverage': [{'key': 'hip_extension', 'scope': 'weekly'}], 'redistributions': []}

    carried = carry_repair_contract(previous, current, source, source, requirements_id='REQ-1')

    assert carried['sessionsPerWeek'] == 3
    assert carried['requiredCoverage'] == previous['requiredCoverage']
    assert repair_contract_errors(carried, source) == []


def test_new_contract_preserves_structured_coverage_errors_for_preflight():
    source = _draft()
    contract = build_repair_contract([], source, {
        'sessionsPerWeek': 3, 'requiredCoverage': [
            {'key': 'upper_push_each_session', 'scope': 'eachSession'}]}, [], requirements_id='REQ-1')
    candidate = copy.deepcopy(source)
    candidate['workouts'][1]['exercises'] = []
    carried = carry_repair_contract(None, contract, source, candidate, requirements_id='REQ-1')
    errors = repair_contract_errors(carried, candidate)
    assert any(error['code'] == 'required_coverage_missing'
        and error['coverageKey'] == 'upper_push_each_session'
        and error['path'] == '/workouts/1/exercises' for error in errors)
