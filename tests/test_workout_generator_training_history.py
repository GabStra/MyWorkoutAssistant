import copy
import json
import threading
import pytest

from workout_generator_pkg.training_history import TrainingHistory
from workout_generator_pkg.cancellation import run_cancellable
from workout_generator_pkg.interactive_shell import handle_function_call, _messages_for_api
from test_workout_generator_planning_tools import planning_case, requirement_messages


@pytest.fixture(autouse=True)
def independent_review_passes(monkeypatch):
    monkeypatch.setattr('workout_generator_pkg.plan_review.chat_call', lambda *a, **k: ('{"findings":[]}', None, None))


def history_case():
    equipment, _, stored, draft = planning_case()
    occurrence = {'type': 'Exercise', 'id': 'occurrence', 'exerciseDefinitionId': 'press',
                  'exerciseType': 'BODY_WEIGHT', 'equipmentId': None,
                  'sets': [{'type': 'RestSet', 'timeInSeconds': 90}]}
    backup = {'WorkoutStore': {**copy.deepcopy(equipment), 'workouts': [
        {'id': 'version1', 'workoutComponents': [occurrence]}]},
        'WorkoutHistories': [{'id': 'session', 'workoutId': 'version1', 'isDone': True, 'date': '2026-10-01'}],
        'SetHistories': [{'id': 'actual', 'exerciseId': 'occurrence', 'workoutHistoryId': 'session',
                         'setData': {'type': 'BodyWeightSetData', 'actualReps': 12, 'additionalWeight': 0,
                                     'relativeBodyWeightInKg': 49}}]}
    return equipment, stored, draft, backup


def test_cancelled_matching_does_not_block_new_turns_or_publish_late_cache_results(monkeypatch):
    equipment, _, _, backup = history_case()
    equipment['exerciseDefinitions'].append({**equipment['exerciseDefinitions'][0], 'id': 'new', 'name': 'Related variant'})
    history = TrainingHistory(backup)
    entered, release, cancelled, returned, turn_ready = (threading.Event() for _ in range(5))
    calls = []
    def slow_rank(*args):
        calls.append(1)
        entered.set()
        assert release.wait(3)
        return [{0: .9}]
    monkeypatch.setattr('workout_generator_pkg.exercise_library_tools._semantic_matches', slow_rank)
    arguments = {'definition_ids': ['LIBRARY_0']}
    failures = []
    def lookup():
        try:
            run_cancellable(history.evidence, arguments, equipment, object(), cancel_event=cancelled)
        except KeyboardInterrupt:
            returned.set()
        except Exception as error:
            failures.append(error)
    worker = threading.Thread(target=lookup, daemon=True)
    worker.start()
    try:
        assert entered.wait(1)
        cancelled.set()
        assert returned.wait(1)
        next_turn = threading.Thread(target=lambda: (history.begin_turn(), turn_ready.set()), daemon=True)
        next_turn.start()
        assert turn_ready.wait(1), 'A cancelled matcher must not hold the cache lock needed by the next turn.'
    finally:
        release.set()
        worker.join(1)
    assert history._related_matching_lock.acquire(timeout=1)
    history._related_matching_lock.release()
    assert not failures and not history._related_cache
    # A fresh request can retry; subsequent identical requests reuse the completed match.
    first = history.evidence(arguments, equipment, client=object())
    assert first['exercises'][0]['relatedMovementHistory']
    assert history.evidence(arguments, equipment, client=object()) == first
    assert len(calls) == 2


def test_waiting_for_a_running_match_is_cancellable_and_does_not_schedule_more_work(monkeypatch):
    equipment, _, _, backup = history_case()
    history = TrainingHistory(backup)
    started, cancelled, finished = (threading.Event() for _ in range(3))
    def exact(*args):
        started.set()
        return {'exercises': []}
    calls = []
    monkeypatch.setattr(history, '_exact_evidence', exact)
    monkeypatch.setattr(history, '_add_related_history', lambda *a: calls.append(1))
    failures = []
    def lookup():
        try:
            run_cancellable(history.evidence, {}, equipment, object(), cancel_event=cancelled)
        except KeyboardInterrupt:
            finished.set()
        except Exception as error:
            failures.append(error)
    history._related_matching_lock.acquire()
    worker = threading.Thread(target=lookup, daemon=True)
    worker.start()
    try:
        assert started.wait(1)
        cancelled.set()
        assert finished.wait(1)
    finally:
        history._related_matching_lock.release()
        worker.join(1)
    assert history._related_matching_lock.acquire(timeout=1)
    history._related_matching_lock.release()
    assert not failures and not calls


def test_actual_records_exclude_warmups_skips_and_calibration():
    equipment, _, _, backup = history_case()
    for category in ('WarmupSet', 'CalibrationSet', 'CalibrationPendingSet'):
        record = copy.deepcopy(backup['SetHistories'][0])
        record['setData']['subCategory'] = category
        backup['SetHistories'].append(record)
    skipped = copy.deepcopy(backup['SetHistories'][0])
    skipped['skipped'] = True
    backup['SetHistories'].append(skipped)
    history = TrainingHistory(backup)
    evidence = history.evidence({'definition_ids': ['LIBRARY_0']}, equipment)
    performances = evidence['exercises'][0]['sessions'][0]['performances']
    assert len(performances) == 1
    assert performances[0]['record']['actualReps'] == 12
    assert performances[0]['record']['recordedRelativeBodyWeightKg'] == 49
    assert performances[0]['record']['loadKg'] == 0
    assert 'rir' not in performances[0]['record']
    assert performances[0]['prescribedRestSeconds'] == [90]
    assert evidence['exercises'][0]['loadHeadroom']['observedAtCurrentEquipmentMaximum']


def test_superset_history_keeps_schedule_through_planner_and_reviewer_compaction():
    from workout_generator_pkg.training_history import compact_training_evidence
    from workout_generator_pkg.plan_review import _compact_evidence
    equipment, _, _, backup = history_case()
    first = backup['WorkoutStore']['workouts'][0]['workoutComponents'][0]
    first['name'] = 'Push-Up'
    partner = {**copy.deepcopy(first), 'id': 'partner', 'name': 'Row'}
    backup['WorkoutStore']['workouts'][0]['workoutComponents'] = [{
        'type': 'Superset', 'exercises': [partner, first],
        'restSecondsByExercise': {'partner': 30, 'occurrence': 75}}]
    history = TrainingHistory(backup)
    item = history.evidence({'definition_ids': ['LIBRARY_0']}, equipment)['exercises'][0]
    expected = {'type': 'superset', 'memberIndex': 1, 'members': [
        {'name': 'Row', 'enabled': True, 'restAfterSeconds': 30, 'exerciseRestSetsSeconds': [90]},
        {'name': 'Push-Up', 'enabled': True, 'restAfterSeconds': 75, 'exerciseRestSetsSeconds': [90]}]}
    for evidence in (item, compact_training_evidence([item])['LIBRARY_0'], _compact_evidence(item)):
        performance = evidence['sessions'][0]['performances'][0]
        assert performance['prescribedRestSeconds'] == []
        assert performance['executionContext'] == expected
        assert performance['record']['actualReps'] == 12


def test_versions_do_not_transfer_history_to_other_definition():
    equipment, _, _, backup = history_case()
    other = {**equipment['exerciseDefinitions'][0], 'id': 'other', 'name': 'Other movement'}
    equipment['exerciseDefinitions'].append(other)
    backup['WorkoutStore']['exerciseDefinitions'].append(other)
    occurrence = copy.deepcopy(backup['WorkoutStore']['workouts'][0]['workoutComponents'][0])
    occurrence['exerciseDefinitionId'] = 'other'
    backup['WorkoutStore']['workouts'].append({'id': 'version2', 'workoutComponents': [occurrence]})
    history = TrainingHistory(backup)
    evidence = history.evidence({'definition_ids': ['LIBRARY_0', 'LIBRARY_1']}, equipment)
    assert [item['totalSessions'] for item in evidence['exercises']] == [0, 1]
    assert history.unresolved_records == 0


def test_pagination_cache_and_changed_identity():
    equipment, _, _, backup = history_case()
    backup['WorkoutHistories'].append({'id': 'older', 'workoutId': 'version1', 'isDone': True, 'date': '2026-09-01'})
    record = copy.deepcopy(backup['SetHistories'][0])
    record.update(id='older-set', workoutHistoryId='older')
    backup['SetHistories'].append(record)
    history = TrainingHistory(backup)
    arguments = {'definition_ids': ['LIBRARY_0'], 'session_limit': 1}
    first = history.evidence(arguments, equipment)
    assert first['exercises'][0]['nextOffset'] == 1
    default = history.evidence({'definition_ids': ['LIBRARY_0']}, equipment)
    assert len(default['exercises'][0]['sessions']) == 1 and default['exercises'][0]['nextOffset'] == 1
    first['exercises'].clear()
    assert history.evidence(arguments, equipment)['exercises']
    older = history.evidence({**arguments, 'session_offset': 1}, equipment)
    assert older['exercises'][0]['sessions'][0]['sessionId'] == 'older'
    changed = copy.deepcopy(equipment)
    changed['exerciseDefinitions'][0]['bodyWeightPercentage'] = 80
    assert history.evidence(arguments, changed)['exercises'][0]['status'] == 'no_comparable_records'


def test_related_history_is_separate_cached_and_required_for_unrecorded_variant(monkeypatch):
    equipment, _, _, backup = history_case()
    historical = backup['WorkoutStore']['exerciseDefinitions'][0]
    historical.update(name='Barbell Romanian Deadlift', exerciseType='WEIGHT', equipmentId='bar', bodyWeightPercentage=None)
    occurrence = backup['WorkoutStore']['workouts'][0]['workoutComponents'][0]
    occurrence.update(exerciseType='WEIGHT', equipmentId='bar')
    backup['SetHistories'][0]['setData'] = {'type': 'WeightSetData', 'actualReps': 10, 'actualWeight': 79}
    gear = [{'id': 'bar', 'name': 'Barbell', 'type': 'BARBELL', 'barWeight': 10, 'availablePlates': []}]
    equipment['equipments'] = backup['WorkoutStore']['equipments'] = gear
    equipment['exerciseDefinitions'] = [copy.deepcopy(historical),
        {**copy.deepcopy(historical), 'id': 'db', 'name': 'Dumbbell Romanian Deadlift', 'equipmentId': None}]
    history = TrainingHistory(backup)
    calls = []
    def rank(client, queries, entries):
        calls.append(queries)
        assert len(entries) == 1 and entries[0]['name'] == 'Barbell Romanian Deadlift'
        return [{0: .96} for _ in queries]
    monkeypatch.setattr('workout_generator_pkg.exercise_library_tools._semantic_matches', rank)
    arguments = {'definition_ids': ['LIBRARY_0'], 'session_limit': 1}
    result = history.evidence(arguments, equipment, client=object())
    item = result['exercises'][0]
    assert item['sessions'] == [] and item['totalSessions'] == 0
    related = item['relatedMovementHistory'][0]
    assert related['definitionId'] == 'press' and related['reference'] == 'LIBRARY_1'
    assert related['matchType'] == 'related_not_equivalent'
    assert related['sessions'][0]['performances'][0]['record']['loadKg'] == 79
    assert related['differences']['equipmentId'] == {'candidate': None, 'historical': 'bar'}
    result['exercises'].clear()
    assert history.evidence(arguments, equipment, client=object())['exercises'] and len(calls) == 1
    plan = {'exercises': [{'libraryDefinitionId': 'db'}]}
    assert history.unreviewed(plan, [], equipment) == ['LIBRARY_0']
    messages = [{'role': 'assistant', 'tool_calls': [{'id': 'lookup', 'function': {'name': 'get_training_evidence'}}]},
                {'role': 'tool', 'tool_call_id': 'lookup', 'content': json.dumps(history.evidence(arguments, equipment, client=object()))}]
    assert history.unreviewed(plan, messages, equipment) == []
    plan['exercises'][0]['id'] = 'EXERCISE_0'
    plan['exercises'][0]['name'] = 'Dumbbell Romanian Deadlift'
    assert history.load_suitability_errors(plan, messages, equipment)[0]['concerns'][0]['code'] == 'related_history_only'
    plan['exercises'][0]['requiresEffortCalibration'] = True
    assert history.load_suitability_errors(plan, messages, equipment) == []


def test_failed_history_matching_retries_on_a_new_turn_and_keeps_successful_cache(monkeypatch):
    from workout_generator_pkg.exercise_library_tools import _SemanticMatchResults
    equipment, _, _, backup = history_case()
    equipment['exerciseDefinitions'].append({**equipment['exerciseDefinitions'][0],
        'id': 'zzz-new', 'name': 'Unrecorded variant'})
    calls = []

    def rank(*args, **kwargs):
        calls.append(1)
        result = _SemanticMatchResults([{0: 0.2 if len(calls) == 1 else 0.95}])
        if len(calls) == 1:
            result.rerank_failures = {0: 'temporary outage'}
        return result

    monkeypatch.setattr('workout_generator_pkg.exercise_library_tools._semantic_matches', rank)
    history = TrainingHistory(backup)
    arguments = {'definition_ids': ['LIBRARY_1']}
    first = history.evidence(arguments, equipment, client=object())
    assert first['exercises'][0]['relatedHistoryStatus'] == 'checked_local_unconfirmed'
    history.evidence(arguments, equipment, client=object())
    assert len(calls) == 1
    history.begin_turn()
    recovered = history.evidence(arguments, equipment, client=object())
    assert recovered['exercises'][0]['relatedHistoryStatus'] == 'checked'
    assert recovered['exercises'][0]['relatedMovementHistory']
    history.begin_turn()
    history.evidence(arguments, equipment, client=object())
    assert len(calls) == 2


def test_failed_weak_history_rerank_keeps_load_uncertainty_for_unrecorded_variant(monkeypatch):
    equipment, _, _, backup = history_case()
    historical = backup['WorkoutStore']['exerciseDefinitions'][0]
    historical.update(name='Old Press Variant', exerciseType='WEIGHT', equipmentId='bar', bodyWeightPercentage=None)
    equipment['exerciseDefinitions'] = [{**copy.deepcopy(historical), 'id': 'current', 'name': 'New Press Variant', 'equipmentId': None}]

    class UncertainMatches(list):
        rerank_failures = {0: 'rerank service unavailable'}

    monkeypatch.setattr('workout_generator_pkg.exercise_library_tools._semantic_matches',
                        lambda *_args, **_kwargs: UncertainMatches([{0: 0.2}]))
    history = TrainingHistory(backup)
    result = history.evidence({'definition_ids': ['LIBRARY_0']}, equipment, client=object())
    item = result['exercises'][0]

    assert item['relatedHistoryStatus'] == 'checked_local_unconfirmed'
    assert item['relatedMovementHistory'] == []
    assert 'adjudication failed' in item['relatedHistoryWarning']
    plan = {'exercises': [{'id': 'EXERCISE_0', 'libraryDefinitionId': 'current', 'name': 'New Press Variant'}]}
    messages = [{'role': 'assistant', 'tool_calls': [{'id': 'evidence', 'function': {'name': 'get_training_evidence'}}]},
                {'role': 'tool', 'tool_call_id': 'evidence', 'content': json.dumps(result)}]
    errors = history.load_suitability_errors(plan, messages, equipment)
    assert errors[0]['concerns'][0]['code'] == 'related_history_unconfirmed'
    plan['exercises'][0]['requiresEffortCalibration'] = True
    assert history.load_suitability_errors(plan, messages, equipment) == []
    assert history.unreviewed(plan, messages, equipment) == []


def test_uncertain_related_lookup_does_not_flag_exact_own_history():
    assert TrainingHistory._load_concerns({
        'totalSessions': 2,
        'loadHeadroom': {'maximumSelectableLoadKg': 100, 'latestSessionHeaviestLoadKg': 80},
        'relatedMovementHistory': [],
        'relatedHistoryStatus': 'checked_local_unconfirmed',
    }) == []


def test_history_only_movement_survives_compaction_for_planning_and_independent_review(monkeypatch):
    from workout_generator_pkg.plan_review import _context
    from workout_generator_pkg.training_history import compact_training_evidence
    equipment, stored, draft, backup = history_case()
    equipment['exerciseDefinitions'][0].update(id='new-definition', name='Renamed Push-Up')
    history = TrainingHistory(backup)
    calls = []
    def rank(client, queries, entries):
        calls.append(queries)
        return [{0: .95} for _ in queries]
    monkeypatch.setattr('workout_generator_pkg.exercise_library_tools._semantic_matches', rank)
    evidence = history.evidence({'definition_ids': ['LIBRARY_0']}, equipment, client=object())
    item = evidence['exercises'][0]
    related = item['relatedMovementHistory'][0]
    assert related['reference'] == 'HISTORY_0' and related['definitionId'] == 'press'
    compact = compact_training_evidence([item])
    assert compact['LIBRARY_0']['relatedMovementHistory'][0]['reference'] == 'HISTORY_0'
    assert compact['HISTORY_0']['sessions'][0]['performances'][0]['record']['actualReps'] == 12
    assert history.evidence({'definition_ids': ['LIBRARY_0']}, equipment, client=object()) == evidence
    assert len(calls) == 1
    messages = requirement_messages(stored) + [
        {'role': 'assistant', 'tool_calls': [{'id': 'history', 'function': {
            'name': 'get_training_evidence', 'arguments': json.dumps({'definition_ids': ['LIBRARY_0']})}}]},
        {'role': 'tool', 'tool_call_id': 'history', 'content': json.dumps(evidence)}]
    draft['workouts'][0]['exercises'][0]['requiresEffortCalibration'] = True
    result = json.loads(handle_function_call(None, messages, 'audit_workout_plan', draft, equipment,
                                           training_history=history)['result'])
    assert result['passed']
    reviewer_context = _context(result, messages, equipment, history, len(messages) - 3)
    assert reviewer_context['history']['HISTORY_0']['sessions'][0]['performances'][0]['record']['actualReps'] == 12
    outgoing = _messages_for_api(messages, True, history, equipment)
    state = json.loads(next(m['content'].split('\n', 1)[1] for m in outgoing
                            if m.get('content', '').startswith('Current planning state')))
    assert state['trainingEvidence']['HISTORY_0']['sessions'][0]['performances'][0]['record']['actualReps'] == 12
    assert 'HISTORY_0' not in state['exerciseCandidates']


def test_changing_variant_requires_its_evidence_before_a_fixed_load_can_pass(monkeypatch):
    from workout_generator_pkg.planning_tools import audit_workout_plan
    equipment, stored, draft, backup = history_case()
    equipment['equipments'] = [{'id': 'EQUIPMENT_0', 'type': 'WEIGHTVEST', 'name': 'Vest',
                                'availableWeights': [{'weight': value} for value in range(1, 21)]}]
    equipment['exerciseDefinitions'].append({**equipment['exerciseDefinitions'][0],
        'id': 'z-weighted', 'name': 'Weighted Push-Up', 'equipmentId': 'EQUIPMENT_0'})
    history = TrainingHistory(backup)
    messages = requirement_messages(stored)
    def add_evidence(arguments, key, client=None):
        payload = history.evidence(arguments, equipment, client=client)
        messages.extend([{'role': 'assistant', 'tool_calls': [{'id': key, 'function': {
            'name': 'get_training_evidence', 'arguments': json.dumps(arguments)}}]},
            {'role': 'tool', 'tool_call_id': key, 'content': json.dumps(payload)}])
    add_evidence({'definition_ids': ['LIBRARY_0']}, 'original-evidence')
    first = audit_workout_plan(draft, equipment, messages, training_history=history)
    assert first['passed']
    messages.extend([{'role': 'assistant', 'tool_calls': [{'id': 'audit', 'function': {
        'name': 'audit_workout_plan', 'arguments': json.dumps(draft)}}]},
        {'role': 'tool', 'tool_call_id': 'audit', 'content': json.dumps(first)}])
    patch = {'requirementsId': draft['requirementsId'], 'baseDraftId': first['currentDraftId'], 'patch': [
        {'op': 'replace', 'path': '/workouts/0/exercises/0/definition_id', 'value': 'LIBRARY_1'},
        {'op': 'add', 'path': '/workouts/0/exercises/0/targetSetPrescriptions', 'value': [
            {'workSetIndex': i, 'reps': 8, 'additionalWeight': 18} for i in range(5)]}]}
    blocked = audit_workout_plan(patch, equipment, messages, training_history=history)
    assert any(error['code'] == 'training_evidence_required' and error['definition_ids'] == ['LIBRARY_1'] for error in blocked['errors'])
    monkeypatch.setattr('workout_generator_pkg.exercise_library_tools._semantic_matches',
                        lambda client, queries, entries: [{0: .95} for _ in queries])
    add_evidence({'definition_ids': ['LIBRARY_1']}, 'variant-evidence', client=object())
    blocked = audit_workout_plan(patch, equipment, messages, training_history=history)
    assert any(error['code'] == 'training_load_suitability_unresolved' for error in blocked['errors'])
    patch['patch'] = [patch['patch'][0], {'op': 'add', 'path': '/workouts/0/exercises/0/requiresEffortCalibration', 'value': True}]
    calibrated = audit_workout_plan(patch, equipment, messages, training_history=history)
    assert calibrated['passed'] and 'conditional' in calibrated['preview']


def test_capacity_mismatch_blocks_preview_until_explicit_effort_calibration():
    import pytest
    from workout_generator_pkg.planning_tools import build_draft_plan, PlanningInputError
    equipment, stored, draft, backup = history_case()
    backup['SetHistories'][0]['setData']['additionalWeight'] = 18
    history = TrainingHistory(backup)
    result = history.evidence({'definition_ids': ['LIBRARY_0']}, equipment)
    assert result['exercises'][0]['loadSuitabilityConcerns'][0]['recordedLoadKg'] == 18
    messages = requirement_messages(stored) + [
        {'role': 'assistant', 'tool_calls': [{'id': 'history', 'function': {'name': 'get_training_evidence'}}]},
        {'role': 'tool', 'tool_call_id': 'history', 'content': json.dumps(result)}]
    def audit():
        return handle_function_call(None, messages, 'audit_workout_plan', draft,
                                    provided_equipment=equipment, training_history=history)
    blocked = audit()
    payload = json.loads(blocked['result'])
    assert payload['passed'] is False and blocked.get('draft_preview') is None
    assert payload['errors'][0]['code'] == 'training_load_suitability_unresolved'
    assert payload['errors'][0]['path'] == '/workouts/0/exercises/0'
    exercise = draft['workouts'][0]['exercises'][0]
    exercise['placementNotes'] = 'Use slower tempo and more sets.'
    assert json.loads(audit()['result'])['passed'] is False
    exercise['requiresEffortCalibration'] = True
    passed = json.loads(audit()['result'])
    assert passed['passed'] and 'Effort verification pending' in passed['preview']
    assert 'Calibration attempts are additional to working sets' in passed['preview']
    assert passed['audit']['workouts'][0]['timing']['calibrationSeconds'] == 30
    exercise['targetSetPrescriptions'] = [{'workSetIndex': i, 'reps': 10, 'additionalWeight': 0} for i in range(5)]
    with pytest.raises(PlanningInputError, match='fixed work-set loads'):
        build_draft_plan(draft, equipment, stored['requirements'])


def test_audit_requires_current_evidence_and_api_context_is_compact():
    equipment, stored, draft, backup = history_case()
    history = TrainingHistory(backup)
    messages = requirement_messages(stored)
    def call(name, arguments):
        return handle_function_call(None, messages, name, arguments, provided_equipment=equipment, training_history=history)
    blocked = json.loads(call('audit_workout_plan', draft)['result'])
    assert not blocked['passed']
    assert blocked['errors'][0]['definition_ids'] == ['LIBRARY_0']
    assert blocked['draftId'] and 'preview' not in blocked
    evidence = call('get_training_evidence', {'definition_ids': ['LIBRARY_0']})
    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': 'history', 'function': {'name': 'get_training_evidence'}}]},
        {'role': 'tool', 'tool_call_id': 'history', 'content': evidence['result']}])
    approved = json.loads(call('audit_workout_plan', draft)['result'])
    assert approved['passed']
    assert approved['historyFingerprint'] == history.fingerprint
    assert 'Training history snapshot:' in approved['preview']
    assert history.unreviewed(approved['planIndex'], messages, equipment) == []
    context = _messages_for_api([], True, history)
    assert 'get_training_evidence' in context[-1]['content']
    assert 'setHistoryId' not in context[-1]['content']
    changed = copy.deepcopy(backup)
    changed['SetHistories'][0]['setData']['actualReps'] = 13
    newer = TrainingHistory(changed)
    assert newer.unreviewed(approved['planIndex'], messages, equipment) == ['LIBRARY_0']
    outgoing = _messages_for_api(messages, True, newer)
    assert any('staleHistory' in message.get('content', '') for message in outgoing)

def test_cli_backup_supplies_library_and_history_then_exports(monkeypatch, tmp_path):
    from test_workout_generator_conversation_sessions import make_shell_deps, FakeToolCall, FakeFunction
    from workout_generator_pkg import interactive_shell
    from workout_generator_pkg.conversation_store import load_active_conversation_record
    equipment, stored, draft, backup = history_case()
    _, requirements, _, _ = planning_case()
    path = tmp_path / 'backup.json'
    path.write_text(json.dumps(backup), encoding='utf-8')
    def tool(name, arguments, identifier):
        return (None, [FakeToolCall(identifier, 'function', FakeFunction(name, json.dumps(arguments)))])
    calls = []
    deps = make_shell_deps(tmp_path, chat_results=[
        tool('set_workout_requirements', requirements, 'requirements'),
        tool('audit_workout_plan', draft, 'blocked'),
        tool('get_training_evidence', {'definition_ids': ['LIBRARY_0']}, 'evidence'),
        tool('generate_workout', {}, 'generate'),
    ], generation_results=[{'success': True, 'filepath': 'generated.json', 'error': None}], generation_calls=calls)
    inputs = iter(['Create my workout', 'CONFIRM REQUIREMENTS', 'CONFIRM GENERATE', '/exit'])
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test-key')
    monkeypatch.setattr('builtins.input', lambda prompt='': next(inputs))
    monkeypatch.setattr('sys.argv', ['workout_generator.py', '--history-backup-file', str(path), '--hybrid-fast'])
    interactive_shell.main(deps=deps)
    assert len(calls) == 1
    messages = load_active_conversation_record(str(tmp_path))['messages']
    results = {message.get('tool_call_id'): json.loads(message['content']) for message in messages
               if message.get('tool_call_id') == 'blocked' or message.get('tool_call_id', '').startswith('reaudit_')}
    assert results['blocked']['errors'][0]['code'] == 'training_evidence_required'
    approved = [result for key, result in results.items() if key.startswith('reaudit_')]
    assert len(approved) == 1 and approved[0]['passed']
    assert approved[0]['historyFingerprint'] == TrainingHistory(backup).fingerprint

def test_pair_load_headroom_uses_current_equipment_and_invalidates_cache():
    equipment, _, _, backup = history_case()
    gear = {'id': 'pair', 'type': 'DUMBBELLS', 'name': 'Pair', 'dumbbells': [{'weight': 10}, {'weight': 12}]}
    equipment['equipments'] = [gear]
    definition = equipment['exerciseDefinitions'][0]
    definition.update(exerciseType='WEIGHT', equipmentId='pair')
    backup['WorkoutStore']['exerciseDefinitions'] = copy.deepcopy(equipment['exerciseDefinitions'])
    occurrence = backup['WorkoutStore']['workouts'][0]['workoutComponents'][0]
    occurrence.update(exerciseType='WEIGHT', equipmentId='pair')
    backup['SetHistories'][0]['setData'] = {'type': 'WeightSetData', 'actualReps': 10, 'actualWeight': 20}
    history = TrainingHistory(backup)
    arguments = {'definition_ids': ['LIBRARY_0']}
    evidence = history.evidence(arguments, equipment)
    assert evidence['equipmentLoadOptions']['pair']['selectableLoadsKg'] == [20, 24]
    assert evidence['equipmentLoadOptions']['pair']['loadConvention'] == 'pair_total'
    headroom = evidence['exercises'][0]['loadHeadroom']
    assert headroom['nextHigherSelectableLoadKg'] == 24
    assert headroom['higherLoadOptionCount'] == 1
    equipment['equipments'][0]['dumbbells'] = [{'weight': 10}]
    headroom = history.evidence(arguments, equipment)['exercises'][0]['loadHeadroom']
    assert headroom['observedAtCurrentEquipmentMaximum']
    assert headroom['higherLoadOptionCount'] == 0


def test_timers_follow_app_countup_and_countdown_semantics():
    def read(kind, start, end):
        return TrainingHistory._set_record({'id': 'timer', 'setData': {
            'type': kind, 'startTimer': start, 'endTimer': end, 'hasBeenExecuted': True}})
    assert read('EnduranceSetData', 60000, 52010)['actualDurationSeconds'] == 52.01
    assert read('EnduranceSetData', 60000, 60000)['actualDurationSeconds'] == 60
    assert read('EnduranceSetData', 60000, 75000)['actualDurationSeconds'] == 75
    assert read('TimedDurationSetData', 60000, 7989)['actualDurationSeconds'] == 52.011
    assert read('TimedDurationSetData', 60000, 0)['actualDurationSeconds'] == 60
    assert read('EnduranceSetData', 60000, 0) is None
    assert read('TimedDurationSetData', 60000, 60000) is None
    assert read('TimedDurationSetData', 60000, 75000) is None


def test_app_effort_fields_survive_tool_retrieval_without_conflation():
    equipment, _, _, backup = history_case()
    data = backup['SetHistories'][0]['setData']
    data.update(autoRegulationRIR=2, calibrationRIR=4)
    calibration = copy.deepcopy(backup['SetHistories'][0])
    calibration['id'] = 'calibration-only'
    calibration['setData']['subCategory'] = 'CalibrationSet'
    backup['SetHistories'].append(calibration)
    history = TrainingHistory(backup)
    performances = history.evidence({'definition_ids': ['LIBRARY_0']}, equipment)['exercises'][0]['sessions'][0]['performances']
    assert len(performances) == 1
    record = performances[0]['record']
    assert record['autoRegulationRIR'] == 2
    assert record['calibrationRIR'] == 4
    assert 'rir' not in record
    weighted = TrainingHistory._set_record({'id': 'weighted', 'setData': {
        'type': 'WeightSetData', 'actualReps': 8, 'actualWeight': 50, 'autoRegulationRIR': 0, 'calibrationRIR': None}})
    assert weighted['autoRegulationRIR'] == 0
    assert 'calibrationRIR' not in weighted


@pytest.mark.parametrize('evidence_version', [None, 4, 5])
def test_pre_fix_saved_evidence_is_invalidated(evidence_version):
    import hashlib
    equipment, stored, draft, backup = history_case()
    history = TrainingHistory(backup)
    evidence = history.evidence({'definition_ids': ['LIBRARY_0']}, equipment)
    fingerprint_input = {'evidenceVersion': evidence_version, 'backup': backup} if evidence_version else backup
    evidence['historyFingerprint'] = hashlib.sha256(json.dumps(fingerprint_input, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    messages = requirement_messages(stored) + [
        {'role': 'assistant', 'tool_calls': [{'id': 'old', 'function': {'name': 'get_training_evidence'}}]},
        {'role': 'tool', 'tool_call_id': 'old', 'content': json.dumps(evidence)}]
    assert history.unreviewed({'exercises': [{'libraryDefinitionId': 'press'}]}, messages, equipment) == ['LIBRARY_0']
    outgoing = _messages_for_api(messages, True, history)
    assert any('staleHistory' in message.get('content', '') for message in outgoing)


def test_history_lookup_after_eighth_round_can_finish_without_rewriting_requirements(monkeypatch, tmp_path):
    from test_workout_generator_conversation_sessions import make_shell_deps, FakeToolCall, FakeFunction
    from workout_generator_pkg import interactive_shell
    from workout_generator_pkg.conversation_store import load_active_conversation_record
    equipment, _, draft, backup = history_case()
    _, requirements, _, _ = planning_case()
    for index in range(7):
        backup['WorkoutStore']['exerciseDefinitions'].append({
            **copy.deepcopy(equipment['exerciseDefinitions'][0]), 'id': f'z{index}', 'name': f'Alternative {index}'})
    path = tmp_path / 'backup.json'
    path.write_text(json.dumps(backup), encoding='utf-8')
    def tool(name, args, identifier):
        return (None, [FakeToolCall(identifier, 'function', FakeFunction(name, json.dumps(args)))])
    generated = []
    deps = make_shell_deps(tmp_path, chat_results=[
        tool('set_workout_requirements', requirements, 'requirements'),
        *[tool('get_training_evidence', {'definition_ids': [f'LIBRARY_{index}']}, f'alternative-{index}') for index in range(1, 8)],
        tool('audit_workout_plan', draft, 'missing-evidence'),
        tool('get_training_evidence', {'definition_ids': ['LIBRARY_0']}, 'selected-evidence'),
        tool('generate_workout', {}, 'export')],
        generation_results=[{'success': True, 'filepath': 'generated.json', 'error': None}], generation_calls=generated)
    inputs = iter(['Create my workout', 'CONFIRM REQUIREMENTS', 'CONFIRM GENERATE', '/exit'])
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test-key')
    monkeypatch.setattr('builtins.input', lambda prompt='': next(inputs))
    monkeypatch.setattr('sys.argv', ['workout_generator.py', '--history-backup-file', str(path)])
    interactive_shell.main(deps=deps)
    assert len(generated) == 1
    messages = load_active_conversation_record(str(tmp_path))['messages']
    feedback = {m['tool_call_id']: json.loads(m['content']) for m in messages if m.get('tool_call_id') == 'missing-evidence' or m.get('tool_call_id', '').startswith('reaudit_')}
    assert feedback['missing-evidence']['errors'][0]['code'] == 'training_evidence_required'
    automatic = [result for key, result in feedback.items() if key.startswith('reaudit_')]
    assert len(automatic) == 1 and automatic[0]['passed']


def test_numerical_and_history_errors_are_returned_together_without_review(monkeypatch):
    equipment, stored, draft, backup = history_case()
    history = TrainingHistory(backup)
    draft['workouts'][0]['exercises'][0]['numWorkSets'] = 1
    monkeypatch.setattr('workout_generator_pkg.plan_review.chat_call', lambda *a, **k: pytest.fail('Invalid draft must not invoke reviewer'))
    result = handle_function_call(None, requirement_messages(stored), 'audit_workout_plan', draft,
                                  provided_equipment=equipment, training_history=history)
    payload = json.loads(result['result'])
    codes = {e['code'] for e in payload['errors']}
    assert 'training_evidence_required' in codes
    assert any('volume' in code for code in codes)
    assert not payload['passed'] and result['draft_preview'] is None
