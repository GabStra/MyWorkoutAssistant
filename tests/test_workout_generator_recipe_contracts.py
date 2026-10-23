import copy
import json

import pytest
from workout_generator_pkg.api_client import _strict_parameters_compatible

from workout_generator_pkg import joint_planning, recipe_contracts
from workout_generator_pkg.planning_tools import (
    library_fingerprint,
    set_workout_requirements,
)
from test_workout_generator_planning_tools import planning_case


def recipe_case(required_coverage=None):
    equipment, requirements, _, draft = planning_case()
    equipment['equipments'] = [{'id': 'EQUIPMENT_0', 'name': 'Weight vest', 'type': 'WEIGHTVEST',
        'availableWeights': [{'weight': value} for value in range(1, 21)]}]
    weighted = copy.deepcopy(equipment['exerciseDefinitions'][0])
    weighted.update(id='weighted_press', name='Weighted Push-Up', equipmentId='EQUIPMENT_0')
    equipment['exerciseDefinitions'].append(weighted)
    requirements['sessionsPerWeek'] = 3
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 15, 'maximum': 18}
    if required_coverage is not None:
        requirements['requiredCoverage'] = required_coverage
    sessions = []
    for index in range(3):
        day = copy.deepcopy(draft['workouts'][0])
        day.update(name=f'Day {index}', trainingDays=[2 * index])
        first = day['exercises'][0]
        first.update(numWorkSets=5, workSetTemplate={'reps': 8, 'additionalWeight': 0})
        first.pop('placementNotes', None)
        second = copy.deepcopy(first)
        second.update(definition_id='LIBRARY_1', numWorkSets=1)
        day['exercises'].append(second)
        sessions.append(day)
    stored = set_workout_requirements(requirements,
        [{'role': 'user', 'content': 'Use chest exercises. Include a push movement in each session.'}], equipment)
    prepared = {'definition_ids': ['LIBRARY_0', 'LIBRARY_1'],
        'candidates': {'LIBRARY_0': equipment['exerciseDefinitions'][0],
                       'LIBRARY_1': equipment['exerciseDefinitions'][1]},
        'sourceMessages': {'SOURCE_0': {'role': 'user', 'content': 'Include a push movement in each session.'}},
        'libraryFingerprint': library_fingerprint(equipment)}
    return equipment, requirements, sessions, stored, prepared


def test_load_headroom_does_not_override_intended_dose_with_equipped_variants():
    equipment, requirements, sessions, _, _ = recipe_case()
    requirements['objectiveOrder'] = ['progression', 'preservation']
    for day in sessions:
        day['exercises'][0]['numWorkSets'] = 3
        day['exercises'][1]['numWorkSets'] = 2
    before = copy.deepcopy(sessions)

    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment)

    assert result['feasible'], result
    assert [[(item['definition_id'], item['numWorkSets']) for item in day['exercises']]
            for day in result['sessions']] == [[('LIBRARY_0', 3), ('LIBRARY_1', 2)]] * 3
    assert 15 <= result['audit']['weeklyVolume']['chest']['effective'] <= 18
    assert {'load_headroom', 'load_capped'} == {margin['status'] for margin in result['progressionMargins']}
    assert all('penalty' not in margin for margin in result['progressionMargins'])
    assert result['objectiveOrderUsed'] == ['preservation']
    assert result['approvedObjectiveOrder'] == ['progression', 'preservation']
    assert sessions == before


def test_unknown_headroom_does_not_assign_a_quality_penalty_or_imply_assistance():
    equipment, _, _, _, _ = recipe_case()
    for definition in equipment['exerciseDefinitions']:
        capability = recipe_contracts.progression_capability(definition, equipment)
        margin = recipe_contracts.progression_margin({}, capability)
        assert margin['status'] == 'unknown' and 'penalty' not in margin
        assert capability['minimumSelectableLoadKg'] == 0
        assert 'do not establish unassisted ability' in capability['authority']


def test_progression_margin_uses_current_numeric_prescription_and_configuration():
    equipment, _, sessions, _, _ = recipe_case()
    definition = equipment['exerciseDefinitions'][1]
    capability = recipe_contracts.progression_capability(definition, equipment)
    capability['observedLoadKg'] = 20

    margin = recipe_contracts.progression_margin(sessions[0]['exercises'][1], capability)

    assert margin['status'] == 'load_headroom'
    assert margin['referenceLoadKg'] == 0  # Current prescription outranks historical observation.
    assert margin['remainingLoadSteps'] > 0
    assert 'nextDefinitionId' not in margin


def test_coverage_qualification_has_no_progression_contract_or_model_context(monkeypatch):
    equipment, _, _, stored, prepared = recipe_case(
        [{'key': 'push', 'description': 'A pushing movement', 'scope': 'eachSession'}])
    calls = []

    def qualify(_, request, **kwargs):
        schema = kwargs['output_schema']
        assert _strict_parameters_compatible(schema)
        item_schema = schema['properties']['contracts']['items']
        assert set(item_schema['properties']) == {'definition_id', 'satisfiesCoverage'}
        assert set(item_schema['required']) == {'definition_id', 'satisfiesCoverage'}
        assert 'progression' not in request[0]['content'].casefold()
        context = json.loads(request[-1]['content'])
        serialized = json.dumps(context).casefold()
        for forbidden in ('progressionplan', 'eligibleprogressiontargets', 'capability', 'selectableloads'):
            assert forbidden not in serialized
        calls.append(1)
        return json.dumps({'contracts': [
            {'definition_id': ref, 'satisfiesCoverage': ['push']} for ref in prepared['definition_ids']]}), None, None

    monkeypatch.setattr(recipe_contracts, 'chat_call', qualify)
    result = recipe_contracts.qualify_recipe_contracts(None, prepared, stored, equipment, [], {})

    assert len(calls) == 1
    assert all(set(item) == {'definition_id', 'satisfiesCoverage'} for item in result['contracts'])
    assert 'capabilities' not in result


def test_coverage_qualification_is_local_when_no_roles_are_approved(monkeypatch):
    equipment, _, _, stored, prepared = recipe_case()
    monkeypatch.setattr(recipe_contracts, 'chat_call',
        lambda *args, **kwargs: pytest.fail('No semantic coverage means no qualification call'))

    result = recipe_contracts.qualify_recipe_contracts(None, prepared, stored, equipment, [], {})

    assert result['contracts'] == [
        {'definition_id': ref, 'satisfiesCoverage': []} for ref in prepared['definition_ids']]


def test_invalid_coverage_qualification_is_rejected_without_prompt_retry(monkeypatch):
    equipment, _, _, stored, prepared = recipe_case(
        [{'key': 'push', 'description': 'A pushing movement', 'scope': 'eachSession'}])
    calls = []

    def invalid(*args, **kwargs):
        calls.append(1)
        return json.dumps({'contracts': [
            {'definition_id': ref, 'satisfiesCoverage': ['push', 'push']}
            for ref in prepared['definition_ids']]}), None, None

    monkeypatch.setattr(recipe_contracts, 'chat_call', invalid)

    with pytest.raises(Exception):
        recipe_contracts.qualify_recipe_contracts(None, prepared, stored, equipment, [], {})

    assert len(calls) == 1


def test_coverage_contract_cache_reuses_only_matching_coverage_context(monkeypatch):
    equipment, _, _, stored, prepared = recipe_case(
        [{'key': 'push', 'description': 'A pushing movement', 'scope': 'eachSession'}])
    calls = []

    def qualify(_, request, **kwargs):
        context = json.loads(request[-1]['content'])
        calls.append(context)
        return json.dumps({'contracts': [
            {'definition_id': ref, 'satisfiesCoverage': ['push']} for ref in prepared['definition_ids']]}), None, None

    monkeypatch.setattr(recipe_contracts, 'chat_call', qualify)
    first = recipe_contracts.qualify_recipe_contracts(None, prepared, stored, equipment, [], {})
    recipe_contracts.qualify_recipe_contracts(None, prepared, stored, equipment, [], {}, first)

    assert len(calls) == 1
    changed = copy.deepcopy(stored)
    changed['requirements']['requiredCoverage'][0]['description'] = 'A horizontal push movement'
    recipe_contracts.qualify_recipe_contracts(None, prepared, changed, equipment, [], {}, first)
    assert len(calls) == 2


def test_coverage_repair_feedback_invalidates_only_its_cached_contract(monkeypatch):
    equipment, _, _, stored, prepared = recipe_case(
        [{'key': 'push', 'description': 'A pushing movement', 'scope': 'eachSession'}])
    requests = []

    def qualify(_, request, **kwargs):
        context = json.loads(request[-1]['content'])
        requests.append(context)
        contracts = []
        for recipe in context['recipes']:
            ref = recipe['definition_id']
            contracts.append({'definition_id': ref, 'satisfiesCoverage': []})
        return json.dumps({'contracts': contracts}), None, None

    monkeypatch.setattr(recipe_contracts, 'chat_call', qualify)
    cached = recipe_contracts.qualify_recipe_contracts(None, prepared, stored, equipment, [], {})
    prepared['reviewFeedbackByDefinition'] = {'LIBRARY_0': [{
        'findingIndex': 2, 'reason': 'Coverage role was assigned to the wrong exercise.',
        'finding': {'field': 'satisfiesCoverage', 'message': 'Re-audit push-role suitability.'}}]}

    refreshed = recipe_contracts.qualify_recipe_contracts(None, prepared, stored, equipment, [], {}, cached)

    assert len(requests) == 2
    assert [recipe['definition_id'] for recipe in requests[1]['recipes']] == ['LIBRARY_0']
    assert requests[1]['recipes'][0]['reviewFeedback'] == prepared['reviewFeedbackByDefinition']['LIBRARY_0']
    assert refreshed['inputHashes']['LIBRARY_0'] != cached['inputHashes']['LIBRARY_0']
    assert refreshed['inputHashes']['LIBRARY_1'] == cached['inputHashes']['LIBRARY_1']


def test_recipe_qualification_rejects_duplicate_definition_ids():
    equipment, _, _, stored, prepared = recipe_case()
    prepared['definition_ids'] = ['LIBRARY_0', 'LIBRARY_0']
    prepared['candidates'] = {'LIBRARY_0': equipment['exerciseDefinitions'][0]}

    with pytest.raises(ValueError, match='exactly once'):
        recipe_contracts.qualify_recipe_contracts(None, prepared, stored, equipment, [], {})
