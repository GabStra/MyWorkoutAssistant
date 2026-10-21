import copy
import json

import pytest

from workout_generator_pkg import allocation, plan_review, session_drafting
from workout_generator_pkg.planning_tools import audit_workout_plan, set_workout_requirements, build_draft_plan
from test_workout_generator_planning_tools import planning_case, requirement_messages


@pytest.fixture(autouse=True)
def qualified_recipe_fixture(monkeypatch):
    # Recipe qualification has dedicated tests; these tests isolate drafting/repair behavior.
    monkeypatch.setattr('workout_generator_pkg.recipe_contracts.qualify_recipe_contracts',
        lambda *args, **kwargs: {'inputHash': 'qualified-fixture', 'contracts': [], 'capabilities': {}})


def prepared_case():
    equipment, requirements, _, draft = planning_case()
    requirements['sessionsPerWeek'] = 3
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 15, 'maximum': 18}
    stored = set_workout_requirements(requirements, [{'role': 'user', 'content': 'Three sessions, chest 5-6 per session and 15-18 weekly.'}], equipment)
    messages = requirement_messages(stored)
    arguments = {'requirementsId': stored['requirementsId'], 'baseDraftId': None, 'name': 'Week',
        'sessions': [{'name': f'Day {i}', 'description': 'Push', 'trainingDays': [i*2], 'timesCompletedInAWeek': 1,
                      'exercises': [
                          {'definition_id': 'LIBRARY_0', 'numWorkSets': 3, 'allocationBounds': {'minimum': 3, 'maximum': 6}, 'superset': None}]}
                     for i in range(3)]}
    return equipment, requirements, messages, arguments, draft


def test_failed_structure_scope_preserves_completed_reviews_and_resumes_only_missing(monkeypatch):
    equipment, _, messages, arguments, _ = prepared_case()
    prepared = session_drafting.prepare_workout_sessions(arguments, messages, equipment)
    def review(client, context, messages, scope, logger):
        if scope == 'workout_0':
            raise RuntimeError('Review transport failed')
        return {'inputHash': plan_review._hash(context), 'findings': [], 'outOfScopeNumericalObservationCount': 0}
    monkeypatch.setattr(plan_review, '_review_structure_part', review)
    with pytest.raises(RuntimeError) as caught:
        plan_review.review_week_structure(None, prepared, None, messages, equipment)
    saved = caught.value.structure_review_checkpoint
    assert saved['inProgress'] and set(saved['scopeResults']) == {'week', 'workout_1', 'workout_2'}
    requested = []
    def resume(client, context, messages, scope, logger):
        requested.append(scope)
        return {'inputHash': plan_review._hash(context), 'findings': [], 'outOfScopeNumericalObservationCount': 0}
    monkeypatch.setattr(plan_review, '_review_structure_part', resume)
    finished = plan_review.review_week_structure(None, prepared, None, messages, equipment, cached=saved)
    assert finished['passed'] and requested == ['workout_0']


@pytest.mark.parametrize('fallback_fails', [False, True])
def test_reasoning_exhaustion_retries_unchanged_review_once_without_thinking(monkeypatch, fallback_fails):
    from types import SimpleNamespace
    from workout_generator_pkg import api_client
    from workout_generator_pkg.api_client import TruncatedResponseError
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
        content=None, tool_calls=None, reasoning_content='thinking'))], usage=SimpleNamespace(
            model_dump=lambda: {'completion_tokens': 24, 'completion_tokens_details': {'reasoning_tokens': 24}}))
    error = TruncatedResponseError(response, 24, 'low')
    request, calls = [{'role': 'user', 'content': 'Unchanged review evidence'}], []
    schema = {'type': 'object'}
    def call(client, actual, tools, **options):
        assert actual is request and options['output_schema'] is schema
        calls.append(options['reasoning_effort'])
        if len(calls) == 1 or fallback_fails:
            raise error
        return '{"findings":[]}', None, None
    monkeypatch.setattr(api_client, '_chat_call_once', call)
    if fallback_fails:
        with pytest.raises(TruncatedResponseError):
            plan_review._review_call(None, request, reasoning_effort='low', output_schema=schema)
    else:
        assert plan_review._review_call(None, request, reasoning_effort='low', output_schema=schema)[0] == '{"findings":[]}'
    assert calls == ['low', None]


def test_preparation_allocates_integer_counts_before_any_prescriptions():
    equipment, _, messages, arguments, _ = prepared_case()
    original = copy.deepcopy(arguments)
    prepared = session_drafting.prepare_workout_sessions(arguments, messages, equipment)
    assert arguments == original
    assert [day['exercises'][0]['numWorkSets'] for day in prepared['sessions']] == [5, 5, 5]
    assert prepared['setAllocation']['feasible']
    arguments['sessions'][0]['exercises'][0]['allocationBounds']['maximum'] = 4
    assert session_drafting.prepare_workout_sessions(arguments, messages, equipment)['setAllocation']['feasible']  # Model bounds do not bind the solver.


def test_integer_allocation_preserves_group_equality_frequency_and_fixed_bounds():
    candidates = {'LIBRARY_0': {'creditsPerWorkingSet': {'chest': {'direct': 1}}},
                  'LIBRARY_1': {'creditsPerWorkingSet': {'back': {'direct': 1}}}}
    days = [{'timesCompletedInAWeek': 2,
             'exercises': [{'definition_id': f'LIBRARY_{i}', 'numWorkSets': 2, 'allocationBounds': {'minimum': 2, 'maximum': 6}, 'superset': 'A'} for i in range(2)]}]
    requirements = {'auditTargets': {'weeklyEffectiveSets': {key: {'minimum': 10, 'maximum': 10} for key in ('chest', 'back')}}}
    result = allocation.allocate_prepared_sets(days, candidates, requirements)
    assert result['feasible'] and [item['numWorkSets'] for item in result['sessions'][0]['exercises']] == [5, 5]
    days[0]['exercises'][1]['allocationBounds'] = {'minimum': 2, 'maximum': 2}
    result = allocation.allocate_prepared_sets(days, candidates, requirements)
    assert not result['feasible'] and result['status'] == 'infeasible'
    assert days[0]['exercises'][0]['numWorkSets'] == 2


def test_initial_allocation_spreads_work_before_preserving_arbitrary_seed_counts():
    candidates = {
        'LIBRARY_0': {'creditsPerWorkingSet': {'chest': {'direct': 1}, 'back': {'direct': 1}}},
        'LIBRARY_1': {'creditsPerWorkingSet': {'chest': {'direct': 1}}},
        'LIBRARY_2': {'creditsPerWorkingSet': {'back': {'direct': 1}}},
    }
    days = [{'timesCompletedInAWeek': 1, 'exercises': [
        {'definition_id': reference, 'numWorkSets': 3, 'superset': None,
         'allocationBounds': {'minimum': 1, 'maximum': 20}} for reference in candidates]}]
    requirements = {'auditTargets': {'weeklyEffectiveSets': {
        muscle: {'minimum': 15, 'maximum': 15} for muscle in ('chest', 'back')}}}
    result = allocation.allocate_prepared_sets(days, candidates, requirements)
    assert result['feasible']
    assert [e['numWorkSets'] for e in result['sessions'][0]['exercises']] == [10, 5, 5]
    # A source-fixed count still overrides the workload preference.
    days[0]['exercises'][0]['allocationBounds'] = {'minimum': 12, 'maximum': 12}
    days[0]['exercises'][0]['numWorkSets'] = 12
    result = allocation.allocate_prepared_sets(days, candidates, requirements)
    assert [e['numWorkSets'] for e in result['sessions'][0]['exercises']] == [12, 3, 3]


def test_structure_role_counts_include_frequency_without_invalidating_other_days():
    equipment, requirements, _, _, _ = prepared_case()
    requirements['requiredCoverage'] = [
        {'key': key, 'description': key, 'scope': 'weekly'} for key in ('pattern_a', 'pattern_b')]
    stored = set_workout_requirements(requirements, [], equipment)
    messages = requirement_messages(stored)
    days = [{'name': 'A', 'timesCompletedInAWeek': 2, 'exercises': [
        {'definition_id': 'LIBRARY_0', 'numWorkSets': 3, 'satisfiesCoverage': ['pattern_a', 'pattern_a']}]},
        {'name': 'B', 'timesCompletedInAWeek': 1, 'exercises': [
        {'definition_id': 'LIBRARY_0', 'numWorkSets': 4, 'satisfiesCoverage': ['pattern_b']}]}]
    context = plan_review._week_structure_context(days, messages, equipment)
    assert context['weeklyCoverageSets'] == {'pattern_a': 6, 'pattern_b': 4}
    assert context['draft']['workouts'][0]['coverageSets'] == {'pattern_a': 3, 'pattern_b': 0}
    parts = dict(plan_review._structure_review_parts(context))
    assert parts['workout_0']['verifiedWeeklyCoverage'] == {'pattern_a': True, 'pattern_b': True}
    assert parts['workout_0']['requirements']['requiredCoverage'] == []
    assert {rule['key'] for rule in parts['workout_0']['weeklyCoverageDefinitions']} == {'pattern_a', 'pattern_b'}
    days[1]['exercises'][0]['numWorkSets'] = 5
    changed = dict(plan_review._structure_review_parts(plan_review._week_structure_context(days, messages, equipment)))
    assert plan_review._hash(parts['workout_0']) == plan_review._hash(changed['workout_0'])
    assert plan_review._hash(parts['week']) != plan_review._hash(changed['week'])


def test_structure_reviewer_blocks_before_workers_and_reuses_only_matching_receipts(monkeypatch):
    equipment, _, messages, arguments, _ = prepared_case()
    prepared = session_drafting.prepare_workout_sessions(arguments, messages, equipment)
    calls = []
    def review(client, request, **options):
        calls.append(request)
        payload = json.loads(request[-1]['content'])
        index = int(payload['reviewScope']['workoutReference'].split('_')[1]) if payload['reviewScope']['kind'] == 'workout' else 0
        assert 'allocationBounds' not in payload['draft']['workouts'][index]['exercises'][0]
        assert 'auditTargets' not in payload['requirements']
        definition = payload['draft']['libraryDefinitions']['LIBRARY_0']
        assert 'creditsPerWorkingSet' not in definition and 'muscleRoles' not in definition
        assert definition['muscleGroups'] == ['FRONT_CHEST']
        assert definition['secondaryMuscleGroups'] == ['BACK_TRICEPS']
        assert set(payload['auditPolicy']) == {'supportedMuscleTargets', '_reviewRef'}
        schema = options['output_schema']['properties']['findings']['items']
        assert schema['properties']['basis']['enum'] == ['established_violation', 'uncertainty']
        index = int(payload['reviewScope']['workoutReference'].split('_')[1]) if payload['reviewScope']['kind'] == 'workout' else 0
        ref = payload['draft']['workouts'][index]['_reviewRef']
        return json.dumps({'findings': [{'check': 'equipment_setup', 'basis': 'established_violation', 'severity': 'warning', 'muscleTargets': [],
            'path': ref, 'evidencePaths': [ref], 'message': 'An established execution contradiction.',
            'repair': 'Correct the selected structure.'}]}), None, None
    monkeypatch.setattr(plan_review, 'chat_call', review)
    receipt = plan_review.review_week_structure(None, prepared, None, messages, equipment)
    assert not receipt['passed'] and receipt['findings'][0]['severity'] == 'blocking'
    assert plan_review.review_week_structure(None, prepared, None, messages, equipment, receipt) == receipt
    assert len(calls) == 4
    changed = copy.deepcopy(prepared)
    changed['sessions'][0]['exercises'][0]['numWorkSets'] += 1
    plan_review.review_week_structure(None, changed, None, messages, equipment, receipt)
    assert len(calls) == 6


def test_approved_rest_adjustment_repairs_overrun_without_model_or_other_changes():
    equipment, requirements, _, draft = planning_case()
    requirements['auditTargets']['maximumSessionSeconds'] = 807
    requirements['executionRules'] = [{'kind': 'rest', 'coverageKey': None, 'context': 'straightSets',
                                     'minimumSeconds': 60, 'maximumSeconds': 120}]
    stored = set_workout_requirements(requirements, [{'role': 'user', 'content': 'Use 60-120 second rests.'}], equipment)
    messages = requirement_messages(stored)
    draft['requirementsId'] = stored['requirementsId']
    before = copy.deepcopy(draft)
    result = audit_workout_plan(draft, equipment, messages)
    assert result['audit']['workouts'][0]['estimatedSeconds'] == 810
    repaired = allocation.auto_allocate_workout(result, equipment, messages)
    assert repaired['passed'] and repaired['audit']['workouts'][0]['estimatedSeconds'] <= 807
    item = repaired['submittedDraft']['workouts'][0]['exercises'][0]
    assert item['restBetweenSetsSeconds'] == 60
    assert item['numWorkSets'] == before['workouts'][0]['exercises'][0]['numWorkSets']
    assert draft == before
    requirements['executionRules'][0]['minimumSeconds'] = 90
    stored = set_workout_requirements(requirements, [{'role': 'user', 'content': 'Use 90-120 second rests.'}], equipment)
    messages = requirement_messages(stored)
    draft['requirementsId'] = stored['requirementsId']
    fixed = audit_workout_plan(draft, equipment, messages)
    rejected = allocation.auto_allocate_workout(fixed, equipment, messages)
    assert not rejected['automaticAllocation']['feasible']
    assert rejected['submittedDraft'] == fixed['submittedDraft']


def test_progression_notes_are_derived_and_units_are_checked():
    equipment, _, stored, draft = planning_case()
    item = draft['workouts'][0]['exercises'][0]
    equipment['equipments'] = [{'id': 'EQUIPMENT_0', 'name': 'Vest', 'type': 'WEIGHTVEST', 'availableWeights': [{'weight': 5}]}]
    equipment['exerciseDefinitions'][0]['equipmentId'] = 'EQUIPMENT_0'
    item.update(progressionMethod='doubleProgression')
    plan = build_draft_plan(draft, equipment, stored['requirements'])
    note = plan['exercises'][0]['placementNotes']
    assert 'reach the rep ceiling on all sets before adding a supported load step' in note
    assert 'Count verified work only' not in note
    assert item['placementNotes'] == 'Controlled reps.'
    item['progressionMethod'] = 'duration'
    with pytest.raises(ValueError, match='units'):
        build_draft_plan(draft, equipment, stored['requirements'])


def store(messages, name, result):
    key = f'tool_{len(messages)}'
    messages.extend([{'role': 'assistant', 'tool_calls': [{'id': key, 'function': {'name': name, 'arguments': '{}'}}]},
                     {'role': 'tool', 'tool_call_id': key, 'content': json.dumps(result)}])


def test_joint_prescription_checkpoint_reuses_workers_without_early_review(monkeypatch):
    equipment, _, messages, arguments, draft = prepared_case()
    prepared = session_drafting.prepare_workout_sessions(arguments, messages, equipment)
    store(messages, 'prepare_workout_sessions', prepared)
    monkeypatch.setattr(plan_review, 'chat_call', lambda *a, **k: pytest.fail('Review needs the executable week'))
    def worker(client, request, **kwargs):
        item = copy.deepcopy(draft['workouts'][0]['exercises'][0])
        item.update(progressionMethod='reps', repDurationSeconds=3)
        return json.dumps({'exercises': [item]}), None, None
    monkeypatch.setattr(session_drafting, 'chat_call', worker)
    checkpoints = []
    result = session_drafting.draft_workout_sessions(None, {'preparationId': prepared['preparationId']}, messages, equipment, {},
        checkpoint=lambda value: checkpoints.append(copy.deepcopy(value)))
    assert result['jointPlanning']['feasible']
    assert len(checkpoints[-1]['workerResults']) == 3
    assert 'structureReview' not in result
    store(messages, 'draft_workout_sessions', result)
    monkeypatch.setattr(session_drafting, 'chat_call', lambda *a, **k: pytest.fail('Completed workers must be reused'))
    resumed = session_drafting.draft_workout_sessions(None, {'preparationId': prepared['preparationId']}, messages, equipment, {})
    assert resumed['proposedSubmission'] == result['proposedSubmission']


def test_joint_failure_retains_recipes_and_stops_before_submission(monkeypatch):
    from workout_generator_pkg import joint_planning
    equipment, _, messages, arguments, draft = prepared_case()
    prepared = session_drafting.prepare_workout_sessions(arguments, messages, equipment)
    store(messages, 'prepare_workout_sessions', prepared)
    def worker(*args, **kwargs):
        items = copy.deepcopy(draft['workouts'][0]['exercises'])
        for item in items:
            item.update(progressionMethod='reps', repDurationSeconds=3)
        return json.dumps({'exercises': items}), None, None
    monkeypatch.setattr(session_drafting, 'chat_call', worker)
    monkeypatch.setattr(joint_planning, 'solve_prescribed_week', lambda *a, **k: {
        'feasible': False, 'status': 'infeasible', 'instruction': 'The approved time and volume conflict in this menu.'})
    result = session_drafting.draft_workout_sessions(None, {'preparationId': prepared['preparationId']}, messages, equipment, {})
    assert not result['passed'] and result['executionFailure'] and 'proposedSubmission' not in result
    assert len(result['workerResults']) == 3
    assert result['errors'][0]['code'] == 'joint_planning_infeasible'


def test_partial_week_allocation_counts_existing_sessions_without_changing_them():
    equipment, requirements, messages, arguments, draft = prepared_case()
    existing = copy.deepcopy(draft)
    existing['requirementsId'] = arguments['requirementsId']
    before = copy.deepcopy(existing)
    from workout_generator_pkg.exercise_library_tools import get_exercise_candidates
    candidates = {item['id']: item for item in get_exercise_candidates({'definition_ids': ['LIBRARY_0']}, equipment, messages)['exercises']}
    result = allocation.allocate_prepared_sets(arguments['sessions'][1:], candidates, requirements, existing, equipment)
    assert result['feasible'] and [day['exercises'][0]['numWorkSets'] for day in result['sessions']] == [5, 5]
    assert existing == before


def test_duration_repair_respects_superset_execution_and_intersected_ranges():
    equipment, requirements, _, draft = planning_case()
    first = draft['workouts'][0]['exercises'][0]
    first.update(numWorkSets=3, superset='A', restBetweenSetsSeconds=0, restAfterSupersetExerciseSeconds=45)
    second = copy.deepcopy(first)
    second['restAfterSupersetExerciseSeconds'] = 90
    draft['workouts'][0]['exercises'].append(second)
    rules = [{'kind': 'rest', 'coverageKey': None, 'context': 'supersetTransition', 'minimumSeconds': 30, 'maximumSeconds': 45},
             {'kind': 'rest', 'coverageKey': None, 'context': 'supersetTransition', 'minimumSeconds': 44, 'maximumSeconds': 45},
             {'kind': 'rest', 'coverageKey': None, 'context': 'supersetRound', 'minimumSeconds': 90, 'maximumSeconds': 90}]
    requirements['executionRules'] = rules
    stored = set_workout_requirements(requirements, [], equipment)
    draft['requirementsId'] = stored['requirementsId']
    baseline = audit_workout_plan(draft, equipment, requirement_messages(stored))
    requirements['auditTargets']['maximumSessionSeconds'] = baseline['audit']['workouts'][0]['estimatedSeconds'] - 3
    stored = set_workout_requirements(requirements, [], equipment)
    draft['requirementsId'] = stored['requirementsId']
    messages = requirement_messages(stored)
    raw = audit_workout_plan(draft, equipment, messages)
    changed = allocation.auto_allocate_workout(raw, equipment, messages)
    assert changed['passed']
    items = changed['submittedDraft']['workouts'][0]['exercises']
    assert items[0]['restAfterSupersetExerciseSeconds'] == 44
    assert items[1]['restAfterSupersetExerciseSeconds'] == second['restAfterSupersetExerciseSeconds']
    assert items[0]['numWorkSets'] == items[1]['numWorkSets']


def test_evidence_cache_ignores_unrelated_arithmetic_but_preserves_own_prescription():
    equipment, _, stored, draft = planning_case()
    draft['workouts'][0]['exercises'].append(copy.deepcopy(draft['workouts'][0]['exercises'][0]))
    raw = audit_workout_plan(draft, equipment, requirement_messages(stored))
    context = plan_review._context(raw, requirement_messages(stored), equipment, None, 3)
    before = plan_review._evidence_review_context(context, ['EXERCISE_0'])
    changed = copy.deepcopy(context)
    changed['audit']['weeklyWorkingSets'] = 100
    changed['audit']['workouts'][0]['estimatedSeconds'] = 999
    changed['draft']['exercises'][1]['placementNotes'] = 'Unrelated note'
    assert plan_review._evidence_review_context(changed, ['EXERCISE_0']) == before
    changed['draft']['exercises'][0]['minReps'] += 1
    assert plan_review._evidence_review_context(changed, ['EXERCISE_0']) != before


def test_structure_authority_ignores_post_instruction_planner_chatter():
    equipment, _, messages, _, draft = prepared_case()
    before = plan_review._week_structure_context(draft['workouts'], messages, equipment)
    chatter = messages + [{'role': 'assistant', 'content': 'I will now draft the selected sessions.'}]
    assert plan_review._week_structure_context(draft['workouts'], chatter, equipment) == before
    answered = chatter + [{'role': 'user', 'content': 'Change the order.'}]
    assert plan_review._week_structure_context(draft['workouts'], answered, equipment) != before


def test_preparation_null_bounds_are_preferences_and_schema_repairs_are_atomic():
    from workout_generator_pkg.planning_tools import PlanningInputError, planning_tool_failure
    from test_workout_generator_parallel_planning import store_tool
    equipment, _, messages, arguments, _ = prepared_case()
    for day in arguments['sessions']:
        day['exercises'][0].update(numWorkSets=5, allocationBounds=None)
    prepared = session_drafting.prepare_workout_sessions(arguments, messages, equipment)
    assert all(day['exercises'][0]['allocationBounds'] == {'minimum': 1, 'maximum': 20}
               for day in prepared['sessions'])
    bad = copy.deepcopy(arguments)
    bad['sessions'][0]['exercises'][0]['numWorkSets'] = 'five'
    bad['sessions'][1]['exercises'][0]['superset'] = 42
    with pytest.raises(PlanningInputError) as caught:
        session_drafting.prepare_workout_sessions(bad, messages, equipment)
    store_tool(messages, 'prepare_workout_sessions', bad,
               planning_tool_failure('prepare_workout_sessions', caught.value, bad))
    task = session_drafting.preparation_repair_task(messages)
    assert len(task['errors']) == 2
    patch = {'basePreparationId': task['basePreparationId'], 'patch': [
        {'op': 'replace', 'path': '/sessions/0/exercises/0/numWorkSets', 'value': 5},
        {'op': 'replace', 'path': '/sessions/1/exercises/0/superset', 'value': None}]}
    repaired = session_drafting.prepare_workout_sessions(patch, messages, equipment)
    assert repaired['sessions'] == prepared['sessions']
    assert bad['sessions'][0]['exercises'][0]['numWorkSets'] == 'five'
    patch['patch'].append({'op': 'replace', 'path': '/sessions/2/name', 'value': 'Unrelated'})
    with pytest.raises(PlanningInputError, match='scope|permitted|outside'):
        session_drafting.prepare_workout_sessions(patch, messages, equipment)


def test_preparation_removes_orphaned_group_preferences_without_changing_inputs():
    equipment, _, messages, arguments, _ = prepared_case()
    arguments['sessions'][0]['exercises'][0]['superset'] = 'orphan'
    original = copy.deepcopy(arguments)
    prepared = session_drafting.prepare_workout_sessions(arguments, messages, equipment)
    assert prepared['setAllocation']['feasible']
    assert prepared['sessions'][0]['exercises'][0]['superset'] is None
    assert arguments == original


def test_structure_review_receives_selected_history_before_prescriptions_and_hashes_it():
    from test_workout_generator_parallel_planning import store_tool
    from workout_generator_pkg.planning_tools import library_fingerprint
    equipment, _, messages, arguments, _ = prepared_case()
    payload = {'historyFingerprint': 'snapshot', 'libraryFingerprint': library_fingerprint(equipment),
               'exercises': [{'reference': 'LIBRARY_0', 'definitionId': equipment['exerciseDefinitions'][0]['id'],
                   'name': 'Recorded movement', 'status': 'comparable_records', 'totalSessions': 1,
                   'loadSuitabilityConcerns': ['historical_load_not_selectable'],
                   'loadHeadroom': {'highestObservedComparableLoad': {'loadKg': 70, 'reps': 8}},
                   'sessions': [{'date': '2026-10-01', 'performances': [{'record': {'reps': 8, 'weight': 70}}]}]}]}
    store_tool(messages, 'get_training_evidence', {'definition_ids': ['LIBRARY_0']}, payload)
    context = plan_review._week_structure_context(arguments['sessions'], messages, equipment, 'snapshot')
    record = context['history']['LIBRARY_0']
    assert record['loadSuitabilityConcerns'] == ['historical_load_not_selectable']
    assert record['loadHeadroom']['highestObservedComparableLoad']['loadKg'] == 70
    assert 'sessions' not in record
    assert context['historyFingerprint'] == 'snapshot'
    assert plan_review._week_structure_context(arguments['sessions'], messages, equipment, 'other')['history'] == {}
    changed = copy.deepcopy(payload)
    changed['exercises'][0]['loadHeadroom']['highestObservedComparableLoad']['loadKg'] = 80
    store_tool(messages, 'get_training_evidence', {'definition_ids': ['LIBRARY_0']}, changed)
    assert plan_review._hash(context) != plan_review._hash(
        plan_review._week_structure_context(arguments['sessions'], messages, equipment, 'snapshot'))


def test_numeric_review_claims_cannot_override_allocator_but_semantic_defects_still_block(monkeypatch):
    equipment, _, messages, arguments, _ = prepared_case()
    prepared = session_drafting.prepare_workout_sessions(arguments, messages, equipment)
    include_semantic = False
    def review(client, request, **options):
        payload = json.loads(request[-1]['content'])
        index = int(payload['reviewScope']['workoutReference'].split('_')[1]) if payload['reviewScope']['kind'] == 'workout' else 0
        ref = payload['draft']['workouts'][index]['_reviewRef']
        finding = {'check': 'numerical', 'basis': 'established_violation', 'severity': 'blocking', 'muscleTargets': ['chest'],
            'path': ref, 'evidencePaths': [ref], 'message': 'Wrong arithmetic claims nine chest sets instead of the verified fifteen.',
            'repair': 'Add extra sets based on this incorrect recalculation.'}
        semantic = {**finding, 'check': 'equipment_setup', 'muscleTargets': [],
                    'message': 'A concrete shared-implement reconfiguration conflict.', 'repair': 'Separate these partners.'}
        return json.dumps({'findings': [finding, semantic] if include_semantic else [finding]}), None, None
    monkeypatch.setattr(plan_review, 'chat_call', review)
    receipt = plan_review.review_week_structure(None, prepared, None, messages, equipment)
    assert receipt['passed'] and receipt['findings'] == []
    assert receipt['outOfScopeNumericalObservationCount'] == 4
    assert 'Wrong arithmetic' not in json.dumps(receipt)
    assert [day['exercises'][0]['numWorkSets'] for day in prepared['sessions']] == [5, 5, 5]
    include_semantic = True
    receipt = plan_review.review_week_structure(None, prepared, None, messages, equipment)
    assert not receipt['passed'] and len(receipt['findings']) == 3
    assert all(item['check'] == 'equipment_setup' for item in receipt['findings'])


def test_preparation_uses_the_same_timed_volume_rules_as_the_final_audit():
    from workout_generator_pkg.planning_tools import PlanningInputError
    from workout_generator_pkg.exercise_library_tools import get_exercise_candidates
    equipment, _, messages, arguments, _ = prepared_case()
    equipment['exerciseDefinitions'][0].update(exerciseType='COUNTDOWN', bodyWeightPercentage=None, name='Timed chest hold')
    candidate = get_exercise_candidates({'definition_ids': ['LIBRARY_0']}, equipment, messages)['exercises'][0]
    assert candidate['creditsPerWorkingSet'] == {}
    assert 'no effective-set equivalence' in candidate['volumeAuditNote']
    context = plan_review._week_structure_context(arguments['sessions'], messages, equipment)
    assert context['draft']['libraryDefinitions']['LIBRARY_0']['muscleGroups'] == ['FRONT_CHEST']
    with pytest.raises(PlanningInputError) as failure:
        session_drafting.prepare_workout_sessions(arguments, messages, equipment)
    assert failure.value.code == 'infeasible_set_allocation'
    assert failure.value.errors[0]['conflictingTargets'][0]['rangeWithinSlotBounds'] == [0, 0]


@pytest.mark.parametrize('layout', [False, True])
def test_preparation_reports_all_group_errors_with_original_permissions(layout):
    from workout_generator_pkg.planning_tools import PlanningInputError
    days = [{'timesCompletedInAWeek': 1, 'exercises': [
        {'definition_id': 'LIBRARY_0', 'numWorkSets': 2, 'superset': 'A'},
        {'definition_id': 'LIBRARY_0', 'numWorkSets': 4, 'superset': 'A'},
        {'definition_id': 'LIBRARY_0', 'numWorkSets': 2, 'superset': 'B'},
        {'definition_id': 'LIBRARY_0', 'numWorkSets': 4, 'superset': 'B'}]} for _ in range(2)]
    if layout:
        for day in days:
            day['exercises'][1]['superset'] = None
            day['exercises'][3]['superset'] = None
    original = copy.deepcopy(days)
    with pytest.raises(PlanningInputError) as caught:
        allocation.allocate_prepared_sets(days, {}, {'auditTargets': {}})
    assert days == original
    errors = caught.value.errors
    assert len(errors) == 4
    assert {item['code'] for item in errors} == {'prepared_group_layout' if layout else 'prepared_group_bounds'}
    for item in errors:
        if layout:
            assert item['permittedPaths']['descendants'] == [item['path']]
        else:
            assert len(item['permittedPaths']['exact']) == 6
            assert all(path.endswith(('/numWorkSets', '/allocationBounds', '/superset'))
                       for path in item['permittedPaths']['exact'])


def shared_block_case():
    equipment, requirements, messages, arguments, _ = prepared_case()
    for day in arguments['sessions']:
        member = {'definition_id': day.pop('exercises')[0]['definition_id'], 'satisfiesCoverage': []}
        day['blocks'] = [{'numWorkSets': 3, 'allocationBounds': {'minimum': 2, 'maximum': 3},
                          'exercises': [member, copy.deepcopy(member)]}]
    return equipment, requirements, messages, arguments


def test_shared_block_is_a_candidate_preference_not_a_hard_count_or_duplicate():
    equipment, _, messages, arguments = shared_block_case()
    original = copy.deepcopy(arguments)
    prepared = session_drafting.prepare_workout_sessions(arguments, messages, equipment)
    assert arguments == original
    for day in prepared['sessions']:
        assert 'blocks' not in day
        assert len(day['exercises']) == 1
        assert day['exercises'][0]['numWorkSets'] == 5
        assert day['exercises'][0]['superset'] is None
        assert day['exercises'][0]['allocationBounds'] == {'minimum': 1, 'maximum': 20}
    assert prepared['setAllocation']['feasible']


def test_shared_block_schema_rejects_member_counts_and_retains_scoped_repair():
    from workout_generator_pkg.planning_tools import PlanningInputError, planning_tool_failure
    from test_workout_generator_parallel_planning import store_tool
    equipment, _, messages, arguments = shared_block_case()
    arguments['sessions'][0]['blocks'][0]['exercises'][1]['numWorkSets'] = 4
    with pytest.raises(PlanningInputError) as caught:
        session_drafting.prepare_workout_sessions(arguments, messages, equipment)
    feedback = planning_tool_failure('prepare_workout_sessions', caught.value, arguments)
    assert feedback['preparationArguments'] == arguments
    store_tool(messages, 'prepare_workout_sessions', arguments, feedback)
    task = session_drafting.preparation_repair_task(messages)
    path = '/sessions/0/blocks/0/exercises/1/numWorkSets'
    from workout_generator_pkg import interactive_shell as shell
    from workout_generator_pkg.planner_context import request_planning_state
    state = request_planning_state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert set(state['exerciseCandidates']) == {'LIBRARY_0'}
    assert state['preparationRepairTask']['arguments'] == arguments
    corrected = session_drafting.prepare_workout_sessions({'basePreparationId': task['basePreparationId'],
        'patch': [{'op': 'remove', 'path': path}]}, messages, equipment)
    assert [item['numWorkSets'] for item in corrected['sessions'][0]['exercises']] == [5]
    with pytest.raises(PlanningInputError, match='outside|permitted'):
        session_drafting.prepare_workout_sessions({'basePreparationId': task['basePreparationId'],
            'patch': [{'op': 'replace', 'path': '/sessions/0/blocks/0/numWorkSets', 'value': 4}]}, messages, equipment)


def test_compiled_blocks_preserve_description_without_changing_allocated_counts():
    equipment, _, messages, arguments = shared_block_case()
    arguments['sessions'][0]['description'] = 'Push focus'
    prepared = session_drafting.prepare_workout_sessions(arguments, messages, equipment)
    assert 'blocks' not in prepared['sessions'][0]
    assert prepared['sessions'][0]['description'] == arguments['sessions'][0]['description']
    assert [item['numWorkSets'] for item in prepared['sessions'][0]['exercises']] == [5]


@pytest.mark.parametrize('kind,weights,load_progression', [
    ('BODY_WEIGHT', [], False), ('WEIGHT', [5], False),
    ('BODY_WEIGHT', [5], True), ('WEIGHT', [5, 10], True)])
def test_load_progression_requires_actual_selectable_load_steps(kind, weights, load_progression):
    from workout_generator_pkg.planning_tools import PlanningInputError
    equipment, _, stored, draft = planning_case()
    definition = equipment['exerciseDefinitions'][0]
    definition.update(exerciseType=kind, bodyWeightPercentage=65 if kind == 'BODY_WEIGHT' else None)
    if weights:
        equipment['equipments'] = [{'id': 'EQUIPMENT_0', 'name': 'Dumbbell', 'type': 'DUMBBELL',
            'dumbbells': [{'weight': weight} for weight in weights]}]
        definition['equipmentId'] = 'EQUIPMENT_0'
    item = draft['workouts'][0]['exercises'][0]
    item['progressionMethod'] = 'doubleProgression'
    original = copy.deepcopy(draft)
    if load_progression:
        assert 'supported load step' in build_draft_plan(draft, equipment, stored['requirements'])['exercises'][0]['placementNotes']
    else:
        with pytest.raises(PlanningInputError) as caught:
            build_draft_plan(draft, equipment, stored['requirements'])
        error = next(e for e in caught.value.errors if e['code'] == 'progression_load_unavailable')
        root = '/workouts/0/exercises/0'
        assert error['path'] == root + '/progressionMethod'
        assert error['permittedPaths'] == {'exact': [root + '/progressionMethod', root + '/placementNotes'], 'descendants': []}
        assert draft == original  # Validation must request repair, never rewrite the prescription.
        item.update(progressionMethod='sourceDefined', placementNotes='At the rep ceiling, progress controlled range; re-audit variants before using them.')
        note = build_draft_plan(draft, equipment, stored['requirements'])['exercises'][0]['placementNotes']
        assert 'supported load step' not in note and 'progress controlled range' in note


def test_parallel_structure_review_preserves_completed_parts_and_waits_for_all_scopes(monkeypatch):
    import threading
    equipment, _, messages, arguments, _ = prepared_case()
    prepared = session_drafting.prepare_workout_sessions(arguments, messages, equipment)
    store(messages, 'prepare_workout_sessions', prepared)
    barrier = threading.Barrier(3)
    calls, checkpoints = [], []
    first = True
    def respond(client, request, **options):
        payload = json.loads(request[-1]['content'])
        scope = payload['reviewScope']
        key = scope.get('workoutReference', 'week')
        calls.append(key)
        if first and key != 'WORKOUT_2':
            barrier.wait(timeout=3)  # These independent requests must overlap.
        if first and key == 'week':
            raise RuntimeError('Temporary weekly review failure')
        if key.startswith('WORKOUT_'):
            index = int(key.split('_')[1])
            assert 'history' not in payload and 'historyFingerprint' not in payload
            assert all(day.get('detailsOmitted') for i, day in enumerate(payload['draft']['workouts']) if i != index)
        if key == 'WORKOUT_0':
            ref = payload['draft']['workouts'][0]['_reviewRef']
            return json.dumps({'findings': [{'check': 'equipment_setup', 'basis': 'established_violation',
                'severity': 'blocking', 'muscleTargets': [], 'path': ref, 'evidencePaths': [ref],
                'message': 'A real local setup defect.', 'repair': 'Repair that setup.'}]}), None, None
        return json.dumps({'findings': []}), None, None
    monkeypatch.setattr(plan_review, 'chat_call', respond)
    with pytest.raises(RuntimeError, match='Temporary weekly'):
        plan_review.review_week_structure(None, prepared, None, messages, equipment, on_checkpoint=checkpoints.append)
    partial = checkpoints[-1]
    assert partial['inProgress'] and not partial['passed'] and len(partial['scopeResults']) == 3
    assert partial['findings'][0]['severity'] == 'blocking'
    store(messages, 'draft_workout_sessions', {'preparationId': prepared['preparationId'], 'structureReview': partial, 'inProgress': True})
    assert session_drafting.preparation_repair_task(messages) is None
    first = False
    calls.clear()
    complete = plan_review.review_week_structure(None, prepared, None, messages, equipment, cached=partial)
    assert calls == ['week'] and not complete['inProgress'] and not complete['passed']
    assert complete['findings'] == partial['findings'] and len(complete['scopeResults']) == 4


def test_movement_only_preparation_allocates_counts_and_preserves_explicit_source_bounds():
    from jsonschema import Draft7Validator
    equipment, requirements, messages, _, _ = prepared_case()
    requirements['auditTargets']['perSessionEffectiveSets'] = {}
    stored = set_workout_requirements(requirements, [{'role': 'user', 'content': 'Three full-body sessions; weekly chest 15-18. Allocate counts.'}], equipment)
    messages = requirement_messages(stored)
    arguments = {'requirementsId': stored['requirementsId'], 'baseDraftId': None, 'name': 'Week',
        'sessions': [{'name': f'Day {i}', 'description': 'Push', 'trainingDays': [i * 2], 'timesCompletedInAWeek': 1,
                      'blocks': [{'exercises': [{'definition_id': 'LIBRARY_0'}]}]} for i in range(3)]}
    original = copy.deepcopy(arguments)
    public = session_drafting.PREPARE_WORKOUT_SESSIONS_TOOL['function']['parameters']
    Draft7Validator(public).validate(arguments)
    prepared = session_drafting.prepare_workout_sessions(arguments, messages, equipment)
    assert arguments == original
    assert [day['exercises'][0]['numWorkSets'] for day in prepared['sessions']] == [5, 5, 5]
    assert prepared['setAllocation']['feasible']
    assert all(day['exercises'][0]['allocationBounds'] == {'minimum': 1, 'maximum': 20} for day in prepared['sessions'])
    counted = copy.deepcopy(arguments)
    counted['sessions'][0]['blocks'][0]['numWorkSets'] = 5
    assert not Draft7Validator(public).is_valid(counted)  # The model's new tool has no arithmetic output field.
    arguments['sessions'][0]['blocks'][0]['allocationBounds'] = {'minimum': 2, 'maximum': 2}
    assert not Draft7Validator(public).is_valid(arguments)
    arguments['sessions'][0]['blocks'][0].pop('allocationBounds')
    requirements['executionRules'] = [{'kind': 'workSets', 'coverageKey': None, 'minimumSets': 5, 'maximumSets': 5}]
    fixed_requirements = set_workout_requirements(requirements, [{'role': 'user', 'content': 'Exactly 5 sets per exercise.'}], equipment)
    arguments['requirementsId'] = fixed_requirements['requirementsId']
    fixed = session_drafting.prepare_workout_sessions(arguments, requirement_messages(fixed_requirements), equipment)
    assert [day['exercises'][0]['numWorkSets'] for day in fixed['sessions']] == [5, 5, 5]
    assert all(day['exercises'][0]['allocationBounds'] == {'minimum': 5, 'maximum': 5} for day in fixed['sessions'])
    arguments['sessions'][0]['blocks'] = None
    schema = session_drafting._preparation_schema(arguments)
    assert schema is not public
    assert 'blocks' in schema['properties']['sessions']['items'][0]['properties']
    assert isinstance(public['properties']['sessions']['items'], dict)
