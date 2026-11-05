import copy
import json

import pytest

from workout_generator_pkg.recipe_contracts import recorded_evidence
from workout_generator_pkg.training_history import (
    candidate_configuration_history, merge_training_evidence,
)


def page(offset, *, total=2):
    date, load = ('2026-07-11', 64) if offset == 0 else ('2026-06-25', 57.5)
    performance = {'exerciseId': 'bench-occurrence', 'equipmentId': 'bar',
        'equipmentContext': {'type': 'BARBELL', 'source': 'set_snapshot'},
        'exerciseType': 'WEIGHT', 'requiredAccessoryEquipmentIds': [], 'order': 0,
        'record': {'setHistoryId': f'set-{offset}', 'loadKg': load, 'actualReps': 8}}
    return {'reference': 'LIBRARY_158', 'definitionId': 'bench', 'name': 'Barbell Bench Press',
        'status': 'comparable_records', 'totalSessions': total, 'otherSetupSessionCount': 0,
        'sessions': [{'sessionId': f'session-{offset}', 'date': date,
            'workoutId': 'bench-workout', 'performances': [performance]}], 'otherSetupSessions': [],
        'sessionOffset': offset, 'hasMore': offset + 1 < total,
        'nextOffset': offset + 1 if offset + 1 < total else None,
        'loadHeadroom': {'latestSessionHeaviestLoadKg': 64, 'maximumSelectableLoadKg': 100},
        'candidateContext': {'exerciseType': 'WEIGHT', 'equipmentId': 'bar'}}


def receipt(messages, item, key):
    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': key,
            'function': {'name': 'get_training_evidence'}}]},
        {'role': 'tool', 'tool_call_id': key, 'content': json.dumps({
            'libraryFingerprint': 'library', 'historyFingerprint': 'history', 'exercises': [item]})},
    ])


@pytest.mark.parametrize('offsets', [(0, 1), (1, 0)])
def test_recorded_pages_keep_latest_and_older_original_records_in_either_retrieval_order(offsets):
    equipment = {'exerciseDefinitions': [{'id': 'bench', 'exerciseType': 'WEIGHT',
        'equipmentId': 'bar', 'requiredAccessoryEquipmentIds': []}],
        'equipments': [{'id': 'bar', 'type': 'BARBELL'}]}
    messages = []
    for offset in offsets:
        item = page(offset)
        item['candidateConfigurationHistory'] = candidate_configuration_history(
            item, equipment['exerciseDefinitions'][0], equipment)
        receipt(messages, item, str(offset))
    before = copy.deepcopy(messages)

    result = recorded_evidence(messages, 'library', 'history', equipment=equipment)['bench']

    assert [item['date'] for item in result['sessions']] == ['2026-07-11', '2026-06-25']
    assert [item['performances'][0]['record']['loadKg'] for item in result['sessions']] == [64, 57.5]
    assert result['sessions'] == [page(0)['sessions'][0], page(1)['sessions'][0]]
    assert result['loadHeadroom']['latestSessionHeaviestLoadKg'] == 64
    assert result['candidateConfigurationHistory']['sources'][0]['matchingConfigurationPerformanceCount'] == 2
    assert result['totalSessions'] == 2 and not result['hasMore'] and result['nextOffset'] is None
    assert messages == before


def test_overlapping_partial_session_pages_union_sets_and_keep_setup_and_related_identities_distinct():
    first, second = page(0, total=1), page(0, total=1)
    extra = copy.deepcopy(second['sessions'][0]['performances'][0])
    extra['record']['setHistoryId'] = 'second-working-set'
    extra['order'] = 1
    second['sessions'][0]['performances'].append(extra)
    other = copy.deepcopy(second['sessions'][0])
    other['performances'] = [copy.deepcopy(extra)]
    other['performances'][0]['record']['setHistoryId'] = 'other-setup-set'
    other['performances'][0]['comparisonLimitations'] = ['recorded_equipment_differs_or_is_unresolved']
    second['otherSetupSessions'] = [other]
    second['otherSetupSessionCount'] = 1
    first['relatedMovementHistory'] = [{**page(0, total=1),
        'definitionId': 'historical-original', 'reference': 'HISTORY_2'}]
    second['relatedMovementHistory'] = copy.deepcopy(first['relatedMovementHistory'])
    second['relatedMovementHistory'][0]['sessions'][0]['performances'].append(extra)
    before = copy.deepcopy((first, second))

    result = merge_training_evidence(first, second)
    repeated = merge_training_evidence(result, second)

    assert repeated == result
    assert [p['record']['setHistoryId'] for p in result['sessions'][0]['performances']] == [
        'set-0', 'second-working-set']
    assert len(result['otherSetupSessions'][0]['performances']) == 1
    related = result['relatedMovementHistory'][0]
    assert related['definitionId'] == 'historical-original' and related['reference'] == 'HISTORY_2'
    assert len(related['sessions'][0]['performances']) == 2
    assert (first, second) == before


@pytest.mark.parametrize('contradiction', ['record', 'session', 'setup', 'movement'])
def test_contradictory_immutable_history_is_rejected(contradiction):
    first, second = page(0, total=1), page(0, total=1)
    if contradiction == 'record':
        second['sessions'][0]['performances'][0]['record']['actualReps'] = 99
    elif contradiction == 'session':
        second['sessions'][0]['date'] = '2026-07-12'
    elif contradiction == 'setup':
        second['otherSetupSessions'] = second.pop('sessions')
    else:
        second['definitionId'] = 'different-original'
    with pytest.raises(ValueError):
        merge_training_evidence(first, second)


def test_noncontiguous_pages_do_not_report_missing_history_complete():
    latest, oldest = page(0, total=3), page(2, total=3)
    missing_middle = merge_training_evidence(latest, oldest)
    assert missing_middle['hasMore'] and missing_middle['nextOffset'] == 1
    oldest_only = merge_training_evidence(None, oldest)
    assert oldest_only['hasMore'] and oldest_only['nextOffset'] == 0
    complete = merge_training_evidence(missing_middle, page(1, total=3))
    assert len(complete['sessions']) == 3
    assert not complete['hasMore'] and complete['nextOffset'] is None


def test_planner_merges_before_compacting_the_explicit_reused_window():
    from workout_generator_pkg.interactive_shell import _messages_for_api
    from workout_generator_pkg.planning_tools import library_fingerprint
    from test_workout_generator_planning_tools import planning_case, requirement_messages
    from test_workout_generator_planner_context import _state, _tool

    equipment, _, stored, _ = planning_case()
    messages = requirement_messages(stored)
    for offset in (0, 1):
        item = page(offset)
        item['reference'] = 'LIBRARY_0'
        _tool(messages, 'get_training_evidence', {'definition_ids': ['LIBRARY_0'], 'session_offset': offset},
            {'libraryFingerprint': library_fingerprint(equipment), 'exercises': [item]}, f'page-{offset}')
    before = copy.deepcopy(messages)
    fresh = _state(_messages_for_api(messages, True, provided_equipment=equipment))
    assert [item['date'] for item in fresh['trainingEvidence']['LIBRARY_0']['sessions']] == [
        '2026-07-11', '2026-06-25']
    messages.append({'role': 'user', 'content': 'Resume the saved repair.'})
    reused = _state(_messages_for_api(messages, True, provided_equipment=equipment))
    retained = reused['trainingEvidence']['LIBRARY_0']
    assert [item['date'] for item in retained['sessions']] == ['2026-07-11']
    assert retained['earlierReturnedSessionsOmitted'] == 1
    assert retained['hasMore'] and retained['nextOffset'] == 1
    assert messages[:-1] == before


def test_related_ranking_filters_reviewed_family_conflicts_before_the_limit_and_on_refresh(monkeypatch):
    from workout_generator_pkg.training_history import TrainingHistory

    identifiers = ['a-wrong', 'b-wrong', 'c-wrong', 'd-unknown', 'e-family']
    definitions = [{'id': identifier, 'name': identifier, 'exerciseType': 'WEIGHT',
        'equipmentId': None, 'requiredAccessoryEquipmentIds': []} for identifier in identifiers]
    candidate = {**definitions[0], 'id': 'candidate', 'name': 'Candidate'}
    equipment = {'exerciseDefinitions': [candidate]}
    history = TrainingHistory({'WorkoutStore': {'exerciseDefinitions': definitions, 'workouts': [
        {'id': 'workout', 'workoutComponents': [
            {'id': identifier, 'type': 'Exercise', 'exerciseDefinitionId': identifier,
             'exerciseType': 'WEIGHT', 'equipmentId': None, 'requiredAccessoryEquipmentIds': []}
            for identifier in identifiers]}]},
        'WorkoutHistories': [{'id': 'session', 'workoutId': 'workout', 'date': '2026-07-11', 'isDone': True}],
        'SetHistories': [{'id': f'set-{identifier}', 'exerciseId': identifier, 'workoutHistoryId': 'session',
            'setData': {'type': 'WeightSetData', 'actualWeight': 30, 'actualReps': 8}}
            for identifier in identifiers]})
    family_by_id = {identifier: 'different-family' for identifier in identifiers[:3]}
    family_by_id.update(candidate='candidate-family', **{'e-family': 'candidate-family'})

    def reviewed_families(catalog):
        mapped = {f'LIBRARY_{index}': family_by_id[definition['id']]
            for index, definition in enumerate(sorted(catalog['exerciseDefinitions'], key=lambda item: item['id']))
            if definition['id'] in family_by_id}
        return {'familyByReference': mapped, 'sourcesByReference': {
            reference: {'source': f'https://reviewed.example/{family}', 'basis': 'Reviewed movement identity only'}
            for reference, family in mapped.items()}}

    monkeypatch.setattr('workout_generator_pkg.recipe_contracts.reviewed_exercise_family_evidence', reviewed_families)
    rankings = []

    def rank(*args):
        rankings.append(1)
        return [{0: .99, 1: .98, 2: .97, 3: .95, 4: .5}]

    monkeypatch.setattr('workout_generator_pkg.exercise_library_tools._semantic_matches', rank)
    arguments = {'definition_ids': ['LIBRARY_0']}
    fresh = history.evidence(arguments, equipment, client=object())
    related = fresh['exercises'][0]['relatedMovementHistory']
    assert [entry['definitionId'] for entry in related] == ['e-family', 'd-unknown']
    assert related[0]['matchType'] == 'reviewed_family_not_equivalent'
    assert related[0]['familyEvidence'] == {
        'candidate': {'source': 'https://reviewed.example/candidate-family', 'basis': 'Reviewed movement identity only'},
        'historical': {'source': 'https://reviewed.example/candidate-family', 'basis': 'Reviewed movement identity only'}}
    assert related[1]['matchType'] == 'related_not_equivalent' and related[1]['relevanceScore'] == .95
    assert 'familyEvidence' not in related[1]
    assert history.evidence(arguments, equipment, client=object()) == fresh
    assert rankings == [1]

    # Retained receipts were ranked before the reviewed contradiction filter existed.
    retained = copy.deepcopy(fresh)
    wrong = history._exact_evidence({'definition_ids': ['LIBRARY_0']}, {'exerciseDefinitions': definitions})['exercises'][0]
    wrong.update(reference='HISTORY_0', matchType='related_not_equivalent', relevanceScore=.99)
    retained['exercises'][0]['relatedMovementHistory'] = [wrong, related[1], related[0]]
    before = copy.deepcopy(retained)
    refreshed = history.refresh_evidence_metadata(retained, equipment)
    assert [entry['definitionId'] for entry in refreshed['exercises'][0]['relatedMovementHistory']] == [
        'e-family', 'd-unknown']
    assert retained == before and rankings == [1]
