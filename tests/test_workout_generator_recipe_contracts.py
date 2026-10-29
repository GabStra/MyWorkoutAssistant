import copy
import json

import pytest
from workout_generator_pkg.api_client import _strict_parameters_compatible

from workout_generator_pkg import allocation, joint_planning, plan_review, recipe_contracts
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


def test_reviewed_exercise_family_annotations_group_only_sourced_definition_ids():
    equipment = {'exerciseDefinitions': [
        {'id': '46b322a6-cee1-55eb-90ca-2df679f72999', 'name': 'Renamed weighted item'},
        {'id': 'c43df18d-b03e-5c4c-8554-c720c7b2ae19', 'name': 'Renamed Nordic item'},
        {'id': '904fc6ff-ebac-5ee6-bdfb-dd5e9835aea2', 'name': 'Another renamed item'},
        {'id': '683216a5-72dd-5200-9fb9-8e0ece4b969d', 'name': 'Item with an app family default',
         'exerciseFamilyId': '00000000-0000-0000-0000-000000000001'},
        {'id': 'a4a8dc45-7ddb-5044-9834-e25fc60507c4', 'name': 'A different posterior movement'},
        {'id': 'ab406af0-5c55-5ddf-b34c-b70641f14cfe', 'name': 'Dumbbell pair RDL'},
        {'id': 'unreviewed', 'name': 'Unreviewed exercise', 'movementRef': {'movementId': 'shared-animation'}},
    ]}

    evidence = recipe_contracts.reviewed_exercise_family_evidence(equipment)

    nordic_family = evidence['familyByReference']['LIBRARY_0']
    rdl_family = evidence['familyByReference']['LIBRARY_1']
    assert nordic_family == evidence['familyByReference']['LIBRARY_2'] == evidence['familyByReference']['LIBRARY_5']
    assert rdl_family == evidence['familyByReference']['LIBRARY_4']
    assert rdl_family != nordic_family
    assert evidence['familyByReference']['LIBRARY_3'] not in {nordic_family, rdl_family}
    assert evidence['sourcesByReference']['LIBRARY_0']['source'].startswith('https://')
    assert evidence['unclassifiedReferences'] == ['LIBRARY_6']


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


def test_lateral_delt_coverage_comes_only_from_reviewed_primary_anatomy():
    roles = {'lateral_delt', 'upper_push'}
    overhead_press = {'id': '8b6b9813-39b1-5c86-89bf-22ab6828556e',
        'anatomy': {'primarySubregions': ['deltoid_lateral']}}
    lateral_raise = {'id': '531463a1-bb50-5265-8eda-13fbf9a1b7e2',
        'anatomy': {'primarySubregions': ['deltoid_anterior']}}
    unreviewed = {'id': 'unreviewed-definition',
        'anatomy': {'primarySubregions': ['deltoid_lateral']}}

    assert recipe_contracts.canonical_qualified_roles(overhead_press, ['lateral_delt', 'upper_push'], roles) == ['upper_push']
    assert recipe_contracts.canonical_qualified_roles(lateral_raise, [], roles) == ['lateral_delt']
    assert recipe_contracts.canonical_qualified_roles(unreviewed, [], roles) == []


def test_retained_qualification_recomputes_code_owned_lateral_role_from_definition_id():
    definitions = {
        'LIBRARY_0': {'id': '8b6b9813-39b1-5c86-89bf-22ab6828556e'},
        'LIBRARY_1': {'id': '531463a1-bb50-5265-8eda-13fbf9a1b7e2'},
    }
    hashes = {'LIBRARY_0': 'press', 'LIBRARY_1': 'raise'}
    receipt = {'inputHashes': hashes, 'contracts': [
        {'definition_id': reference, 'satisfiesCoverage': ['lateral_delt']}
        for reference in hashes]}

    contracts, conflicts = recipe_contracts._retained_contracts(
        [], receipt, hashes, {'lateral_delt'}, definitions)

    assert conflicts == []
    assert contracts['LIBRARY_0']['satisfiesCoverage'] == []
    assert contracts['LIBRARY_1']['satisfiesCoverage'] == ['lateral_delt']


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


def test_coverage_qualification_bounds_large_menus_and_checkpoints_each_batch(monkeypatch):
    equipment, _, _, stored, prepared = recipe_case(
        [{'key': 'push', 'description': 'A pushing movement', 'scope': 'eachSession'}])
    definitions = []
    for index in range(40):
        definition = copy.deepcopy(equipment['exerciseDefinitions'][0])
        definition['id'] = f'definition-{index:02d}'
        definitions.append(definition)
    equipment['exerciseDefinitions'] = definitions
    refs = [f'LIBRARY_{index}' for index in range(40)]
    prepared['definition_ids'] = refs
    prepared['candidates'] = {ref: definition for ref, definition in zip(refs, definitions)}
    calls, checkpoints = [], []

    def qualify(_, request, **kwargs):
        context = json.loads(request[-1]['content'])
        batch_refs = [recipe['definition_id'] for recipe in context['recipes']]
        calls.append(batch_refs)
        assert 1 <= len(batch_refs) <= 10
        schema_refs = kwargs['output_schema']['properties']['contracts']['items']['properties']['definition_id']['enum']
        assert schema_refs == batch_refs
        return json.dumps({'contracts': [
            {'definition_id': ref, 'satisfiesCoverage': ['push']} for ref in batch_refs]}), None, None

    monkeypatch.setattr(recipe_contracts, 'chat_call', qualify)
    result = recipe_contracts.qualify_recipe_contracts(None, prepared, stored, equipment, [], {},
        checkpoint=lambda receipt: checkpoints.append(receipt))

    assert len(calls) == 4
    assert {ref for batch in calls for ref in batch} == set(refs)
    assert len(set(ref for batch in calls for ref in batch)) == 40
    assert [len(receipt['contracts']) for receipt in checkpoints] == [10, 20, 30, 40]
    assert all(set(receipt['inputHashes']) == set(refs) for receipt in checkpoints)
    assert result['contracts'] == checkpoints[-1]['contracts']


def test_coverage_qualification_checkpoints_successful_batches_and_resumes_only_missing(monkeypatch):
    equipment, _, _, stored, prepared = recipe_case(
        [{'key': 'push', 'description': 'A pushing movement', 'scope': 'eachSession'}])
    definitions = []
    for index in range(40):
        definition = copy.deepcopy(equipment['exerciseDefinitions'][0])
        definition['id'] = f'definition-{index:02d}'
        definitions.append(definition)
    equipment['exerciseDefinitions'] = definitions
    refs = [f'LIBRARY_{index}' for index in range(40)]
    prepared['definition_ids'] = refs
    prepared['candidates'] = {ref: definition for ref, definition in zip(refs, definitions)}
    failed_once, calls, checkpoints = set(), [], []

    def qualify(_, request, **kwargs):
        context = json.loads(request[-1]['content'])
        batch_refs = [recipe['definition_id'] for recipe in context['recipes']]
        calls.append(batch_refs)
        if batch_refs[0] == 'LIBRARY_0' and 'LIBRARY_0' not in failed_once:
            failed_once.add('LIBRARY_0')
            raise RuntimeError('simulated failed qualification batch')
        return json.dumps({'contracts': [
            {'definition_id': ref, 'satisfiesCoverage': ['push']} for ref in batch_refs]}), None, None

    monkeypatch.setattr(recipe_contracts, 'chat_call', qualify)
    with pytest.raises(RuntimeError, match='simulated failed qualification batch'):
        recipe_contracts.qualify_recipe_contracts(None, prepared, stored, equipment, [], {},
            checkpoint=lambda receipt: checkpoints.append(receipt))

    assert len(checkpoints) == 3
    retained = checkpoints[-1]
    retained_refs = {item['definition_id'] for item in retained['contracts']}
    assert len(retained_refs) == 30
    assert 'LIBRARY_0' not in retained_refs
    first_attempt_count = len(calls)
    completed = recipe_contracts.qualify_recipe_contracts(None, prepared, stored, equipment, [], {}, retained)

    assert len(calls) - first_attempt_count == 1
    assert calls[-1] == ['LIBRARY_0'] + [f'LIBRARY_{index}' for index in range(1, 10)]
    assert {item['definition_id'] for item in completed['contracts']} == set(refs)


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


def test_recipe_roles_remain_pinned_to_first_valid_same_hash_batch_receipt(monkeypatch):
    equipment, _, _, stored, prepared = recipe_case(
        [{'key': 'push', 'description': 'A pushing movement', 'scope': 'eachSession'}])
    calls = []

    def qualify(_, request, **kwargs):
        context = json.loads(request[-1]['content'])
        calls.append(context)
        return json.dumps({'contracts': [
            {'definition_id': recipe['definition_id'],
             'satisfiesCoverage': ['push'] if len(calls) == 1 else []}
            for recipe in context['recipes']]}), None, None

    monkeypatch.setattr(recipe_contracts, 'chat_call', qualify)
    first_batch = copy.deepcopy(prepared)
    first_batch['definition_ids'] = ['LIBRARY_0']
    first_batch['candidates'] = {'LIBRARY_0': prepared['candidates']['LIBRARY_0']}
    first = recipe_contracts.qualify_recipe_contracts(
        None, first_batch, stored, equipment, [], {})

    drifted_receipt = copy.deepcopy(first)
    drifted_receipt['contracts'][0]['satisfiesCoverage'] = []
    # Reconstruct the first retained same-input result followed by the later
    # contradictory batch result.  The latter is also the caller's old cache.
    messages = [
        {'role': 'tool', 'content': json.dumps({'recipeQualification': first})},
        {'role': 'tool', 'content': json.dumps({'recipeQualification': drifted_receipt})},
    ]
    result = recipe_contracts.qualify_recipe_contracts(
        None, prepared, stored, equipment, messages, {}, drifted_receipt)

    assert len(calls) == 2
    assert first['inputHashes']['LIBRARY_0'] == result['inputHashes']['LIBRARY_0']
    assert [item['definition_id'] for item in calls[1]['recipes']] == ['LIBRARY_1']
    assert result['contracts'] == [
        {'definition_id': 'LIBRARY_0', 'satisfiesCoverage': ['push']},
        {'definition_id': 'LIBRARY_1', 'satisfiesCoverage': []},
    ]
    assert result['qualificationConflicts'] == [{
        'definition_id': 'LIBRARY_0',
        'inputHash': first['inputHashes']['LIBRARY_0'],
        'retainedRoles': ['push'],
        'conflictingRoles': [],
    }]


def test_passed_reviewed_role_replaces_old_base_pin_after_feedback_resolves(monkeypatch):
    equipment, _, _, stored, _ = recipe_case(
        [{'key': 'push', 'description': 'A pushing movement', 'scope': 'eachSession'}])
    messages = [
        {'role': 'user', 'content': 'Include a push movement in each session.'},
        {'role': 'assistant', 'tool_calls': [{'id': 'requirements', 'function': {
            'name': 'set_workout_requirements', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'requirements', 'content': json.dumps(stored)},
    ]
    workout = copy.deepcopy(recipe_case()[2][0])
    workout['exercises'] = [workout['exercises'][0]]
    responses = iter([[], ['push']])
    qualification_calls = []

    def qualify(_, request, **kwargs):
        context = json.loads(request[-1]['content'])
        qualification_calls.append(context)
        return json.dumps({'contracts': [{
            'definition_id': recipe['definition_id'], 'satisfiesCoverage': next(responses)}
            for recipe in context['recipes']]}), None, None

    monkeypatch.setattr(recipe_contracts, 'chat_call', qualify)
    initial_workouts, initial_receipt = allocation.qualify_workout_recipes(
        None, [workout], stored, equipment, messages)
    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': 'initial-qualification', 'function': {
            'name': 'draft_workout_sessions', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'initial-qualification', 'content': json.dumps({
            'recipeQualification': initial_receipt})},
    ])
    feedback = {'LIBRARY_0': [{'reason': 'Re-audit the assigned push role.'}]}
    corrected_workouts, corrected_receipt = allocation.qualify_workout_recipes(
        None, initial_workouts, stored, equipment, messages,
        review_feedback_by_definition=feedback)
    assert corrected_workouts[0]['exercises'][0]['satisfiesCoverage'] == ['push']
    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': 'corrected-qualification', 'function': {
            'name': 'draft_workout_sessions', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'corrected-qualification', 'content': json.dumps({
            'recipeQualification': corrected_receipt})},
    ])
    audited = {
        'passed': True, 'requirementsId': stored['requirementsId'],
        'libraryFingerprint': library_fingerprint(equipment), 'historyFingerprint': None,
        'resolvedDecisions': {}, 'submittedDraft': {
            'requirementsId': stored['requirementsId'], 'workouts': corrected_workouts},
        'recipeQualification': corrected_receipt, 'review': {'version': 1}, 'audit': {},
    }
    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': 'reviewed-audit', 'function': {
            'name': 'audit_workout_plan', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'reviewed-audit', 'content': json.dumps(audited)},
    ])
    monkeypatch.setattr(plan_review, '_require_review_receipt', lambda *args, **kwargs: None)
    monkeypatch.setattr(recipe_contracts, 'chat_call',
        lambda *args, **kwargs: pytest.fail('A current passed review already owns this role correction'))

    later_workouts, later_receipt = allocation.qualify_workout_recipes(
        None, corrected_workouts, stored, equipment, messages)

    assert qualification_calls
    assert initial_receipt['contracts'][0]['satisfiesCoverage'] == []
    assert corrected_receipt['contracts'][0]['satisfiesCoverage'] == ['push']
    assert later_workouts[0]['exercises'][0]['satisfiesCoverage'] == ['push']
    assert later_receipt['inputHashes']['LIBRARY_0'] == initial_receipt['inputHashes']['LIBRARY_0']
    assert later_receipt['contracts'] == [{'definition_id': 'LIBRARY_0', 'satisfiesCoverage': ['push']}]
    retained_definition_maps = []
    retain_contracts = recipe_contracts._retained_contracts
    def capture_retained_definitions(*args):
        retained_definition_maps.append(args[4])
        return retain_contracts(*args)
    monkeypatch.setattr(recipe_contracts, '_retained_contracts', capture_retained_definitions)
    comparison_context = allocation._joint_candidate_comparison_context(
        later_workouts, later_workouts, stored['requirements'], equipment, messages,
        None, {}, None, qualification=later_receipt)
    assert comparison_context['qualifiedRoleEvidence']['LIBRARY_0'] == ['push']
    assert retained_definition_maps[0]['LIBRARY_0']['id'] == equipment['exerciseDefinitions'][0]['id']


def test_audit_reuses_preparation_recipe_authority_after_unrelated_dialogue(monkeypatch):
    equipment, requirements, sessions, stored, prepared = recipe_case(
        [{'key': 'push', 'description': 'A pushing movement', 'scope': 'eachSession'}])
    source_snapshot = {
        'SOURCE_0': {'role': 'user', 'content': 'Use the approved push source.'},
        'SOURCE_1': {'role': 'assistant', 'content': 'Menu review question.'},
        'SOURCE_2': {'role': 'user', 'content': 'Accept this menu.'},
    }
    from workout_generator_pkg.exercise_library_tools import get_exercise_candidates
    candidates = get_exercise_candidates(
        {'definition_ids': prepared['definition_ids']}, equipment, [])['exercises']
    qualification_input = {**prepared, 'sourceMessages': source_snapshot,
        'candidates': {candidate['id']: candidate for candidate in candidates}}
    qualified_calls = []

    def qualify(_, request, **kwargs):
        context = json.loads(request[-1]['content'])
        qualified_calls.append(context)
        return json.dumps({'contracts': [
            {'definition_id': recipe['definition_id'], 'satisfiesCoverage': ['push']}
            for recipe in context['recipes']]}), None, None

    monkeypatch.setattr(recipe_contracts, 'chat_call', qualify)
    original = recipe_contracts.qualify_recipe_contracts(
        None, qualification_input, stored, equipment, [], {})
    assert original['inputHashes']['LIBRARY_0']

    preparation_id = 'prepared-menu'
    prep_authority = {
        'requirementsId': stored['requirementsId'],
        'libraryFingerprint': library_fingerprint(equipment),
        'historyFingerprint': None,
        'restrictionPolicy': copy.deepcopy(stored.get('restrictionPolicy')),
        'resolvedDecisions': {},
        'sourceMessages': source_snapshot,
    }
    preparation = {
        'preparationId': preparation_id, 'requirementsId': stored['requirementsId'],
        'baseDraftId': None, 'libraryFingerprint': library_fingerprint(equipment),
        'historyFingerprint': None, 'sourceMessages': source_snapshot,
        'sourceBudgetAuthority': prep_authority,
    }
    worker = {
        'preparationId': preparation_id, 'requirementsId': stored['requirementsId'],
        'baseDraftId': None, 'libraryFingerprint': library_fingerprint(equipment),
        'historyFingerprint': None, 'recipeQualification': original,
    }
    messages = [
        {'role': 'assistant', 'tool_calls': [{'id': 'requirements', 'function': {
            'name': 'set_workout_requirements', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'requirements', 'content': json.dumps(stored)},
        {'role': 'assistant', 'tool_calls': [{'id': 'preparation', 'function': {
            'name': 'prepare_workout_sessions', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'preparation', 'content': json.dumps(preparation)},
        {'role': 'assistant', 'tool_calls': [{'id': 'worker', 'function': {
            'name': 'draft_workout_sessions', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'worker', 'content': json.dumps(worker)},
        {'role': 'assistant', 'tool_calls': [{'id': 'decision', 'function': {
            'name': 'record_planning_decisions', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'decision', 'content': json.dumps({
            'passed': True, 'decisionReview': {'passed': True},
            'decisions': {'DECISION_0': {'choice': 'Accept the menu tradeoff.'}}})},
        {'role': 'assistant', 'content': 'Unrelated review and navigation dialogue.'},
        {'role': 'user', 'content': '/continue'},
    ]
    monkeypatch.setattr(recipe_contracts, 'chat_call',
        lambda *args, **kwargs: pytest.fail('The matching preparation already owns this recipe contract'))

    audited, receipt = allocation.qualify_workout_recipes(
        None, [sessions[0]], stored, equipment, messages, cached_qualification=original)

    assert receipt['inputHashes']['LIBRARY_0'] == original['inputHashes']['LIBRARY_0']
    assert receipt['contracts'] == original['contracts']
    assert audited[0]['exercises'][0]['satisfiesCoverage'] == ['push']
    assert len(qualified_calls) == 1


def test_changed_approved_requirements_do_not_reuse_preparation_recipe_contract(monkeypatch):
    equipment, requirements, sessions, stored, prepared = recipe_case(
        [{'key': 'push', 'description': 'A pushing movement', 'scope': 'eachSession'}])
    calls = []

    def qualify(_, request, **kwargs):
        context = json.loads(request[-1]['content'])
        calls.append(context)
        return json.dumps({'contracts': [
            {'definition_id': recipe['definition_id'], 'satisfiesCoverage': ['push']}
            for recipe in context['recipes']]}), None, None

    monkeypatch.setattr(recipe_contracts, 'chat_call', qualify)
    original = recipe_contracts.qualify_recipe_contracts(None, prepared, stored, equipment, [], {})
    changed_requirements = copy.deepcopy(requirements)
    changed_requirements['requiredCoverage'][0]['description'] = 'A horizontal pushing movement'
    changed = set_workout_requirements(changed_requirements,
        [{'role': 'user', 'content': 'Use a horizontal push movement.'}], equipment)
    source_snapshot = {'SOURCE_0': {'role': 'user', 'content': 'Earlier approved source.'}}
    preparation_id = 'old-preparation'
    source_authority = {
        'requirementsId': stored['requirementsId'],
        'libraryFingerprint': library_fingerprint(equipment),
        'historyFingerprint': None,
        'restrictionPolicy': copy.deepcopy(stored.get('restrictionPolicy')),
        'resolvedDecisions': {},
        'sourceMessages': source_snapshot,
    }
    preparation = {
        'preparationId': preparation_id, 'requirementsId': stored['requirementsId'],
        'baseDraftId': None, 'libraryFingerprint': library_fingerprint(equipment),
        'historyFingerprint': None, 'sourceMessages': source_snapshot,
        'sourceBudgetAuthority': source_authority,
    }
    worker = {
        'preparationId': preparation_id, 'requirementsId': stored['requirementsId'],
        'baseDraftId': None, 'libraryFingerprint': library_fingerprint(equipment),
        'historyFingerprint': None, 'recipeQualification': original,
    }
    messages = [
        {'role': 'assistant', 'tool_calls': [{'id': 'requirements', 'function': {
            'name': 'set_workout_requirements', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'requirements', 'content': json.dumps(changed)},
        {'role': 'assistant', 'tool_calls': [{'id': 'old-preparation-call', 'function': {
            'name': 'prepare_workout_sessions', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'old-preparation-call', 'content': json.dumps(preparation)},
        {'role': 'assistant', 'tool_calls': [{'id': 'old-worker-call', 'function': {
            'name': 'draft_workout_sessions', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'old-worker-call', 'content': json.dumps(worker)},
    ]
    approved_sources = allocation._recipe_qualification_source_messages(
        messages, changed, equipment, None)
    assert approved_sources != source_snapshot
    changed_context = {**prepared, 'sourceMessages': approved_sources}

    result = recipe_contracts.qualify_recipe_contracts(
        None, changed_context, changed, equipment, messages, {}, original)

    assert len(calls) == 2
    assert result['inputHashes']['LIBRARY_0'] != original['inputHashes']['LIBRARY_0']


@pytest.mark.parametrize('changed_authority', ['libraryFingerprint', 'historyFingerprint'])
def test_changed_library_or_history_does_not_reuse_preparation_recipe_context(changed_authority):
    equipment, _, _, stored, _ = recipe_case()
    source_snapshot = {'SOURCE_0': {'role': 'user', 'content': 'Prepared source snapshot.'}}
    old_library_fingerprint = library_fingerprint(equipment)
    old_history_fingerprint = None
    if changed_authority == 'libraryFingerprint':
        equipment['exerciseDefinitions'][0]['name'] += ' revised'
    history_fingerprint = 'new-history' if changed_authority == 'historyFingerprint' else None
    preparation_id = 'prepared-menu'
    authority = {
        'requirementsId': stored['requirementsId'],
        'libraryFingerprint': old_library_fingerprint,
        'historyFingerprint': old_history_fingerprint,
        'restrictionPolicy': copy.deepcopy(stored.get('restrictionPolicy')),
        'resolvedDecisions': {},
        'sourceMessages': source_snapshot,
    }
    preparation = {
        'preparationId': preparation_id, 'requirementsId': stored['requirementsId'],
        'baseDraftId': None, 'libraryFingerprint': old_library_fingerprint,
        'historyFingerprint': old_history_fingerprint, 'sourceMessages': source_snapshot,
        'sourceBudgetAuthority': authority,
    }
    worker = {
        'preparationId': preparation_id, 'requirementsId': stored['requirementsId'],
        'baseDraftId': None, 'libraryFingerprint': old_library_fingerprint,
        'historyFingerprint': old_history_fingerprint, 'recipeQualification': {'contracts': []},
    }
    messages = [
        {'role': 'assistant', 'tool_calls': [{'id': 'preparation', 'function': {
            'name': 'prepare_workout_sessions', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'preparation', 'content': json.dumps(preparation)},
        {'role': 'assistant', 'tool_calls': [{'id': 'worker', 'function': {
            'name': 'draft_workout_sessions', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'worker', 'content': json.dumps(worker)},
    ]

    source_messages = allocation._recipe_qualification_source_messages(
        messages, stored, equipment, history_fingerprint)
    approved_source_messages = allocation._recipe_qualification_source_messages(
        [], stored, equipment, history_fingerprint)

    assert source_messages == approved_source_messages
    assert source_messages != source_snapshot


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


def test_reviewed_metadata_overlay_preserves_unknowns_and_separates_regional_credits(monkeypatch):
    definition_id = '00000000-0000-0000-0000-000000000123'
    source = 'https://example.org/reviewed-exercise-evidence'
    monkeypatch.setattr(recipe_contracts, '_reviewed_exercise_annotations_by_definition', lambda: {
        definition_id: {
            'exerciseFamilyId': '00000000-0000-0000-0000-000000000321',
            'source': source,
            'basis': 'Controlled family fixture.',
            'anatomy': {
                'primarySubregions': ['deltoid_lateral'],
                'secondarySubregions': ['deltoid_lateral', 'deltoid_anterior'],
                'source': source,
                'basis': 'Controlled evidence fixture.',
            },
            'programmingDemands': {
                'axial_loading': {'present': True, 'source': source},
                'unsupported_trunk': {'present': False, 'source': source},
            },
        },
    })
    payload = {'exerciseDefinitions': [
        {'id': definition_id, 'name': 'Reviewed'},
        {'id': 'unreviewed', 'name': 'Unknown'},
    ]}

    overlaid = recipe_contracts.apply_reviewed_exercise_annotations(payload)
    reviewed, unknown = overlaid['exerciseDefinitions']

    from workout_generator_pkg.programming_demands import definition_demand_facts
    assert definition_demand_facts(reviewed)['axial_loading']['status'] == 'present'
    assert definition_demand_facts(reviewed)['unsupported_trunk']['status'] == 'absent'
    assert definition_demand_facts(reviewed)['eccentric_emphasis']['status'] == 'unknown'
    assert reviewed['reviewedExerciseFamily'] == {
        'exerciseFamilyId': '00000000-0000-0000-0000-000000000321',
        'source': source,
        'basis': 'Controlled family fixture.',
    }
    credits = recipe_contracts.regional_muscle_credits(reviewed, working_sets=4)
    assert credits == {'deltoid_lateral': 4, 'deltoid_anterior': 2.0}
    assert recipe_contracts.regional_muscle_credit_roles(reviewed, working_sets=4) == {
        'deltoid_anterior': {'direct': 0, 'indirect': 2.0},
        'deltoid_lateral': {'direct': 4, 'indirect': 0},
    }
    assert recipe_contracts.regional_muscle_credits({'id': definition_id}, working_sets=4) == credits
    facts = recipe_contracts.regional_muscle_facts(reviewed, working_sets=4)
    assert facts['deltoid_lateral']['status'] == 'present'
    assert facts['deltoid_lateral']['effectiveSets'] == 4
    assert facts['deltoid_anterior']['effectiveSets'] == 2.0
    projected = recipe_contracts.regional_muscle_facts({'libraryDefinitionId': definition_id}, 4)
    assert projected['deltoid_lateral']['source'] == source
    exported = recipe_contracts.regional_muscle_facts({
        'id': '00000000-0000-0000-0000-000000000999',
        'exerciseDefinitionId': definition_id,
    }, 4)
    raw_definition = recipe_contracts.regional_muscle_facts({'id': definition_id}, 4)
    assert exported == projected == raw_definition
    assert facts['latissimus_dorsi']['status'] == 'unknown'
    assert recipe_contracts.regional_muscle_credits(unknown) == {}
    assert recipe_contracts.regional_muscle_credits({'id': 'unreviewed'}) == {}
    assert payload['exerciseDefinitions'][0].get('anatomy') is None
    assert payload['exerciseDefinitions'][1].get('programmingDemands') is None
