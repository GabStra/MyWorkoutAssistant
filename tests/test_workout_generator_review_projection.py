import copy
import json

from workout_generator_pkg.review_projection import compact_review_request


def _expand_links(value, request):
    if isinstance(value, dict):
        if set(value) == {'factsRef'}:
            target = request
            for token in value['factsRef'].split('/')[1:]:
                token = token.replace('~1', '/').replace('~0', '~')
                target = target[int(token)] if isinstance(target, list) else target[token]
            return _expand_links(target, request)
        return {key: _expand_links(child, request) for key, child in value.items()}
    if isinstance(value, list):
        return [_expand_links(child, request) for child in value]
    return value


def test_review_projection_preserves_evidence_and_citation_paths_without_mutating_context():
    uncertainty = 'Unknown physical configuration is not evidence of independent stations. ' * 3
    demands = {'unsupported_trunk': {'status': 'present', 'source': 'https://example.org/study'},
               'axial_loading': {'status': 'unknown', 'source': None}}
    transition = {'scope': 'within_exercise', 'fromWorkSetIndex': 0, 'toWorkSetIndex': 1,
                  'configurationRelation': 'unknown_configuration', 'physicalConfigurationKnown': False,
                  'interpretation': uncertainty}
    capability = {'selectableLoadsKg': [index / 4 for index in range(400)],
                  'observedLoadKg': None, 'evidenceStatus': 'no_comparable_records',
                  'authority': uncertainty}
    context = {
        'sourceMessages': {'SOURCE_0': {'role': 'user', 'content': 'Keep the exact prescriptions.'}},
        'requirements': {'approved': True, 'sourceReferences': ['SOURCE_0']},
        'draft': {'libraryDefinitions': {'LIBRARY_0': {'programmingDemandFacts': demands}}},
        'finalArtifact': {'programGuidance': uncertainty, 'workouts': [
            {'name': 'A', 'components': [{'type': 'Exercise', 'id': 'EXERCISE_0',
                                        'sets': [{'reps': 7, 'weight': 12.25}]}]}]},
        'programmingSummary': {'executionTimeVerified': False, 'sessions': [
            {'_reviewRef': 'SUMMARY_SESSION_A', 'setupEvidence': {'transitions': [transition] * 5},
             'interferenceEvidence': {'interpretation': uncertainty, 'primaryWorkingSets': 2},
             'timingComponents': {'estimatedTotalSeconds': 1234, 'note': uncertainty}},
            {'_reviewRef': 'SUMMARY_SESSION_B', 'setupEvidence': {'transitions': [transition] * 5}}],
            'exposures': {'LIBRARY_0': {'_reviewRef': 'SUMMARY_EXPOSURE_LIBRARY_0',
                                      'programmingDemandFacts': demands}}},
        'progressionCapabilities': {
            'LIBRARY_0': {'_reviewRef': 'PROGRESSION_LIBRARY_0', **capability},
            'LIBRARY_1': {'_reviewRef': 'PROGRESSION_LIBRARY_1', **capability}},
    }
    original = copy.deepcopy(context)

    projected = compact_review_request(context)

    assert context == original
    for root in ('sourceMessages', 'requirements', 'draft', 'finalArtifact'):
        assert projected[root] == original[root]
    assert projected['programmingSummary']['sessions'][0]['_reviewRef'] == 'SUMMARY_SESSION_A'
    assert projected['programmingSummary']['sessions'][1]['_reviewRef'] == 'SUMMARY_SESSION_B'
    assert projected['progressionCapabilities']['LIBRARY_1']['_reviewRef'] == 'PROGRESSION_LIBRARY_1'
    expanded = _expand_links(projected, projected)
    expanded.pop('factsRefMeaning')
    assert expanded == original
    assert len(json.dumps(projected)) < len(json.dumps(original)) * 0.8


def test_review_projection_keeps_distinct_values_and_escapes_reference_paths():
    known = {'status': 'present', 'source': 'https://example.org/evidence/' + 'a' * 180}
    unknown = {'status': 'unknown', 'source': None}
    context = {'draft': {'a/b~c': known},
               'programmingSummary': {'known': known, 'unknown': unknown}}

    projected = compact_review_request(context)

    assert projected['programmingSummary']['known'] == {
        'factsRef': '/draft/a~1b~0c'}
    assert projected['programmingSummary']['unknown'] == unknown
    expanded = _expand_links(projected, projected)
    expanded.pop('factsRefMeaning')
    assert expanded == context


def test_review_projection_deduplicates_across_roots_without_hiding_history_changes():
    capacity = {'status': 'comparable_records', 'observedLoadKg': 42.5,
                'uncertainty': 'A recorded set does not establish present recovery or capacity. ' * 4}
    demands = {'status': 'unknown', 'explanation': 'No measured physical configuration. ' * 8}
    context = {
        # The shorter canonical path occurs after its longer duplicate.
        'programmingSummary': {'exposures': {'LIBRARY_0': {
            '_reviewRef': 'SUMMARY_EXPOSURE_LIBRARY_0', 'capacity': capacity,
            'demands': demands}}},
        'draft': {'exercises': [{'_reviewRef': 'EXERCISE_0', 'demands': demands}]},
        'history': {
            'LIBRARY_0': {'_reviewRef': 'HISTORY_LIBRARY_0', 'capacity': capacity},
            'LIBRARY_1': {'_reviewRef': 'HISTORY_LIBRARY_1',
                          'capacity': {**capacity, 'observedLoadKg': 45.0}},
        },
        'audit': {'demands': demands},
        'finalArtifact': {'programGuidance': demands['explanation'], 'workouts': []},
        'sourceMessages': {'SOURCE_0': {'_reviewRef': 'SOURCE_0',
                                       'content': demands['explanation']}},
    }
    original = copy.deepcopy(context)

    projected = compact_review_request(context)

    assert context == original
    assert projected['finalArtifact'] == original['finalArtifact']
    assert projected['sourceMessages'] == original['sourceMessages']
    assert projected['programmingSummary']['exposures']['LIBRARY_0']['capacity'] == {
        'factsRef': '/history/LIBRARY_0/capacity'}
    assert projected['draft']['exercises'][0]['demands'] == {'factsRef': '/audit/demands'}
    assert projected['history']['LIBRARY_1']['capacity']['observedLoadKg'] == 45.0
    expanded = _expand_links(projected, projected)
    expanded.pop('factsRefMeaning')
    assert expanded == original
