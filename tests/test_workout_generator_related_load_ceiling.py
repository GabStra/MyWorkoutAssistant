import copy

from workout_generator_pkg.training_history import TrainingHistory
from workout_generator_pkg.session_drafting import _history_configuration_concerns


def case(monkeypatch, *, reviewed=True, exact=False):
    definitions = [{'id': identifier, 'name': identifier, 'exerciseType': 'WEIGHT'}
        for identifier in ('candidate', 'historical')]
    equipment = {'exerciseDefinitions': definitions}
    history = TrainingHistory({'WorkoutStore': {'exerciseDefinitions': [], 'workouts': []},
        'WorkoutHistories': [], 'SetHistories': []})
    history.sessions['historical'] = [True]
    candidate = {'reference': 'LIBRARY_0', 'definitionId': 'candidate', 'totalSessions': int(exact),
        'sessions': [], 'candidateContext': {'exerciseType': 'WEIGHT'},
        'loadHeadroom': {'maximumSelectableLoadKg': 50, 'latestSessionHeaviestLoadKg': 20 if exact else None}}
    historical = {'reference': 'LIBRARY_1', 'definitionId': 'historical', 'totalSessions': 1,
        'sessions': [{'date': '2026-07-11', 'performances': [{'record': {'loadKg': 88.5, 'actualReps': 9}}]}],
        'candidateContext': {'exerciseType': 'WEIGHT'},
        'loadHeadroom': {'maximumSelectableLoadKg': 111, 'latestSessionHeaviestLoadKg': 88.5}}
    items = {'LIBRARY_0': candidate, 'LIBRARY_1': historical}
    monkeypatch.setattr(history, '_exact_evidence', lambda args, gear: {
        'exercises': [copy.deepcopy(items[ref]) for ref in args['definition_ids']]})
    monkeypatch.setattr('workout_generator_pkg.recipe_contracts.reviewed_exercise_family_evidence',
        lambda gear: {'familyByReference': {ref: 'family' for ref in items} if reviewed else {},
            'sourcesByReference': {ref: {'source': 'reviewed-source', 'basis': 'identity only'} for ref in items}})
    return history, equipment


def test_reviewed_related_ceiling_reaches_selection_and_cannot_be_calibrated_away(monkeypatch):
    history, equipment = case(monkeypatch)
    item = history.evidence({'definition_ids': ['LIBRARY_0']}, equipment)['exercises'][0]
    assert item['totalSessions'] == 0 and item['loadHeadroom']['latestSessionHeaviestLoadKg'] is None
    concern = next(c for c in item['loadSuitabilityConcerns']
        if c['code'] == 'related_history_ceiling_requires_reassessment')
    assert concern['maximumSelectableLoadKg'] == 50
    assert concern['relatedEvidence'][0]['definitionId'] == 'historical'
    sessions = [{'exercises': [{'definition_id': 'LIBRARY_0'}]}]
    assert 'LIBRARY_0' in _history_configuration_concerns(sessions, equipment, history)
    plan = {'exercises': [{'id': 'EXERCISE_0', 'libraryDefinitionId': 'candidate',
        'exerciseType': 'WEIGHT', 'requiresLoadCalibration': True}],
        'workouts': [{'exerciseIds': ['EXERCISE_0']}]}
    validator = history.load_suitability_validator([], equipment)
    for reps in (6, 12):
        plan['exercises'][0]['maxReps'] = reps
        error = validator(plan)[0]
        assert error['repairStage'] == 'candidate_reassessment'


def test_unreviewed_relationship_and_exact_history_do_not_infer_a_ceiling_conflict(monkeypatch):
    for options in ({'reviewed': False}, {'exact': True}):
        history, equipment = case(monkeypatch, **options)
        item = history.evidence({'definition_ids': ['LIBRARY_0']}, equipment)['exercises'][0]
        assert not any(c['code'] == 'related_history_ceiling_requires_reassessment'
            for c in item['loadSuitabilityConcerns'])
