import pytest

from workout_generator_pkg.programming_demands import (
    definition_demand_facts, demand_distribution_inputs,
)


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


def test_generator_demand_evidence_does_not_leak_into_app_export_definitions():
    from copy import deepcopy
    from test_workout_generator_planning_tools import planning_case
    from workout_generator_pkg.domain_ops import apply_exercise_library_schema_v2

    equipment, _, _, _ = planning_case()
    definition = deepcopy(equipment['exerciseDefinitions'][0])
    definition['programmingDemands'] = {
        'unsupported_trunk': {'present': False, 'source': 'Reviewed library execution setup'}}
    original = deepcopy(definition)
    component = {key: value for key, value in definition.items() if key not in ('id', 'programmingDemands')}
    component.update(type='Exercise', id='prescription')
    package = {'workouts': [{'workoutComponents': [component]}]}

    apply_exercise_library_schema_v2(package, [definition])

    assert package['exerciseDefinitions'][0]['id'] == definition['id']
    assert 'programmingDemands' not in package['exerciseDefinitions'][0]
    assert definition == original
