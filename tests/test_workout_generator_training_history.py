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


def test_batch_load_validation_resolves_evidence_once_without_weakening_checks(monkeypatch):
    from workout_generator_pkg import training_history
    from workout_generator_pkg.planning_tools import build_draft_plan
    equipment, stored, draft, backup = history_case()
    history = TrainingHistory(backup)
    evidence = history._exact_evidence({'definition_ids': ['LIBRARY_0'], 'session_limit': 1}, equipment)
    messages = [{'role': 'assistant', 'tool_calls': [{'id': 'evidence', 'function': {'name': 'get_training_evidence'}}]},
                {'role': 'tool', 'tool_call_id': 'evidence', 'content': json.dumps(evidence)}]
    plan = build_draft_plan(draft, equipment, stored['requirements'])
    reads = []
    original = training_history.json.loads
    def read(value):
        reads.append(1)
        return original(value)
    monkeypatch.setattr(training_history.json, 'loads', read)
    monkeypatch.setattr(history, '_load_concerns', lambda item: [{'code': 'recorded_load_exceeds_current_capacity'}] if item else [])
    validate_plan = history.load_suitability_validator(messages, equipment)
    first = validate_plan(plan)
    assert first == [] and validate_plan(plan) == first and reads == [1]
    plan['exercises'][0]['exerciseType'] = 'WEIGHT'
    plan['exercises'][0]['requiresLoadCalibration'] = True
    assert validate_plan(plan) == [] and reads == [1]


def test_highest_comparable_load_uses_wider_history_without_treating_latest_as_maximum():
    equipment,_,_,backup=history_case()
    backup['WorkoutHistories'].append({'id':'older','workoutId':'version1','isDone':True,'date':'2026-09-01'})
    def record(identifier,load,reps=8,**extra):
        return {'id':identifier,'exerciseId':'occurrence','workoutHistoryId':'older',
            'setData':{'type':'BodyWeightSetData','actualReps':reps,'additionalWeight':load,
                       'relativeBodyWeightInKg':49,**extra}}
    backup['SetHistories'].extend([record('higher',10),record('warmup',100,subCategory='WarmupSet'),
        record('different',200,bodyWeightPercentageSnapshot=100),record('zero',300,reps=0)])
    history=TrainingHistory(backup)
    result=history.evidence({'definition_ids':['LIBRARY_0'],'session_limit':1},equipment)
    item=result['exercises'][0]
    assert len(item['sessions'])==1 and item['loadHeadroom']['latestSessionHeaviestLoadKg']==0
    assert item['loadHeadroom']['highestObservedComparableLoad']=={
        'loadKg':10,'date':'2026-09-01','reps':8,'endReason':None}
    legacy=copy.deepcopy(result)
    del legacy['exercises'][0]['loadHeadroom']['highestObservedComparableLoad']
    before=copy.deepcopy(legacy)
    refreshed=history.refresh_evidence_metadata(legacy,equipment)
    assert legacy==before
    assert refreshed['exercises'][0]['loadHeadroom']['highestObservedComparableLoad']['loadKg']==10
    legacy['historyFingerprint']='stale'
    assert history.refresh_evidence_metadata(legacy,equipment)==legacy


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


def test_native_load_calibration_uses_only_comparable_loaded_history_and_supported_types():
    from workout_generator_pkg.planning_tools import library_fingerprint
    from workout_generator_pkg.training_history import apply_native_load_calibration_policy

    equipment, _, _, _ = history_case()
    definition = equipment['exerciseDefinitions'][0]
    history_fingerprint = 'current-history'
    call_id = 'load-evidence'
    evidence = {'historyFingerprint': history_fingerprint,
        'libraryFingerprint': library_fingerprint(equipment),
        'exercises': [{'definitionId': definition['id'], 'status': 'comparable_records',
            'sessions': [{'performances': [{'record': {'setType': 'WeightSetData',
                'actualReps': 8, 'loadKg': 20}}]}]}]}
    messages = [
        {'role': 'assistant', 'tool_calls': [{'id': call_id, 'type': 'function',
            'function': {'name': 'get_training_evidence'}}]},
        {'role': 'tool', 'tool_call_id': call_id, 'content': json.dumps(evidence)},
    ]
    plan = {'exercises': [
        {'id': 'EXERCISE_0', 'libraryDefinitionId': definition['id'], 'exerciseType': 'WEIGHT', 'equipmentId': 'barbell'},
        {'id': 'EXERCISE_1', 'libraryDefinitionId': 'unrecorded', 'exerciseType': 'WEIGHT', 'equipmentId': 'barbell'},
        {'id': 'EXERCISE_2', 'libraryDefinitionId': 'bodyweight-loaded', 'exerciseType': 'BODY_WEIGHT', 'equipmentId': 'vest'},
        {'id': 'EXERCISE_3', 'libraryDefinitionId': 'bodyweight-fixed', 'exerciseType': 'BODY_WEIGHT', 'equipmentId': None},
        {'id': 'EXERCISE_4', 'libraryDefinitionId': 'timed', 'exerciseType': 'COUNTDOWN', 'equipmentId': None},
    ]}

    apply_native_load_calibration_policy(plan, messages, equipment, history_fingerprint)

    assert [item['requiresLoadCalibration'] for item in plan['exercises']] == [False, True, True, False, False]

    strict_plan = copy.deepcopy(plan)
    apply_native_load_calibration_policy(
        strict_plan, messages, equipment, history_fingerprint, allow_educated_load_guesses=False)
    assert [item['requiresLoadCalibration'] for item in strict_plan['exercises']] == [True, True, True, False, False]


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
    assert history.load_suitability_errors(plan, messages, equipment) == []
    plan['exercises'][0].update(exerciseType='WEIGHT', requiresLoadCalibration=True)
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


def test_changing_variant_uses_native_calibration_when_its_load_history_is_missing(monkeypatch):
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
    calibrated = audit_workout_plan(patch, equipment, messages, training_history=history)
    assert calibrated['passed']
    assert calibrated['planIndex']['exercises'][0]['requiresLoadCalibration'] is True


def test_historical_load_above_current_capacity_is_review_evidence_not_a_blocker():
    equipment, stored, draft, backup = history_case()
    backup['SetHistories'][0]['setData']['additionalWeight'] = 18
    history = TrainingHistory(backup)
    result = history.evidence({'definition_ids': ['LIBRARY_0']}, equipment)
    assert result['exercises'][0]['loadSuitabilityConcerns'][0]['recordedLoadKg'] == 18
    messages = requirement_messages(stored) + [
        {'role': 'assistant', 'tool_calls': [{'id': 'history', 'function': {'name': 'get_training_evidence'}}]},
        {'role': 'tool', 'tool_call_id': 'history', 'content': json.dumps(result)}]
    assert result['exercises'][0]['loadSuitabilityConcerns'][0]['code'] == 'recorded_load_exceeds_current_capacity'
    plan = draft
    assert history.load_suitability_errors(plan, messages, equipment) == []


def test_unresolved_historical_rep_suitability_routes_to_candidate_change_when_calibration_is_unsupported(monkeypatch):
    equipment, _, _, backup = history_case()
    history = TrainingHistory(backup)
    evidence = history.evidence({'definition_ids': ['LIBRARY_0']}, equipment)
    messages = [{'role': 'assistant', 'tool_calls': [{'id': 'history', 'function': {'name': 'get_training_evidence'}}]},
                {'role': 'tool', 'tool_call_id': 'history', 'content': json.dumps(evidence)}]
    monkeypatch.setattr(history, '_load_concerns', lambda item: [{'code': 'historical_reps_exceed_prescription'}])
    plan = {'workouts': [{'exerciseIds': ['EXERCISE_0']}], 'workingSetRIR': {'maximum': 0},
            'exercises': [{'id': 'EXERCISE_0', 'libraryDefinitionId': evidence['exercises'][0]['definitionId'],
                'name': 'Nordic Curl', 'exerciseType': 'BODY_WEIGHT', 'equipmentId': None,
                'maxReps': 8, 'targetSetPrescriptions': [{'reps': 8, 'additionalWeight': 0}]}]}

    errors = history.load_suitability_errors(plan, messages, equipment)

    assert len(errors) == 1
    assert errors[0]['code'] == 'training_load_suitability_unresolved'
    assert errors[0]['repairStage'] == 'candidate_reassessment'
    assert set(concern['code'] for concern in errors[0]['concerns']) == {'historical_reps_exceed_prescription'}


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


def test_bodyweight_equipment_evidence_keeps_load_meaning_snapshots_and_current_context():
    from workout_generator_pkg.training_history import compact_training_evidence
    from workout_generator_pkg.plan_review import _compact_evidence
    equipment, _, _, backup = history_case()
    vest = {'id': 'vest', 'type': 'WEIGHTVEST', 'name': 'Current vest', 'availableWeights': [{'weight': 10}, {'weight': 20}]}
    for store in (equipment, backup['WorkoutStore']):
        store['equipments'] = [copy.deepcopy(vest)]
        store['exerciseDefinitions'][0]['equipmentId'] = 'vest'
    equipment['weightKg'] = 80
    occurrence = backup['WorkoutStore']['workouts'][0]['workoutComponents'][0]
    occurrence['equipmentId'] = 'vest'
    record = backup['SetHistories'][0]
    record.update(equipmentIdSnapshot='vest', equipmentNameSnapshot='Vest at recording', equipmentTypeSnapshot='WEIGHTVEST')
    record['setData'].update(additionalWeight=10, bodyWeightPercentageSnapshot=65)
    history = TrainingHistory(backup)
    result = history.evidence({'definition_ids': ['LIBRARY_0']}, equipment)
    item = result['exercises'][0]
    assert item['loadHeadroom']['latestSessionHeaviestLoadKg'] == 10
    assert item['loadHeadroom']['maximumSelectableLoadKg'] == 20
    assert item['candidateContext']['effectiveBodyweightKg'] == 52
    assert item['candidateContext']['loadMeaning'] == 'additional_bodyweight_load'
    assert result['evidenceFormat']['recordedTotalResistanceKg']
    for projected in (item, compact_training_evidence([item])['LIBRARY_0'], _compact_evidence(item)):
        performance = projected['sessions'][0]['performances'][0]
        assert performance['equipmentContext']['name'] == 'Vest at recording'
        assert performance['equipmentContext']['source'] == 'set_snapshot'
        assert performance['bodyWeightPercentageSource'] == 'set_snapshot'
        assert performance['record']['bodyWeightPercentageSnapshot'] == 65
        assert performance['record']['recordedRelativeBodyWeightKg'] == 49
        assert performance['record']['loadKg'] == 10
        assert performance['record']['recordedTotalResistanceKg'] == 59
        assert projected['candidateContext']['effectiveBodyweightKg'] == 52


@pytest.mark.parametrize('changed', ['equipment', 'percentage'])
def test_other_setup_records_remain_visible_but_do_not_set_current_load_headroom(changed):
    from workout_generator_pkg.training_history import compact_training_evidence
    from workout_generator_pkg.plan_review import _compact_evidence
    equipment, _, _, backup = history_case()
    record = backup['SetHistories'][0]
    if changed == 'equipment':
        record.update(equipmentIdSnapshot='historical-vest', equipmentNameSnapshot='Old vest', equipmentTypeSnapshot='WEIGHTVEST')
        record['setData']['additionalWeight'] = 18
    else:
        record['setData']['bodyWeightPercentageSnapshot'] = 100
    history = TrainingHistory(backup)
    item = history.evidence({'definition_ids': ['LIBRARY_0']}, equipment)['exercises'][0]
    assert not item['sessions'] and item['totalSessions'] == 0 and item['otherSetupSessionCount'] == 1
    assert item['loadHeadroom']['latestSessionHeaviestLoadKg'] is None
    assert any(concern['code'] == 'historical_setup_not_comparable' for concern in item['loadSuitabilityConcerns'])
    for projected in (item, compact_training_evidence([item])['LIBRARY_0'], _compact_evidence(item)):
        performance = projected['otherSetupSessions'][0]['performances'][0]
        assert performance['comparisonLimitations']
        assert performance['record']['actualReps'] == 12


@pytest.mark.parametrize('kind,exercise_type', [('TimedDurationSetData', 'COUNTDOWN'), ('EnduranceSetData', 'COUNTUP')])
def test_loaded_timers_keep_recorded_resistance_with_duration(kind, exercise_type):
    from workout_generator_pkg.training_history import compact_training_evidence
    from workout_generator_pkg.plan_review import _compact_evidence
    equipment, _, _, backup = history_case()
    vest = {'id': 'vest', 'type': 'WEIGHTVEST', 'name': 'Vest', 'availableWeights': [{'weight': 10}, {'weight': 20}]}
    for store in (equipment, backup['WorkoutStore']):
        store['equipments'] = [copy.deepcopy(vest)]
        store['exerciseDefinitions'][0].update(exerciseType=exercise_type, equipmentId='vest', bodyWeightPercentage=None)
    occurrence = backup['WorkoutStore']['workouts'][0]['workoutComponents'][0]
    occurrence.update(exerciseType=exercise_type, equipmentId='vest')
    backup['SetHistories'][0]['setData'] = {'type': kind, 'startTimer': 60000,
        'endTimer': 0 if exercise_type == 'COUNTDOWN' else 60000, 'actualWeight': 10, 'hasBeenExecuted': True,
        'autoStop': exercise_type == 'COUNTDOWN'}
    item = TrainingHistory(backup).evidence({'definition_ids': ['LIBRARY_0']}, equipment)['exercises'][0]
    assert item['loadHeadroom']['latestSessionHeaviestLoadKg'] == 10
    for projected in (item, compact_training_evidence([item])['LIBRARY_0'], _compact_evidence(item)):
        record = projected['sessions'][0]['performances'][0]['record']
        assert record['actualDurationSeconds'] == 60 and record['loadKg'] == 10
        assert record['configuredDurationSeconds'] == 60 and record['timerAutoStop'] == (exercise_type == 'COUNTDOWN')
        assert record['loadMeaning'] == 'app_total_external_load'


def test_running_evidence_uses_measured_results_once_and_omits_routes():
    equipment, _, _, backup = history_case()
    for store in (equipment, backup['WorkoutStore']):
        store['exerciseDefinitions'][0].update(exerciseType='RUNNING', bodyWeightPercentage=None)
    backup['WorkoutStore']['workouts'][0]['workoutComponents'][0]['exerciseType'] = 'RUNNING'
    backup['SetHistories'][0]['setData'] = {'type': 'RunningSetData', 'hasBeenExecuted': True}
    duplicate = copy.deepcopy(backup['SetHistories'][0])
    duplicate['id'] = 'duplicate-running-row'
    backup['SetHistories'].append(duplicate)
    backup['WorkoutHistories'][0]['runningResults'] = [{'exerciseId': 'occurrence', 'elapsedTimeMillis': 300000,
        'distanceMeters': 1000, 'averagePaceSecondsPerKilometer': 300, 'averageHeartRateBpm': 150,
        'minHeartRateBpm': None, 'maxHeartRateBpm': 170, 'route': [{'latitude': 45, 'longitude': 9}]}]
    item = TrainingHistory(backup).evidence({'definition_ids': ['LIBRARY_0']}, equipment)['exercises'][0]
    performances = item['sessions'][0]['performances']
    assert len(performances) == 1
    record = performances[0]['record']
    assert record['actualDurationSeconds'] == 300 and record['distanceMeters'] == 1000
    assert record['averagePaceSecondsPerKilometer'] == 300 and record['averageHeartRateBpm'] == 150
    assert 'latitude' not in json.dumps(item) and 'route' not in json.dumps(item)
    assert item['loadHeadroom']['loadMeaning'] == 'not_applicable'


def test_shared_recorded_context_survives_reprojection_for_session_workers():
    from workout_generator_pkg.training_history import pool_execution_contexts
    equipment = {'name': 'Recorded vest', 'type': 'WEIGHTVEST', 'source': 'set_snapshot',
                 'loadConvention': 'app_total'}
    execution = {'type': 'superset', 'members': [{'name': 'Long recorded exercise name', 'restAfterSeconds': 90}] * 6}
    catalog = {'LIBRARY_0': {'sessions': [{'performances': [
        {'equipmentContext': equipment, 'executionContext': execution, 'record': {'loadKg': 10}} for _ in range(5)]}]}}
    first, contexts = pool_execution_contexts(catalog)
    assert 'equipmentContextRef' in first['LIBRARY_0']['sessions'][0]['performances'][0]
    second, forwarded = pool_execution_contexts(first, contexts)
    for performance in second['LIBRARY_0']['sessions'][0]['performances']:
        assert forwarded[performance['equipmentContextRef']] == equipment
        assert forwarded[performance['executionContextRef']] == execution
    with pytest.raises(ValueError, match='no supplied context'):
        pool_execution_contexts(first)


@pytest.mark.parametrize('with_sequence', [False, True])
def test_history_set_order_is_numeric_and_prefers_recorded_execution_sequence(with_sequence):
    from workout_generator_pkg.training_history import compact_training_evidence
    from workout_generator_pkg.plan_review import _compact_evidence
    equipment, _, _, backup = history_case()
    source = backup['SetHistories'][0]
    backup['SetHistories'] = []
    for order in (10, 2):
        row = copy.deepcopy(source)
        row.update(id=f'set-{order}', order=order)
        if with_sequence:
            row['executionSequence'] = 1 if order == 10 else 2
        row['setData']['actualReps'] = order
        backup['SetHistories'].append(row)
    item = TrainingHistory(backup).evidence({'definition_ids': ['LIBRARY_0']}, equipment)['exercises'][0]
    expected = [10, 2] if with_sequence else [2, 10]
    for projected in (item, compact_training_evidence([item])['LIBRARY_0'], _compact_evidence(item)):
        performances = projected['sessions'][0]['performances']
        assert [p['record']['actualReps'] for p in performances] == expected
        if with_sequence:
            assert [p['executionSequence'] for p in performances] == [1, 2]


def test_changed_occurrence_accessories_are_not_exact_current_load_evidence():
    from workout_generator_pkg.training_history import compact_training_evidence
    from workout_generator_pkg.plan_review import _compact_evidence
    equipment, _, _, backup = history_case()
    equipment['accessoryEquipments'] = [{'id': 'current-rings', 'name': 'Current rings'}]
    equipment['exerciseDefinitions'][0]['requiredAccessoryEquipmentIds'] = ['current-rings']
    backup['WorkoutStore']['exerciseDefinitions'] = copy.deepcopy(equipment['exerciseDefinitions'])
    backup['WorkoutStore']['accessoryEquipments'] = [{'id': 'old-handles', 'name': 'Recorded handles'}]
    backup['WorkoutStore']['workouts'][0]['workoutComponents'][0]['requiredAccessoryEquipmentIds'] = ['old-handles']
    item = TrainingHistory(backup).evidence({'definition_ids': ['LIBRARY_0']}, equipment)['exercises'][0]
    assert item['loadHeadroom']['latestSessionHeaviestLoadKg'] is None
    assert item['otherSetupSessionCount'] == 1
    for projected in (item, compact_training_evidence([item])['LIBRARY_0'], _compact_evidence(item)):
        assert projected['candidateContext']['requiredAccessoryNames'] == ['Current rings']
        performance = projected['otherSetupSessions'][0]['performances'][0]
        assert performance['requiredAccessoryNames'] == ['Recorded handles']
        assert performance['comparisonLimitations'] == ['required_accessories_changed']
    assert 'requiredAccessoryEquipmentIds' not in compact_training_evidence([item])['LIBRARY_0']['otherSetupSessions'][0]['performances'][0]


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
    # Isolate error aggregation; automatic numerical repair has separate coverage.
    monkeypatch.setattr('workout_generator_pkg.interactive_shell.auto_allocate_workout', lambda result, *a, **k: result)
    monkeypatch.setattr('workout_generator_pkg.plan_review.chat_call', lambda *a, **k: pytest.fail('Invalid draft must not invoke reviewer'))
    result = handle_function_call(None, requirement_messages(stored), 'audit_workout_plan', draft,
                                  provided_equipment=equipment, training_history=history)
    payload = json.loads(result['result'])
    codes = {e['code'] for e in payload['errors']}
    assert 'training_evidence_required' in codes
    assert any('volume' in code for code in codes)
    assert not payload['passed'] and result['draft_preview'] is None
