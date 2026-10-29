import pytest

from workout_generator_pkg.programming_demands import (
    definition_demand_facts, demand_distribution_inputs, demand_union_exposure_input,
)


def _classified_definition(identifier, **present):
    return {'id': identifier, 'programmingDemands': {
        key: {'present': key in present, 'source': f'Reviewed {key} setup'}
        for key in ('unsupported_trunk', 'axial_loading', 'eccentric_emphasis')}}


def test_unannotated_or_partially_annotated_candidates_cannot_look_like_low_demand():
    known = {'id': 'known', 'programmingDemands': {
        'unsupported_trunk': {'present': True, 'source': 'Reviewed execution specification'}}}
    unknown = {'id': 'unknown', 'name': 'Supported row', 'exerciseCategory': 'ISOLATION'}
    assert definition_demand_facts(unknown)['unsupported_trunk']['status'] == 'unknown'
    inputs = demand_distribution_inputs([known, unknown])
    assert 'unsupported_trunk' not in inputs['groups']
    assert inputs['unavailableGroups']['unsupported_trunk'] == ['unknown']
    unknown['programmingDemands'] = {
        'unsupported_trunk': {'present': False, 'source': 'Reviewed supported configuration'}}
    inputs = demand_distribution_inputs([known, unknown])
    assert inputs['groups']['unsupported_trunk']['presentDefinitionIds'] == ['known']
    assert inputs['groups']['unsupported_trunk']['evidenceByDefinition']['unknown']
    assert inputs['status'] == 'partial'  # The other physical properties are still unknown.


def test_library_annotations_fail_closed_when_malformed_or_unsourced():
    for annotation in ({'present': 'yes', 'source': 'source'}, {'present': True, 'source': ''},
                       {'present': True, 'source': 'source', 'fatigueScore': 10}):
        with pytest.raises(ValueError, match='requires a boolean present'):
            definition_demand_facts({'programmingDemands': {'unsupported_trunk': annotation}})
    with pytest.raises(ValueError, match='supported library property keys'):
        definition_demand_facts({'programmingDemands': {'fatigueScore': 10}})


def test_union_exposure_distinguishes_disjoint_known_property_groups():
    inputs = demand_distribution_inputs([
        _classified_definition('unsupported', unsupported_trunk=True),
        _classified_definition('axial', axial_loading=True),
    ])

    union = demand_union_exposure_input(inputs)

    assert union['presentDefinitionIds'] == ['axial', 'unsupported']
    assert union['availableGroups'] == ['axial_loading', 'eccentric_emphasis', 'unsupported_trunk']
    assert union['status'] == 'available'
    assert 'structural concentration only' in union['interpretation']


def test_union_exposure_counts_a_definition_once_when_properties_overlap():
    inputs = demand_distribution_inputs([
        _classified_definition('overlap', unsupported_trunk=True, axial_loading=True),
        _classified_definition('eccentric', eccentric_emphasis=True),
    ])

    union = demand_union_exposure_input(inputs)

    assert union['presentDefinitionIds'] == ['eccentric', 'overlap']
    assert union['evidenceByDefinition']['overlap'] == {
        'unsupported_trunk': 'Reviewed unsupported_trunk setup',
        'axial_loading': 'Reviewed axial_loading setup',
    }


def test_union_exposure_keeps_unknown_candidates_out_of_known_union_and_reports_partiality():
    unknown = {'id': 'unknown', 'programmingDemands': {
        'axial_loading': {'present': False, 'source': 'Reviewed axial setup'},
        'eccentric_emphasis': {'present': False, 'source': 'Reviewed eccentric setup'},
    }}
    inputs = demand_distribution_inputs([
        _classified_definition('axial', axial_loading=True),
        _classified_definition('eccentric', eccentric_emphasis=True),
        unknown,
    ])

    union = demand_union_exposure_input(inputs)

    assert union['presentDefinitionIds'] == ['axial', 'eccentric']
    assert union['status'] == 'partial'
    assert union['unavailableGroups']['unsupported_trunk'] == ['unknown']
    assert 'unavailable properties remain unknown' in union['interpretation']


def test_confirmed_demand_priority_round_trips_through_requirements_and_candidate_metadata():
    from test_workout_generator_planning_tools import planning_case
    from workout_generator_pkg.exercise_library_tools import _selection_entry
    from workout_generator_pkg.planning_tools import set_workout_requirements

    equipment, requirements, _, _ = planning_case()
    requirements['objectiveOrder'] = ['demand_distribution', 'distribution', 'source_balance']
    original_targets = requirements['auditTargets'].copy()
    result = set_workout_requirements(requirements,
        [{'role': 'user', 'content': 'Prioritize demand distribution before muscle-set distribution and balance.'}],
        equipment)
    assert result['requirements']['objectiveOrder'] == requirements['objectiveOrder']
    assert result['requirements']['auditTargets'] == original_targets
    assert 'demand_distribution, distribution, source_balance' in result['requirementsPreview']

    definition = {**equipment['exerciseDefinitions'][0], 'programmingDemands': {
        'unsupported_trunk': {'present': False, 'source': 'Reviewed library execution setup'}}}
    entry = _selection_entry(definition, {}, 'LIBRARY_0')
    assert entry['programmingDemandFacts']['unsupported_trunk'] == {
        'status': 'absent', 'source': 'Reviewed library execution setup'}


def test_generator_evidence_does_not_leak_into_app_export_definitions(monkeypatch):
    from copy import deepcopy
    from test_workout_generator_planning_tools import planning_case
    from workout_generator_pkg.domain_ops import apply_exercise_library_schema_v2
    from workout_generator_pkg import recipe_contracts

    equipment, _, _, _ = planning_case()
    definition = deepcopy(equipment['exerciseDefinitions'][0])
    evidence_source = 'https://example.org/reviewed-anatomy'
    definition['programmingDemands'] = {
        'unsupported_trunk': {'present': False, 'source': 'Reviewed library execution setup'}}
    definition['anatomy'] = {
        'primarySubregions': ['deltoid_lateral'], 'secondarySubregions': [],
        'source': evidence_source, 'basis': 'Reviewed source-backed attribution.'}
    definition['reviewedExerciseFamily'] = {
        'exerciseFamilyId': '00000000-0000-0000-0000-000000000001',
        'source': evidence_source, 'basis': 'Reviewed source-backed family.'}
    monkeypatch.setattr(recipe_contracts, '_reviewed_exercise_annotations_by_definition', lambda: {
        definition['id']: {'anatomy': deepcopy(definition['anatomy'])}})
    original = deepcopy(definition)
    component = {key: value for key, value in definition.items()
                 if key not in ('id', 'programmingDemands', 'anatomy', 'reviewedExerciseFamily')}
    component.update(type='Exercise', id='prescription')
    package = {'workouts': [{'workoutComponents': [component]}]}

    apply_exercise_library_schema_v2(package, [definition])

    assert package['exerciseDefinitions'][0]['id'] == definition['id']
    assert 'programmingDemands' not in package['exerciseDefinitions'][0]
    assert 'anatomy' not in package['exerciseDefinitions'][0]
    assert 'reviewedExerciseFamily' not in package['exerciseDefinitions'][0]
    regional_facts = recipe_contracts.regional_muscle_facts(package['exerciseDefinitions'][0])
    assert regional_facts['deltoid_lateral'] == {
        'status': 'present', 'label': 'Lateral deltoid', 'effectiveSets': 1,
        'source': evidence_source}
    assert definition == original
