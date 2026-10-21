import copy
import json

import pytest

from workout_generator_pkg import allocation, plan_review, interactive_shell as shell
from workout_generator_pkg.planner_context import pending_evidence
from workout_generator_pkg.planning_tools import (
    audit_workout_plan, get_workout_draft, latest_draft_submission, set_workout_requirements,
    validate_repair_scope, PlanningInputError,
)
from workout_generator_pkg.training_history import pool_execution_contexts
from test_workout_generator_planning_tools import planning_case, requirement_messages
from test_workout_generator_planner_context import _state, _tool


@pytest.mark.parametrize('feasible', [True, False])
def test_automatic_allocator_is_cached_and_reviews_only_a_complete_passing_patch(monkeypatch, feasible):
    equipment, requirements, stored, draft = planning_case()
    if not feasible:
        requirements['auditTargets']['maximumSessionSeconds'] = 500
        stored = set_workout_requirements(requirements, [], equipment)
        draft['requirementsId'] = stored['requirementsId']
    item = draft['workouts'][0]['exercises'][0]
    item.update(numWorkSets=3, allocationBounds={'minimum': 3, 'maximum': 6})
    messages = requirement_messages(stored)
    original = copy.deepcopy(draft)
    solves, reviews = [], []
    solve = allocation.allocate_workout_sets
    def allocate(*args, **kwargs):
        solves.append(1)
        return solve(*args, **kwargs)
    def review(*args, **kwargs):
        reviews.append(1)
        return '{"findings":[]}', None, None
    monkeypatch.setattr(allocation, 'allocate_workout_sets', allocate)
    monkeypatch.setattr(plan_review, 'chat_call', review)
    response = shell.handle_function_call(None, messages, 'audit_workout_plan', draft, equipment)
    result = json.loads(response['result'])
    assert result['passed'] is feasible
    assert len(solves) == 1 and len(reviews) == int(feasible)
    assert draft == original
    assert result['submittedDraft']['workouts'][0]['exercises'][0]['numWorkSets'] == (5 if feasible else 3)
    assert result['automaticAllocation']['feasible'] is feasible
    _tool(messages, 'audit_workout_plan', draft, result, 'first')
    current, revision = latest_draft_submission(messages, equipment)
    assert current == result['submittedDraft'] and revision == result['currentDraftId']
    repeated = shell.handle_function_call(None, messages, 'audit_workout_plan', {
        'requirementsId': stored['requirementsId'], 'baseDraftId': revision, 'patch': []}, equipment)
    assert json.loads(repeated['result'])['passed'] is feasible
    assert len(solves) == 1 and len(reviews) == int(feasible)


def test_after_preview_allocation_proposes_tradeoffs_without_undoing_the_edit():
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    approved = audit_workout_plan(draft, equipment, messages)
    _tool(messages, 'audit_workout_plan', draft, approved, 'approved')
    messages.append({'role': 'assistant', 'content': approved['preview'], 'canonicalDraftPreview': approved['draftId']})
    patch = {'requirementsId': stored['requirementsId'], 'baseDraftId': approved['currentDraftId'], 'patch': [
        {'op': 'replace', 'path': '/workouts/0/exercises/0/numWorkSets', 'value': 3},
        {'op': 'add', 'path': '/workouts/0/exercises/0/allocationBounds', 'value': {'minimum': 1, 'maximum': 6}}]}
    rejected = audit_workout_plan(patch, equipment, messages)
    before = copy.deepcopy(rejected)
    result = allocation.auto_allocate_workout(rejected, equipment, messages)
    assert not result['passed'] and result['errors'] == before['errors']
    assert result['submittedDraft'] == before['submittedDraft']
    assert result['submittedDraft']['workouts'][0]['exercises'][0]['numWorkSets'] == 3
    proposal = result['automaticAllocation']
    assert proposal['application'] == 'proposal' and proposal['feasible']
    assert proposal['patch'] == [{'op': 'replace', 'path': '/workouts/0/exercises/0/numWorkSets', 'value': 5}]
    assert rejected == before
    _tool(messages, 'audit_workout_plan', patch, result, 'proposal')
    accepted = audit_workout_plan({'requirementsId': stored['requirementsId'],
        'baseDraftId': result['currentDraftId'], 'patch': proposal['patch']}, equipment, messages)
    assert accepted['passed'] and accepted['submittedDraft']['workouts'][0]['exercises'][0]['numWorkSets'] == 5


def test_automatic_allocation_does_not_invent_bounds_or_change_exact_prescriptions(monkeypatch):
    equipment, _, stored, draft = planning_case()
    item = draft['workouts'][0]['exercises'][0]
    item['numWorkSets'] = 3
    messages = requirement_messages(stored)
    def forbidden(*args, **kwargs):
        raise AssertionError('Locked or undeclared flexibility must not trigger allocation.')
    monkeypatch.setattr(allocation, 'allocate_workout_sets', forbidden)
    result = audit_workout_plan(draft, equipment, messages)
    assert not allocation.auto_allocate_workout(result, equipment, messages)['passed']
    item.update(allocationBounds={'minimum': 1, 'maximum': 6}, targetSetPrescriptions=[
        {'workSetIndex': i, 'reps': 10, 'additionalWeight': 0} for i in range(3)])
    result = audit_workout_plan(draft, equipment, messages)
    assert not allocation.auto_allocate_workout(result, equipment, messages)['passed']


def test_related_findings_share_one_scoped_task_and_full_sessions_remain_readable():
    equipment, requirements, _, draft = planning_case()
    requirements.update(sessionsPerWeek=3, executionRules=[{'kind': 'rest', 'coverageKey': None,
        'context': 'straightSets', 'minimumSeconds': 120, 'maximumSeconds': 180}])
    requirements['auditTargets'] = {'weeklyEffectiveSets': {}, 'perSessionEffectiveSets': {}, 'maximumSessionSeconds': 10000}
    stored = set_workout_requirements(requirements, [], equipment)
    draft['requirementsId'] = stored['requirementsId']
    draft['workouts'] = [copy.deepcopy(draft['workouts'][0]) for _ in range(3)]
    for i, day in enumerate(draft['workouts']):
        day['exercises'][0].update(restBetweenSetsSeconds=150 if i == 1 else 60, placementNotes='detail ' * 40)
    messages = requirement_messages(stored)
    result = audit_workout_plan(draft, equipment, messages)
    _tool(messages, 'audit_workout_plan', draft, result, 'audit')
    before = copy.deepcopy(messages)
    state = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert state['repairTask']['findingIndexes'] == [0, 1]
    assert state['repairTask']['editableWorkoutReferences'] == ['WORKOUT_0', 'WORKOUT_2']
    assert state['currentDraft']['workouts'][1]['detailsOmitted']
    assert state['allocationSlots']['SLOT_2']['path'] == '/workouts/2/exercises/0'
    with pytest.raises(PlanningInputError, match='Read omitted'):
        validate_repair_scope({'patch': [{'op': 'replace', 'path': '/workouts/1/exercises/0/numWorkSets', 'value': 2}]}, state['repairTask'])
    with pytest.raises(PlanningInputError, match='Read omitted'):
        validate_repair_scope({'patch': [{'op': 'remove', 'path': '/workouts/0'}]}, state['repairTask'])
    read = get_workout_draft({'baseDraftId': result['currentDraftId'], 'workoutReferences': ['WORKOUT_1']}, messages, equipment)
    assert read['workouts']['WORKOUT_1'] == draft['workouts'][1]
    assert messages == before
    _tool(messages, 'get_workout_draft', {}, read, 'read')
    expanded = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert expanded['currentDraft']['workouts'][1] == draft['workouts'][1]
    validate_repair_scope({'patch': [{'op': 'replace', 'path': '/workouts/1/exercises/0/numWorkSets', 'value': 2}]}, expanded['repairTask'])
    with pytest.raises(ValueError, match='stale'):
        get_workout_draft({'baseDraftId': 'REVISION_999', 'workoutReferences': ['WORKOUT_1']}, messages, equipment)


def test_pending_evidence_batches_all_selected_references_without_refetching_summaries():
    state = {'requirementsApproved': True, 'currentDraftAudited': True, 'selectedDefinitionReferences': ['LIBRARY_0', 'LIBRARY_1', 'LIBRARY_2'],
             'lastAudit': {'errors': [{'code': 'duration_exceeded'}]}, 'trainingEvidenceSummary': {'LIBRARY_0': {}},
             'trainingEvidence': {}, 'attemptedEvidence': ['LIBRARY_2']}
    assert pending_evidence(state) == ['LIBRARY_1']
    state['planningDecisionNeeded'] = True
    assert pending_evidence(state) == []


def test_reviewer_audit_reference_scopes_to_one_session_instead_of_the_whole_program():
    from workout_generator_pkg.planner_context import _focus_repair
    _, _, _, draft = planning_case()
    draft['workouts'] = [copy.deepcopy(draft['workouts'][0]) for _ in range(3)]
    state = {'requirementsApproved': True, 'currentDraftId': 'REVISION_0', 'currentDraft': draft,
        'lastAudit': {'passed': False, 'errors': [{'code': 'independent_review_finding', 'path': '/audit/workouts/0'}]},
        'exerciseCandidates': {}, 'trainingEvidence': {}, 'otherToolResults': {}}
    _focus_repair(state, set())
    assert state['repairTask']['editableWorkoutReferences'] == ['WORKOUT_0']
    assert state['currentDraft']['workouts'][1]['detailsOmitted']
    assert plan_review._draft_patch_path('/audit/workouts/0/timing', {'workouts': [{}], 'exercises': []}) == '/workouts/0'


def test_repeated_execution_context_pooling_is_lossless_and_reduces_request_size():
    context = {'type': 'superset', 'memberIndex': 0, 'members': [
        {'name': 'Movement ' + str(i), 'restAfterSeconds': 40 if i == 0 else 90} for i in range(4)]}
    evidence = {'LIBRARY_0': {'sessions': [{'performances': [
        {'order': i, 'executionContext': copy.deepcopy(context), 'record': {'loadKg': 20, 'actualReps': 12 - i}}
        for i in range(5)]}]}}
    before = copy.deepcopy(evidence)
    compact, contexts = pool_execution_contexts(evidence)
    assert len(contexts) == 1 and evidence == before
    assert len(json.dumps({'history': compact, 'historyExecutionContexts': contexts})) < len(json.dumps(evidence))
    for p in compact['LIBRARY_0']['sessions'][0]['performances']:
        p['executionContext'] = contexts[p.pop('executionContextRef')]
    assert compact == evidence


def test_partial_week_repairs_local_blockers_then_resumes_construction():
    equipment, requirements, _, draft = planning_case()
    requirements.update(sessionsPerWeek=3, minimumRestDaysBetweenSessions=1)
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 15, 'maximum': 18}
    stored = set_workout_requirements(requirements, [], equipment)
    messages = requirement_messages(stored)
    draft['requirementsId'] = stored['requirementsId']
    result = audit_workout_plan(draft, equipment, messages)
    _tool(messages, 'audit_workout_plan', draft, result, 'first-session')
    original = copy.deepcopy(messages)
    state = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert state['repairTask']['findingCode'] == 'schedule_days_required'
    indexes = state['repairTask']['findingIndexes']
    assert all(state['lastAudit']['errors'][i]['code'] == 'schedule_days_required' for i in indexes)
    assert state['repairTask']['findingIndex'] == indexes[0] > 0
    assert 'week is incomplete' in state['repairTask']['instruction']
    assert not state.get('availableAlternativeCountByMuscle')
    assert messages == original
    patch = {'requirementsId': stored['requirementsId'], 'baseDraftId': result['currentDraftId'], 'patch': [
        {'op': 'add', 'path': '/workouts/0/trainingDays', 'value': [0]}]}
    repaired = audit_workout_plan(patch, equipment, messages)
    # This saved concern reproduces the second local blocker in the retained run.
    concern = {'code': 'training_load_suitability_unresolved', 'path': '/workouts/0/exercises/0'}
    repaired['errors'].append(concern)
    _tool(messages, 'audit_workout_plan', patch, repaired, 'scheduled')
    state = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert state['repairTask']['findingCode'] == concern['code']
    repaired['errors'].remove(concern)
    _tool(messages, 'audit_workout_plan', {'requirementsId': stored['requirementsId'],
        'baseDraftId': repaired['currentDraftId'], 'patch': []}, repaired, 'load-resolved')
    state = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert state['constructionTask']['action'] == 'append_session' and not state.get('repairTask')


def test_discovery_outcomes_survive_compaction_and_unchanged_audits_do_not_reopen_search():
    from workout_generator_pkg.exercise_library_tools import execute_library_tool
    from workout_generator_pkg.planner_context import discovery_tool_failure
    equipment, _, stored, draft = planning_case()
    draft['workouts'][0]['exercises'][0]['numWorkSets'] = 3
    messages = requirement_messages(stored)
    audit = audit_workout_plan(draft, equipment, messages)
    _tool(messages, 'audit_workout_plan', draft, audit, 'draft')
    for key, queries in [('first', ['Push-Up']), ('repeat', [' push-up '])]:
        args = {'queries': queries, 'muscleTargets': ['chest']}
        result = execute_library_tool('search_exercise_library', args, equipment, messages=messages)
        _tool(messages, 'search_exercise_library', args, result, key)
    before = copy.deepcopy(messages)
    state = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert len(state['completedSearches']) == 1
    assert state['completedSearches'][0]['definition_ids'] == ['LIBRARY_0']
    assert discovery_tool_failure('search_exercise_library', state)['errors'][0]['code'] == 'lookup_no_progress'
    assert discovery_tool_failure('get_exercise_candidates', state)
    assert discovery_tool_failure('get_training_evidence', state) is None
    assert messages == before
    unchanged = {'requirementsId': stored['requirementsId'], 'baseDraftId': audit['currentDraftId'], 'patch': []}
    repeated = audit_workout_plan(unchanged, equipment, messages)
    _tool(messages, 'audit_workout_plan', unchanged, repeated, 'unchanged')
    assert _state(shell._messages_for_api(messages, True, provided_equipment=equipment))['discoveryPaused']
    patch = {**unchanged, 'patch': [{'op': 'replace', 'path': '/workouts/0/exercises/0/numWorkSets', 'value': 4}]}
    revised = audit_workout_plan(patch, equipment, messages)
    _tool(messages, 'audit_workout_plan', patch, revised, 'changed')
    assert not _state(shell._messages_for_api(messages, True, provided_equipment=equipment)).get('discoveryPaused')
    messages.append({'role': 'user', 'content': 'Check a different alternative.'})
    assert not _state(shell._messages_for_api(messages, True, provided_equipment=equipment)).get('discoveryPaused')


def test_empty_filtered_searches_are_remembered_but_invalidated_by_library_changes():
    from workout_generator_pkg.exercise_library_tools import execute_library_tool
    equipment, _, stored, draft = planning_case()
    draft['workouts'][0]['exercises'][0]['numWorkSets'] = 3
    messages = requirement_messages(stored)
    _tool(messages, 'audit_workout_plan', draft, audit_workout_plan(draft, equipment, messages), 'draft')
    for key, query in [('first', 'chest fly'), ('synonym', 'chest isolation')]:
        args = {'queries': [query], 'muscleTargets': ['chest'], 'exerciseCategories': ['ISOLATION']}
        result = execute_library_tool('search_exercise_library', args, equipment, messages=messages)
        _tool(messages, 'search_exercise_library', args, result, key)
    state = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert len(state['completedSearches']) == 1 and state['discoveryPaused']
    assert state['completedSearches'][0]['queries'] == ['chest fly', 'chest isolation']
    assert all(item['matchMethod'] == 'no_suitable_matches' and item['definition_ids'] == []
               and item['searchFilters']['muscleTargets'] == ['chest'] for item in state['completedSearches'])
    equipment['exerciseDefinitions'].append({**copy.deepcopy(equipment['exerciseDefinitions'][0]),
        'id': 'chest-isolation', 'name': 'Dumbbell Fly', 'muscleGroups': ['FRONT_CHEST'], 'exerciseCategory': 'ISOLATION'})
    state = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert not state.get('completedSearches') and not state.get('discoveryPaused')


def test_discovery_progress_is_measured_per_batch_and_novel_results_remain_available():
    from workout_generator_pkg.planner_context import _focus_discovery
    state = {}
    facts = {('candidate', 'LIBRARY_0')}
    _focus_discovery(state, {1: facts, 2: facts | {('candidate', 'LIBRARY_1')}}, 0)
    assert not state.get('discoveryPaused')
    _focus_discovery(state, {1: facts, 2: facts}, 0)
    assert state['discoveryPaused']
    state = {}
    _focus_discovery(state, {1: facts, 2: facts}, 2)
    assert not state.get('discoveryPaused')


def test_conversational_edit_can_allocate_sets_without_a_failed_audit(monkeypatch, tmp_path):
    from test_workout_generator_conversation_sessions import make_shell_deps, FakeToolCall, FakeFunction
    equipment, requirements, _, draft = planning_case()
    path = tmp_path / 'library.json'
    path.write_text(json.dumps(equipment), encoding='utf-8')
    def tool(name, args, key):
        return (None, [FakeToolCall(key, 'function', FakeFunction(name, json.dumps(args)))])
    deps = make_shell_deps(tmp_path, chat_results=[
        tool('set_workout_requirements', requirements, 'requirements'),
        tool('audit_workout_plan', draft, 'draft'),
        ('I can redistribute the requested working sets.', None)], generation_results=[], generation_calls=[])
    requests = []
    chat = deps.chat_call_with_loading
    def capture(client, messages, tools, logger, **options):
        state = _state(messages) if any((m.get('content') or '').startswith('Current planning state') for m in messages) else {}
        requests.append((state, [t['function']['name'] for t in tools if 'function' in t]))
        return chat(client, messages, tools, logger, **options)
    deps.chat_call_with_loading = capture
    monkeypatch.setattr('sys.argv', ['workout_generator.py', '--exercise-library-file', str(path)])
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test-key')
    inputs = iter(['Plan chest training', 'CONFIRM REQUIREMENTS', 'Redistribute sets to reduce concentrated fatigue.', '/exit'])
    monkeypatch.setattr('builtins.input', lambda prompt='': next(inputs))
    shell.main(deps=deps)
    state, tools = requests[-1]
    assert state.get('editTask') and not state.get('repairTask')
    assert 'allocate_workout_sets' in tools


@pytest.mark.parametrize('batched', [False, True])
def test_shell_withholds_redundant_discovery_and_rejects_unadvertised_repeated_calls(monkeypatch, tmp_path, batched):
    from test_workout_generator_conversation_sessions import make_shell_deps, FakeToolCall, FakeFunction
    equipment, requirements, _, draft = planning_case()
    requirements.update(sessionsPerWeek=3, minimumRestDaysBetweenSessions=1)
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 15, 'maximum': 18}
    path = tmp_path / 'library.json'
    path.write_text(json.dumps(equipment), encoding='utf-8')
    def tool(name, args, key):
        return (None, [FakeToolCall(key, 'function', FakeFunction(name, json.dumps(args)))])
    blocked = tool('search_exercise_library', {'queries': ['Push-Up']}, 'unadvertised')
    if batched:
        blocked[1].append(FakeToolCall('details', 'function', FakeFunction('get_exercise_candidates',
            json.dumps({'definition_ids': ['LIBRARY_0']}))))
    deps = make_shell_deps(tmp_path, chat_results=[
        tool('set_workout_requirements', requirements, 'requirements'),
        tool('audit_workout_plan', draft, 'draft'),
        tool('search_exercise_library', {'queries': ['Push-Up']}, 'first'),
        tool('search_exercise_library', {'queries': ['Push-Up']}, 'repeat'),
        blocked,
        ('I will repair the pending draft.', None)], generation_results=[], generation_calls=[])
    requests, executed = [], []
    chat, handle = deps.chat_call_with_loading, deps.handle_function_call
    def capture(client, messages, tools, logger, **options):
        requests.append([t['function']['name'] for t in tools if 'function' in t])
        return chat(client, messages, tools, logger, **options)
    def dispatch(*args, **kwargs):
        executed.append(args[2])
        return handle(*args, **kwargs)
    deps.chat_call_with_loading, deps.handle_function_call = capture, dispatch
    monkeypatch.setattr('sys.argv', ['workout_generator.py', '--exercise-library-file', str(path)])
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test-key')
    inputs = iter(['Plan chest training', 'CONFIRM REQUIREMENTS', '/exit'])
    monkeypatch.setattr('builtins.input', lambda prompt='': next(inputs))
    shell.main(deps=deps)
    assert 'search_exercise_library' in requests[3]
    assert 'search_exercise_library' not in requests[4]
    assert 'get_exercise_candidates' not in requests[4]
    assert 'audit_workout_plan' in requests[4]
    assert 'allocate_workout_sets' in requests[4]
    assert executed.count('search_exercise_library') == 2
    assert 'get_exercise_candidates' not in executed
