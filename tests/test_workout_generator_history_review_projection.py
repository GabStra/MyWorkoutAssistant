import copy
import json

import pytest

from workout_generator_pkg import plan_review as review
from workout_generator_pkg.planning_tools import audit_workout_plan, library_fingerprint
from test_workout_generator_planning_tools import planning_case, requirement_messages


def _session(identifier, date, load, reps=10):
    return {'sessionId': identifier, 'date': date, 'time': '12:00:00', 'endReason': 'COMPLETED',
        'performances': [{'order': 0, 'executionSequence': 0, 'equipmentId': 'implement',
            'exerciseType': 'WEIGHT', 'requiredAccessoryEquipmentIds': [],
            'equipmentContext': {'source': 'set_snapshot', 'type': 'DUMBBELLS'},
            'record': {'setHistoryId': identifier + '-set', 'setType': 'WeightSetData',
                'loadKg': load, 'loadMeaning': 'app_total_external_load',
                'actualReps': reps, 'autoRegulationRIR': 2}}]}


def _source(reference, identifier, name, load, score):
    return {'reference': reference, 'definitionId': identifier, 'name': name,
        'status': 'comparable_records', 'totalSessions': 31,
        'sessions': [_session(identifier + '-session', '2026-06-13', load, 27)],
        'otherSetupSessions': [], 'loadHeadroom': {'latestSessionHeaviestLoadKg': load},
        'matchType': 'related_not_equivalent', 'relevanceScore': score,
        'loadTransfer': review.RELATED_LOAD_TRANSFER_CAUTION}


def _case():
    equipment = {'exerciseDefinitions': [{'id': 'selected', 'name': 'Dumbbell Calf Raise',
        'exerciseType': 'WEIGHT', 'equipmentId': 'implement', 'requiredAccessoryEquipmentIds': []}],
        'equipments': [{'id': 'implement', 'type': 'DUMBBELLS', 'dumbbells': []}]}
    lateral = _source('HISTORY_0', 'lateral', 'Dumbbell Lateral Raise', 18, .795)
    single = _source('HISTORY_1', 'single', 'Single-Arm Dumbbell Lateral Raise', 9, .713)
    calf = _source('HISTORY_2', 'historical-calf', 'Barbell Calf Raise', 99, .5)
    calf.update(matchType='reviewed_family_not_equivalent', familyEvidence={
        'candidate': {'source': 'https://example.com/dumbbell', 'basis': 'Reviewed movement family.'},
        'historical': {'source': 'https://example.com/barbell', 'basis': 'Reviewed movement family.'}})
    item = {'reference': 'LIBRARY_0', 'definitionId': 'selected', 'name': 'Dumbbell Calf Raise',
        'status': 'no_comparable_records', 'totalSessions': 0, 'sessions': [], 'otherSetupSessions': [],
        'loadHeadroom': {'latestSessionHeaviestLoadKg': None, 'maximumSelectableLoadKg': 50},
        'loadSuitabilityConcerns': [], 'relatedMovementHistory': [lateral, single, calf]}
    return equipment, item


def _messages(equipment, *items):
    messages = []
    for index, item in enumerate(items):
        call = f'history-{index}'
        messages.extend([{'role': 'assistant', 'tool_calls': [
            {'id': call, 'function': {'name': 'get_training_evidence'}}]},
            {'role': 'tool', 'tool_call_id': call, 'content': json.dumps({
                'historyFingerprint': 'current', 'libraryFingerprint': library_fingerprint(equipment),
                'exercises': [item]})}])
    return messages


@pytest.mark.parametrize('with_loading_concern', [False, True])
def test_review_uses_reviewed_family_before_higher_semantic_score(with_loading_concern):
    equipment, item = _case()
    calf = item['relatedMovementHistory'][2]
    if with_loading_concern:
        item['loadSuitabilityConcerns'] = [{'code': 'related_history_ceiling_requires_reassessment',
            'maximumSelectableLoadKg': 50, 'relatedEvidence': [
                {key: calf[key] for key in ('reference', 'definitionId', 'familyEvidence', 'loadHeadroom')}]}]
    messages = _messages(equipment, item)
    before = copy.deepcopy(messages)

    selected = review._selected_review_evidence(messages, equipment, 'current', {'selected'})
    compact = review._compact_review_history(selected.values())

    assert compact['HISTORY_2']['sessions'][0]['performances'][0]['record']['loadKg'] == 99
    assert compact['HISTORY_2']['sessions'][0]['performances'][0]['record']['actualReps'] == 27
    assert compact['HISTORY_0']['historyDetailsOmitted'] and 'sessions' not in compact['HISTORY_0']
    assert compact['HISTORY_1']['historyDetailsOmitted'] and 'sessions' not in compact['HISTORY_1']
    links = {link['reference']: link for link in compact['LIBRARY_0']['relatedMovementHistory']}
    assert links['HISTORY_2']['matchType'] == 'reviewed_family_not_equivalent'
    assert links['HISTORY_2']['familyEvidence'] == calf['familyEvidence']
    assert links['HISTORY_0']['matchType'] == 'related_not_equivalent'
    assert links['HISTORY_0']['relevanceScore'] == .795
    assert 'familyEvidence' not in links['HISTORY_0']
    assert compact['LIBRARY_0']['loadSuitabilityConcerns'] == item['loadSuitabilityConcerns']
    assert selected['selected']['definitionId'] == 'selected'
    assert messages == before


def test_review_keeps_comparable_primary_history_and_explicit_source_claims():
    equipment, item = _case()
    item.update(status='comparable_records', totalSessions=1,
        sessions=[_session('latest', '2026-10-09', 40)])
    item['loadHeadroom']['latestSessionHeaviestLoadKg'] = 40
    messages = _messages(equipment, item)

    unused = review._selected_review_evidence(messages, equipment, 'current', {'selected'})['selected']
    assert unused['sessions'][0]['performances'][0]['record']['loadKg'] == 40
    assert all(source['historyDetailsOmitted'] for source in unused['relatedMovementHistory'])
    claimed = review._selected_review_evidence(messages, equipment, 'current', {'selected'},
        notes='Compare DUMBBELL LATERAL RAISE and HISTORY_2.')['selected']
    assert claimed['relatedMovementHistory'][0]['sessions']
    assert claimed['relatedMovementHistory'][2]['sessions']
    assert claimed['relatedMovementHistory'][1]['historyDetailsOmitted']
    assert claimed['sessions'] == unused['sessions']


def test_review_keeps_loading_concern_sources_even_when_not_top_ranked():
    equipment, item = _case()
    item['loadSuitabilityConcerns'] = [{'code': 'source_specific_loading_concern',
        'relatedEvidence': [{'definitionId': 'single'}]}]

    selected = review._selected_review_evidence(_messages(equipment, item), equipment, 'current', {'selected'})
    sources = selected['selected']['relatedMovementHistory']

    assert sources[1]['sessions'] and sources[2]['sessions']
    assert sources[0]['historyDetailsOmitted']


def test_final_review_context_retains_typed_claim_source_and_family_provenance():
    equipment, _, stored, draft = planning_case()
    draft['workouts'][0]['exercises'][0]['effortAcceptance']['acceptanceCriterion'] = (
        'Compare Barbell Calf Raise records before accepting this exercise.')
    messages = requirement_messages(stored)
    result = audit_workout_plan(draft, equipment, messages)
    _, item = _case()
    item.update(definitionId='press', name='Push-Up', status='comparable_records', totalSessions=1,
        sessions=[_session('latest', '2026-10-09', 40)])
    messages.extend(_messages(equipment, item))

    context = review._context(result, messages, equipment, 'current', len(messages) - 1)

    source = context['history']['HISTORY_2']
    assert source['sessions'][0]['performances'][0]['record']['loadKg'] == 99
    link = context['history']['LIBRARY_0']['relatedMovementHistory'][2]
    assert link['familyEvidence'] == item['relatedMovementHistory'][2]['familyEvidence']
    assert link['matchType'] == 'reviewed_family_not_equivalent'
    assert context['history']['HISTORY_0']['historyDetailsOmitted']


def test_review_merges_requested_pages_before_projecting_latest_session():
    equipment, item = _case()
    item.update(status='comparable_records', totalSessions=2,
        sessions=[_session('latest', '2026-10-09', 40)], relatedMovementHistory=[], sessionOffset=0)
    item['loadHeadroom']['latestSessionHeaviestLoadKg'] = 40
    older = copy.deepcopy(item)
    older.update(sessions=[_session('older', '2026-06-25', 30)], sessionOffset=1)
    messages = _messages(equipment, item, older)
    before = copy.deepcopy(messages)

    selected = review._selected_review_evidence(messages, equipment, 'current', {'selected'})['selected']

    assert selected['sessions'][0]['date'] == '2026-10-09'
    assert selected['sessions'][0]['performances'][0]['record']['loadKg'] == 40
    assert selected['loadHeadroom']['latestSessionHeaviestLoadKg'] == 40
    assert selected['totalSessions'] == 2
    assert messages == before
