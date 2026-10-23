from workout_generator_pkg.planning_tools import (
    _audit_coverage,
    _filter_unsupported_warmup_candidates,
    _normalize_definition_dependent_fields,
)
from workout_generator_pkg.programming_guidelines import audit_execution_rules


def test_approved_warmup_role_sets_flag_only_when_native_app_can_generate_it():
    equipment = {'exerciseDefinitions': [
        {'id': 'loadable', 'exerciseType': 'WEIGHT', 'equipmentId': 'EQ_0'},
        {'id': 'unloaded', 'exerciseType': 'BODY_WEIGHT', 'equipmentId': None,
         'bodyWeightPercentage': 65},
    ], 'equipments': [{'id': 'EQ_0'}]}
    draft = {'workouts': [{'exercises': [
        {'definition_id': 'LIBRARY_0', 'satisfiesCoverage': ['posterior_chain'], 'generateWarmUpSets': False},
        {'definition_id': 'LIBRARY_0', 'satisfiesCoverage': ['chest'], 'generateWarmUpSets': True},
        {'definition_id': 'LIBRARY_0', 'satisfiesCoverage': ['chest'], 'generateWarmUpSets': False},
        {'definition_id': 'LIBRARY_1', 'satisfiesCoverage': ['posterior_chain'], 'generateWarmUpSets': False},
    ]}]}
    requirements = {'executionRules': [{'kind': 'warmup', 'coverageKey': 'posterior_chain'}]}

    _normalize_definition_dependent_fields(draft, equipment, requirements)

    assert [item['generateWarmUpSets'] for item in draft['workouts'][0]['exercises']] == [True, True, False, False]

    removed = _filter_unsupported_warmup_candidates(draft['workouts'], equipment, requirements)
    assert [item['definition_id'] for item in removed] == ['LIBRARY_1']
    assert [item['definition_id'] for item in draft['workouts'][0]['exercises']] == [
        'LIBRARY_0', 'LIBRARY_0', 'LIBRARY_0']


def test_unsupported_warmup_option_does_not_block_supported_coverage_option():
    equipment = {'exerciseDefinitions': [
        {'id': 'bodyweight', 'exerciseType': 'BODY_WEIGHT', 'equipmentId': None,
         'bodyWeightPercentage': 65},
        {'id': 'loadable', 'exerciseType': 'WEIGHT', 'equipmentId': 'EQ_0'},
    ], 'equipments': [{'id': 'EQ_0'}]}
    workouts = [{'name': 'A', 'exercises': [
        {'definition_id': 'LIBRARY_0', 'satisfiesCoverage': ['posterior_chain']},
        {'definition_id': 'LIBRARY_1', 'satisfiesCoverage': ['posterior_chain']},
    ]}]
    requirements = {
        'executionRules': [{'kind': 'warmup', 'coverageKey': 'posterior_chain'}],
        'requiredCoverage': [{'key': 'posterior_chain', 'description': 'Posterior-chain work',
                             'scope': 'eachSession'}],
    }

    removed = _filter_unsupported_warmup_candidates(workouts, equipment, requirements)
    report = {'issues': [], 'errors': []}
    _audit_coverage({'workouts': workouts}, requirements, report)

    assert [item['definition_id'] for item in removed] == ['LIBRARY_0']
    assert [item['definition_id'] for item in workouts[0]['exercises']] == ['LIBRARY_1']
    assert not report['errors']


def test_unsupported_warmup_audit_does_not_recommend_toggling_flag():
    draft = {'workouts': [{'name': 'A', 'exercises': [{
        'definition_id': 'LIBRARY_0', 'satisfiesCoverage': ['posterior_chain'],
        'generateWarmUpSets': False, 'superset': None, 'numWorkSets': 3,
        'restBetweenSetsSeconds': 90,
    }]}]}
    requirements = {'executionRules': [{'kind': 'warmup', 'coverageKey': 'posterior_chain'}]}
    plan = {'exercises': [{'id': 'EX_0', 'exerciseType': 'BODY_WEIGHT', 'equipmentId': None,
                           'bodyWeightPercentage': 65}],
            'equipments': [], 'workouts': [{'exerciseIds': ['EX_0']}]}
    report = {'issues': [], 'errors': []}

    audit_execution_rules(draft, requirements, report, plan)

    assert len(report['errors']) == 1
    assert report['errors'][0]['code'] == 'execution_warmup'
    assert report['errors'][0].get('warmupCapability') == 'unsupported'
    assert 'do not toggle the flag' in report['errors'][0]['repair']
