from workout_generator_pkg.planning_tools import (
    _audit_coverage,
    _filter_unsupported_warmup_candidates,
    _normalize_definition_dependent_fields,
)
from workout_generator_pkg.programming_guidelines import (
    EXECUTION_RULES_SCHEMA, audit_execution_rules, replacement_supports_required_warmup,
)


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


def test_category_preparation_uses_native_capability_without_excluding_other_movements():
    from jsonschema import validate
    from workout_generator_pkg.planner_context import replacement_definition_references_by_occurrence

    equipment = {'exerciseDefinitions': [
        {'id': 'a-press', 'exerciseType': 'WEIGHT', 'equipmentId': 'bar',
         'exerciseCategory': 'HEAVY_COMPOUND'},
        {'id': 'b-pull', 'exerciseType': 'BODY_WEIGHT', 'equipmentId': 'vest',
         'bodyWeightPercentage': 100, 'exerciseCategory': 'HEAVY_COMPOUND'},
        {'id': 'c-unweighted', 'exerciseType': 'BODY_WEIGHT', 'equipmentId': None,
         'bodyWeightPercentage': 65, 'exerciseCategory': 'MODERATE_COMPOUND'},
        {'id': 'd-isolation', 'exerciseType': 'WEIGHT', 'equipmentId': 'bar',
         'exerciseCategory': 'ISOLATION'},
        {'id': 'e-missing-equipment', 'exerciseType': 'WEIGHT', 'equipmentId': 'missing',
         'exerciseCategory': 'HEAVY_COMPOUND'},
        {'id': 'f-missing-percentage', 'exerciseType': 'BODY_WEIGHT', 'equipmentId': 'vest',
         'exerciseCategory': 'HEAVY_COMPOUND'},
    ], 'equipments': [{'id': 'bar'}, {'id': 'vest'}]}
    requirements = {'executionRules': [
        {'kind': 'warmup', 'coverageKey': None, 'exerciseCategory': category, 'whenSupported': True}
        for category in ('HEAVY_COMPOUND', 'MODERATE_COMPOUND')]}
    validate(requirements['executionRules'], EXECUTION_RULES_SCHEMA)
    draft = {'workouts': [{'name': 'A', 'exercises': [
        {'definition_id': f'LIBRARY_{index}', 'satisfiesCoverage': ['upper'],
         'generateWarmUpSets': False, 'superset': None, 'numWorkSets': 2,
         'restBetweenSetsSeconds': 90}
        for index in range(len(equipment['exerciseDefinitions']))]}]}
    _normalize_definition_dependent_fields(draft, equipment, requirements)
    exercises = draft['workouts'][0]['exercises']
    assert [item['generateWarmUpSets'] for item in exercises] == [True, True, False, False, False, False]
    assert _filter_unsupported_warmup_candidates(draft['workouts'], equipment, requirements) == []
    assert len(exercises) == 6
    choices = replacement_definition_references_by_occurrence(
        draft, ['LIBRARY_0', 'LIBRARY_2'], equipment, requirements)
    assert all(value == ['LIBRARY_0', 'LIBRARY_2'] for value in choices.values())

    plan = {'exercises': [dict(definition, id=f'EX_{index}')
        for index, definition in enumerate(equipment['exerciseDefinitions'])],
        'equipments': equipment['equipments'],
        'workouts': [{'exerciseIds': [f'EX_{index}' for index in range(6)]}]}
    report = {'issues': [], 'errors': []}
    audit_execution_rules(draft, requirements, report, plan)
    assert not report['errors']
    exercises[0]['generateWarmUpSets'] = False
    audit_execution_rules(draft, requirements, report, plan)
    assert len(report['errors']) == 1
    assert report['errors'][0]['path'].endswith('/0/generateWarmUpSets')

    _normalize_definition_dependent_fields(draft, equipment, requirements,
        execution_definitions={'d-isolation': dict(equipment['exerciseDefinitions'][3],
                                                 exerciseCategory='MODERATE_COMPOUND')})
    assert exercises[3]['generateWarmUpSets'] is True
    strict = {'executionRules': [{'kind': 'warmup', 'coverageKey': None,
                                'exerciseCategory': 'HEAVY_COMPOUND'}]}
    removed = _filter_unsupported_warmup_candidates(draft['workouts'], equipment, strict)
    assert [item['definition_id'] for item in removed] == ['LIBRARY_4', 'LIBRARY_5']
    assert any(item['definition_id'] == 'LIBRARY_2' for item in draft['workouts'][0]['exercises'])


def test_strict_category_preparation_restricts_only_matching_source_occurrences():
    source = {'exerciseCategory': 'HEAVY_COMPOUND'}
    unsupported = {'exerciseType': 'BODY_WEIGHT', 'exerciseCategory': 'MODERATE_COMPOUND'}
    requirements = {'executionRules': [
        {'kind': 'warmup', 'coverageKey': None, 'exerciseCategory': 'HEAVY_COMPOUND'}]}
    assert not replacement_supports_required_warmup([], unsupported, set(), requirements, source)
    assert replacement_supports_required_warmup([], unsupported, set(), requirements, unsupported)
