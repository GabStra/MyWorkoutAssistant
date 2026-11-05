import copy

import pytest

from workout_generator_pkg.training_history import TrainingHistory


def historical_case(monkeypatch, *, family='reviewed-family', exact=False):
    candidate = {'id': 'candidate', 'name': 'Selected movement', 'exerciseType': 'WEIGHT',
        'equipmentId': 'bar', 'requiredAccessoryEquipmentIds': [], 'exerciseFamilyId': 'raw-family'}
    historical = {**candidate, 'id': 'z-historical', 'name': 'Stored movement', 'equipmentId': 'old-bar'}
    unknown = {**historical, 'id': 'a-unknown', 'name': candidate['name']}
    equipment = {'exerciseDefinitions': [candidate], 'equipments': [
        {'id': identifier, 'name': identifier, 'type': 'BARBELL', 'barWeight': weight, 'availablePlates': []}
        for identifier, weight in (('bar', 50), ('old-bar', 111))]}
    history = TrainingHistory({'WorkoutStore': {'exerciseDefinitions': [], 'workouts': []},
        'WorkoutHistories': [], 'SetHistories': []})
    history.definitions = {definition['id']: copy.deepcopy(definition) for definition in (unknown, historical, candidate)}
    for definition in (unknown, historical, candidate) if exact else (unknown, historical):
        history.sessions[definition['id']] = [{'sessionId': definition['id'] + '-session', 'date': '2026-06-13',
            'performances': [{'equipmentId': definition['equipmentId'], 'exerciseType': 'WEIGHT',
                'requiredAccessoryEquipmentIds': [],
                'equipmentContext': {'type': 'BARBELL', 'name': definition['equipmentId'], 'source': 'set_snapshot'},
                'record': {'loadKg': 20 if definition['id'] == 'candidate' else 99, 'actualReps': 27}}]}]
    annotations = {'candidate': {'exerciseFamilyId': 'reviewed-family',
        'source': 'https://example.com/candidate', 'basis': 'Reviewed movement identity only.'}}
    if family:
        annotations[historical['id']] = {'exerciseFamilyId': family,
            'source': 'https://example.com/historical', 'basis': 'Reviewed movement identity only.'}
    monkeypatch.setattr('workout_generator_pkg.recipe_contracts._reviewed_exercise_annotations_by_definition',
        lambda: annotations)
    return history, equipment


def test_historical_reviewed_family_reaches_shared_selection_and_final_ceiling_checks(monkeypatch):
    from workout_generator_pkg.session_drafting import _history_configuration_concerns

    history, equipment = historical_case(monkeypatch)
    item = history.evidence({'definition_ids': ['LIBRARY_0']}, equipment)['exercises'][0]
    assert item['totalSessions'] == 0 and item['sessions'] == []
    assert item['loadHeadroom']['latestSessionHeaviestLoadKg'] is None
    assert len(item['relatedMovementHistory']) == 1
    related = item['relatedMovementHistory'][0]
    assert related['definitionId'] == 'z-historical' and related['reference'] == 'HISTORY_1'
    assert related['matchType'] == 'reviewed_family_not_equivalent'
    assert related['sessions'] == history.sessions['z-historical']
    assert related['familyEvidence']['historical']['source'] == 'https://example.com/historical'
    selection = _history_configuration_concerns(
        [{'exercises': [{'definition_id': 'LIBRARY_0'}]}], equipment, history)
    concern = next(concern for concern in selection['LIBRARY_0']
        if concern['code'] == 'related_history_ceiling_requires_reassessment')
    assert concern['maximumSelectableLoadKg'] == 50
    assert concern['relatedEvidence'][0]['definitionId'] == 'z-historical'
    plan = {'exercises': [{'id': 'EXERCISE_0', 'libraryDefinitionId': 'candidate',
        'exerciseType': 'WEIGHT', 'requiresLoadCalibration': True}],
        'workouts': [{'exerciseIds': ['EXERCISE_0']}]}
    assert history.load_suitability_errors(plan, [], equipment)[0]['repairStage'] == 'candidate_reassessment'


@pytest.mark.parametrize('family', [None, 'unrelated-reviewed-family'])
def test_unknown_or_unrelated_historical_identity_does_not_infer_family_from_name_or_raw_id(monkeypatch, family):
    history, equipment = historical_case(monkeypatch, family=family)
    item = history.evidence({'definition_ids': ['LIBRARY_0']}, equipment)['exercises'][0]
    assert not item['relatedMovementHistory']
    assert not item['loadSuitabilityConcerns']


def test_exact_usable_history_stays_allowed_without_related_strength_transfer(monkeypatch):
    history, equipment = historical_case(monkeypatch, exact=True)
    item = history.evidence({'definition_ids': ['LIBRARY_0']}, equipment)['exercises'][0]
    assert item['status'] == 'comparable_records' and item['totalSessions'] == 1
    assert item['loadHeadroom']['latestSessionHeaviestLoadKg'] == 20
    assert not item.get('relatedMovementHistory')
    assert not item['loadSuitabilityConcerns']


def test_refresh_upgrades_retained_historical_family_without_rewriting_pages_or_duplicates(monkeypatch):
    from workout_generator_pkg.planning_tools import library_fingerprint

    history, equipment = historical_case(monkeypatch)
    payload = history._exact_evidence({'definition_ids': ['LIBRARY_0']}, equipment)
    historical_equipment = {**equipment, 'exerciseDefinitions': [history.definitions[key] for key in history.sessions]}
    related = history._exact_evidence({'definition_ids': ['LIBRARY_1']}, historical_equipment)['exercises'][0]
    related.update(reference='HISTORY_1', matchType='related_not_equivalent', relevanceScore=.9,
        sessionOffset=8, hasMore=True, nextOffset=9,
        differences={'equipmentId': {'candidate': 'bar', 'historical': 'old-bar'}})
    payload['exercises'][0]['relatedMovementHistory'] = [related]
    before = copy.deepcopy(payload)
    assert payload['libraryFingerprint'] == library_fingerprint(equipment)

    refreshed = history.refresh_evidence_metadata(payload, equipment)

    assert payload == before
    retained = refreshed['exercises'][0]['relatedMovementHistory']
    assert len(retained) == 1 and retained[0]['reference'] == 'HISTORY_1'
    for key in ('definitionId', 'sessions', 'otherSetupSessions', 'candidateContext', 'sessionOffset',
                'hasMore', 'nextOffset', 'relevanceScore', 'differences'):
        assert retained[0][key] == before['exercises'][0]['relatedMovementHistory'][0][key]
    assert retained[0]['matchType'] == 'reviewed_family_not_equivalent'
    assert any(concern['code'] == 'related_history_ceiling_requires_reassessment'
        for concern in refreshed['exercises'][0]['loadSuitabilityConcerns'])
