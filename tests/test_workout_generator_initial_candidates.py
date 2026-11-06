import copy

from workout_generator_pkg import planner_context
from workout_generator_pkg.planning_tools import library_fingerprint
from workout_generator_pkg.restriction_policy import RESTRICTION_POLICY_VERSION
from test_workout_generator_planning_tools import planning_case, requirement_messages


def _selection_case():
    equipment, _, receipt, _ = planning_case()
    base = equipment['exerciseDefinitions'][0]
    equipment['equipments'] = [{'id': 'available', 'name': 'Available load'}]
    equipment['exerciseDefinitions'] = [
        {**base, 'id': 'a', 'name': 'Available movement', 'exerciseType': 'WEIGHT', 'equipmentId': 'available'},
        {**base, 'id': 'b', 'name': 'Excluded movement', 'exerciseType': 'WEIGHT', 'equipmentId': 'available'},
        {**base, 'id': 'c', 'name': 'Missing implement', 'equipmentId': 'missing'},
        {**base, 'id': 'd', 'name': 'Missing accessory', 'requiredAccessoryEquipmentIds': ['missing']},
        {**base, 'id': 'e', 'name': 'Unknown capability'},
        {**base, 'id': 'f', 'name': 'Unclassified alternative', 'exerciseType': 'WEIGHT', 'equipmentId': 'available'},
    ]
    receipt['requirements']['sessionsPerWeek'] = 2
    receipt['requirements']['exerciseRestrictions'] = {'excludeNameTerms': ['Excluded movement']}
    receipt['restrictionPolicy'] = {
        'resolutionVersion': RESTRICTION_POLICY_VERSION,
        'libraryFingerprint': library_fingerprint(equipment), 'excludedDefinitionIds': ['b']}
    return equipment, requirement_messages(receipt)


def test_initial_pool_replaces_discovery_with_complete_admitted_metadata_without_mutating_transcript():
    equipment, messages = _selection_case()
    original = copy.deepcopy(messages)
    state = planner_context.request_planning_state(
        planner_context.focus_planner_context(messages, messages, equipment))

    assert state['constructionTask']['stage'] == 'choose_movements'
    assert set(state['exerciseCandidates']) == {'LIBRARY_0', 'LIBRARY_5'}
    assert set(state['preparationSelectionOptions']['admissibleDefinitionIds']) == {'LIBRARY_0', 'LIBRARY_5'}
    assert state['exerciseCandidates']['LIBRARY_5']['programmingDemandFacts']['unsupported_trunk']['status'] == 'unknown'
    assert state['candidateRetrieval']['semanticCoverage'] == 'unqualified'
    assert 'search_exercise_library' in state['candidateRetrieval']['instruction']
    assert 'LIBRARY_4' in state['preparationSelectionOptions']['unresolvedConfigurations']
    assert messages == original


def test_initial_pool_reuses_local_history_summary_without_claiming_coverage():
    equipment, messages = _selection_case()

    class History:
        def evidence(self, arguments, _equipment):
            return {'exercises': [{'reference': reference, 'loadSuitabilityConcerns': (
                [{'code': 'unverified_fixed_bodyweight_capability'}] if reference == 'LIBRARY_4' else [])}
                for reference in arguments['definition_ids']]}

        def annotate_search(self, payload, _equipment):
            for query in payload['results']:
                for entry in query['exercises']:
                    entry['trainingEvidence'] = {'status': 'no_comparable_records', 'totalSessions': 0}
            return payload

    state = planner_context.request_planning_state(planner_context.focus_planner_context(
        messages, messages, equipment, training_history=History()))
    candidate = state['exerciseCandidates']['LIBRARY_0']
    assert candidate['trainingEvidence']['status'] == 'no_comparable_records'
    assert 'satisfiesCoverage' not in candidate
    assert 'LIBRARY_4' not in state['exerciseCandidates']


def test_prepared_or_unapproved_context_does_not_expand_candidate_pool():
    equipment, messages = _selection_case()
    for approved, stage in ((True, 'draft_sessions'), (False, 'discover_movements')):
        state = {'requirementsApproved': approved, 'exerciseCandidates': {},
                 'constructionTask': {'stage': stage}}
        planner_context._preparation_selection_context(state, messages, equipment, None)
        assert state['exerciseCandidates'] == {}
        assert 'candidateRetrieval' not in state
