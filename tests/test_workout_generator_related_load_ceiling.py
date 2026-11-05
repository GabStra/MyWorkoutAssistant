import copy

import pytest

from workout_generator_pkg.training_history import TrainingHistory, unverified_fixed_bodyweight_capability_concern
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


@pytest.mark.parametrize('exercise_type', ['COUNTUP_TIMER', 'COUNTDOWN_TIMER'])
def test_reviewed_timed_family_retains_duration_without_a_load_ceiling_inference(monkeypatch, exercise_type):
    history, equipment = case(monkeypatch)
    original = history._exact_evidence
    for definition in equipment['exerciseDefinitions']:
        definition['exerciseType'] = exercise_type

    def timed_evidence(arguments, gear):
        result = original(arguments, gear)
        for item in result['exercises']:
            item['candidateContext']['exerciseType'] = exercise_type
            for session in item['sessions']:
                session['performances'][0]['record'] = {'actualDurationSeconds': 600, 'loadKg': 88.5}
        return result

    monkeypatch.setattr(history, '_exact_evidence', timed_evidence)
    result = history.evidence({'definition_ids': ['LIBRARY_0']}, equipment)['exercises'][0]

    related = result['relatedMovementHistory'][0]
    assert related['matchType'] == 'reviewed_family_not_equivalent'
    assert related['sessions'][0]['performances'][0]['record'] == {'actualDurationSeconds': 600, 'loadKg': 88.5}
    assert [concern['code'] for concern in result['loadSuitabilityConcerns']] == ['related_history_only']
    assert not result['candidateConfigurationHistory']['currentCapabilityEstablished']


def test_unverified_fixed_bodyweight_capability_gates_without_transferring_family_load(monkeypatch):
    definitions = [
        {'id': 'a-candidate', 'name': 'Unweighted Variant', 'exerciseType': 'BODY_WEIGHT',
         'equipmentId': None},
        {'id': 'b-history', 'name': 'Loaded Variant', 'exerciseType': 'BODY_WEIGHT',
         'equipmentId': 'vest'},
    ]
    equipment = {'exerciseDefinitions': definitions,
        'equipments': [{'id': 'vest', 'name': 'Weight Vest', 'type': 'WEIGHTVEST'}]}
    history = TrainingHistory({'WorkoutStore': {'exerciseDefinitions': [], 'workouts': []},
        'WorkoutHistories': [], 'SetHistories': []})
    history.definitions['b-history'] = copy.deepcopy(definitions[1])
    history.sessions['b-history'] = [True]
    candidate = {'reference': 'LIBRARY_0', 'definitionId': 'a-candidate', 'totalSessions': 0,
        'sessions': [], 'candidateContext': {'exerciseType': 'BODY_WEIGHT'},
        'loadHeadroom': {'maximumSelectableLoadKg': 0, 'latestSessionHeaviestLoadKg': None}}
    historical = {'reference': 'LIBRARY_1', 'definitionId': 'b-history', 'totalSessions': 1,
        'sessions': [{'date': '2026-07-11', 'performances': [{'record': {'loadKg': 18, 'actualReps': 6}}]}],
        'candidateContext': {'exerciseType': 'BODY_WEIGHT'},
        'loadHeadroom': {'maximumSelectableLoadKg': 30, 'latestSessionHeaviestLoadKg': 18}}
    items = {'LIBRARY_0': candidate, 'LIBRARY_1': historical}
    monkeypatch.setattr(history, '_exact_evidence', lambda args, gear: {
        'exercises': [copy.deepcopy(items[ref]) for ref in args['definition_ids']]})
    monkeypatch.setattr('workout_generator_pkg.recipe_contracts.reviewed_exercise_family_evidence',
        lambda gear: {'familyByReference': {ref: 'family' for ref in items},
            'sourcesByReference': {ref: {'source': 'reviewed-source', 'basis': 'identity only'} for ref in items}})

    result = history.evidence({'definition_ids': ['LIBRARY_0']}, equipment)['exercises'][0]
    concerns = result['loadSuitabilityConcerns']

    assert [item['code'] for item in concerns] == ['related_history_only', 'unverified_fixed_bodyweight_capability']
    assert result['relatedMovementHistory'][0]['definitionId'] == 'b-history'
    assert result['relatedMovementHistory'][0]['matchType'] == 'reviewed_family_not_equivalent'
    assert result['relatedMovementHistory'][0]['sessions'] == historical['sessions']
    assert 'related_history_ceiling_requires_reassessment' not in {item['code'] for item in concerns}
    assert 'LIBRARY_0' in _history_configuration_concerns(
        [{'exercises': [{'definition_id': 'LIBRARY_0'}]}], equipment, history)
    items['LIBRARY_0']['totalSessions'] = 1
    items['LIBRARY_0']['sessions'] = [{'performances': [{'record': {'actualReps': 6}}]}]
    exact = history.evidence({'definition_ids': ['LIBRARY_0']}, equipment)['exercises'][0]
    assert not any(item['code'] == 'unverified_fixed_bodyweight_capability'
        for item in exact['loadSuitabilityConcerns'])


def test_unverified_fixed_bodyweight_capability_is_gated_without_history():
    equipment = {'exerciseDefinitions': [{'id': 'a-candidate', 'name': 'Unweighted Variant',
        'exerciseType': 'BODY_WEIGHT', 'equipmentId': None}]}

    concerns = _history_configuration_concerns(
        [{'exercises': [{'definition_id': 'LIBRARY_0'}]}], equipment, None)

    assert concerns['LIBRARY_0'][0]['code'] == 'unverified_fixed_bodyweight_capability'


def test_capability_evidence_helper_accepts_only_fixed_bodyweight_matching_records():
    fixed = {'exerciseType': 'BODY_WEIGHT', 'equipmentId': None}
    assert unverified_fixed_bodyweight_capability_concern(fixed) is not None
    assert unverified_fixed_bodyweight_capability_concern(fixed, {'totalSessions': 1}) is not None
    assert unverified_fixed_bodyweight_capability_concern(fixed,
        {'sessions': [{'performances': [{'record': {'actualReps': 6}}]}]}) is None
    assert unverified_fixed_bodyweight_capability_concern(
        {'exerciseType': 'BODY_WEIGHT', 'equipmentId': 'vest'}) is None
    assert unverified_fixed_bodyweight_capability_concern({'exerciseType': 'WEIGHT'}) is None


def test_final_audit_gates_fixed_bodyweight_and_only_exact_current_library_confirmation_clears_it(monkeypatch):
    from test_workout_generator_planning_tools import planning_case, requirement_messages
    from workout_generator_pkg.planning_tools import audit_workout_plan, library_fingerprint

    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    blocked = audit_workout_plan(draft, equipment, messages)
    capability_errors = [error for error in blocked['errors']
        if error['code'] == 'training_load_suitability_unresolved']
    assert [error['definition_id'] for error in capability_errors] == ['LIBRARY_0']

    fingerprint = library_fingerprint(equipment)
    decision = {'topic': 'Capability', 'choice': 'User reports ability.',
        'sourceReferences': ['SOURCE_0'], 'confirmedCapabilityReference': 'LIBRARY_0',
        'capabilityLibraryFingerprint': fingerprint}
    monkeypatch.setattr('workout_generator_pkg.planning_decisions.resolved_decisions',
        lambda _messages: {'DECISION_0': decision})
    cleared = audit_workout_plan(draft, equipment, messages)
    assert cleared['passed']

    decision['capabilityLibraryFingerprint'] = 'stale-library-fingerprint'
    stale = audit_workout_plan(draft, equipment, messages)
    assert any(error.get('definition_id') == 'LIBRARY_0' for error in stale['errors'])


def test_selection_options_filter_existing_history_gates_without_transferring_strength(monkeypatch):
    from workout_generator_pkg.session_drafting import preparation_selection_options

    history, equipment = case(monkeypatch)
    blocked = preparation_selection_options([], equipment, history)
    assert blocked['admissibleDefinitionIds'] == ['LIBRARY_1']
    concern = blocked['unresolvedConfigurations']['LIBRARY_0'][0]
    assert concern['code'] == 'related_history_ceiling_requires_reassessment'
    assert concern['relatedEvidence'][0]['definitionId'] == 'historical'
    assert 'uncertainty, not a strength conversion' in concern['message']

    history, equipment = case(monkeypatch, exact=True)
    supported = preparation_selection_options([], equipment, history)
    assert supported['admissibleDefinitionIds'] == ['LIBRARY_0', 'LIBRARY_1']
    assert not supported['unresolvedConfigurations']


def test_selection_options_preserve_capability_clarification_and_share_tool_domain(monkeypatch):
    from jsonschema import Draft7Validator
    from workout_generator_pkg import session_drafting

    equipment = {'exerciseDefinitions': [{'id': 'fixed', 'name': 'Fixed movement',
        'exerciseType': 'BODY_WEIGHT', 'equipmentId': None}]}
    selection_options = session_drafting.preparation_selection_options
    options = session_drafting.preparation_selection_options([], equipment)
    assert options['admissibleDefinitionIds'] == []
    assert options['unresolvedConfigurations']['LIBRARY_0'][0]['code'] == 'unverified_fixed_bodyweight_capability'
    assert options['unresolvedConfigurationNames'] == {'LIBRARY_0': 'Fixed movement'}
    monkeypatch.setattr(session_drafting, 'preparation_selection_options',
        lambda *args: (_ for _ in ()).throw(AssertionError('Reuse supplied local selection evidence.')))
    week = session_drafting.prepare_workout_sessions_tool([], equipment, selection_options=options)
    single = session_drafting.prepare_workout_session_tool([], equipment, selection_options=options)
    week_item = week['function']['parameters']['properties']['definition_ids']['items']
    single_item = single['function']['parameters']['properties']['definition_ids']['items']
    assert not Draft7Validator(week_item).is_valid('LIBRARY_0')
    assert not Draft7Validator(single_item).is_valid('LIBRARY_0')

    monkeypatch.setattr('workout_generator_pkg.training_history.confirmed_capability_references',
        lambda messages, gear: {'LIBRARY_0'})
    confirmed = selection_options([], equipment)
    assert confirmed['admissibleDefinitionIds'] == ['LIBRARY_0']
    assert not confirmed['unresolvedConfigurations']
