import copy
import json

import pytest
from jsonschema import Draft7Validator, ValidationError

from workout_generator_pkg import joint_planning, recipe_contracts, plan_review, session_drafting
from workout_generator_pkg.planning_tools import (
    build_draft_plan, library_fingerprint, placement_notes_text_contract,
    set_workout_requirements, PlanningInputError,
)
from test_workout_generator_planning_tools import planning_case, requirement_messages


def progression_case():
    equipment, requirements, _, draft = planning_case()
    equipment['equipments'] = [{'id': 'EQUIPMENT_0', 'name': 'Weight vest', 'type': 'WEIGHTVEST',
        'availableWeights': [{'weight': value} for value in range(1, 21)]}]
    weighted = copy.deepcopy(equipment['exerciseDefinitions'][0])
    weighted.update(id='weighted_press', name='Weighted Push-Up', equipmentId='EQUIPMENT_0')
    equipment['exerciseDefinitions'].append(weighted)
    requirements['sessionsPerWeek'] = 3
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 15, 'maximum': 18}
    sessions = []
    for index in range(3):
        day = copy.deepcopy(draft['workouts'][0])
        day.update(name=f'Day {index}', trainingDays=[2 * index])
        first = day['exercises'][0]
        first.update(numWorkSets=5, workSetTemplate={'reps': 8, 'additionalWeight': 0})
        second = copy.deepcopy(first)
        second.update(definition_id='LIBRARY_1', numWorkSets=1)
        day['exercises'].append(second)
        sessions.append(day)
    return equipment, requirements, sessions


def test_available_gear_is_not_silently_attached_to_a_fixed_configuration():
    equipment, _, _ = progression_case()
    plain, weighted = equipment['exerciseDefinitions']
    fixed = recipe_contracts.progression_capability(plain, equipment)
    loadable = recipe_contracts.progression_capability(weighted, equipment)
    assert fixed['selectableLoadsKg'] == [0] and not fixed['supportsLoadProgression']
    assert loadable['supportsLoadProgression'] and loadable['maximumSelectableLoadKg'] == 20
    with pytest.raises(ValueError, match='unavailable'):
        recipe_contracts.validate_progression_plan({'kind': 'load', 'nextDefinitionId': None,
            'nextDefinitionName': None}, plain, equipment, {})


def test_progression_target_must_share_a_primary_muscle():
    equipment, _, _ = progression_case()
    plain, target = equipment['exerciseDefinitions']
    target['muscleGroups'] = ['hamstrings']
    with pytest.raises(ValueError, match='share a primary muscle group'):
        recipe_contracts.validate_progression_plan({'kind': 'reps', 'nextDefinitionId': 'LIBRARY_1',
            'nextDefinitionName': target['name'], 'atCeilingAction': 're_audit_variant'}, plain, equipment, {})


def test_unknown_headroom_remains_unknown_and_starting_load_takes_precedence():
    equipment, _, sessions = progression_case()
    definition = equipment['exerciseDefinitions'][1]
    capability = recipe_contracts.progression_capability(definition, equipment)
    unknown = recipe_contracts.progression_margin({}, capability)
    assert unknown['status'] == 'unknown' and unknown['remainingLoadSteps'] is None
    capability['observedLoadKg'] = 20
    margin = recipe_contracts.progression_margin(sessions[0]['exercises'][1], capability)
    assert margin['status'] == 'load_headroom' and margin['referenceLoadKg'] == 0
    assert margin['remainingLoadSteps'] > 0


def test_headroom_selection_overrides_original_choice_without_breaking_targets():
    equipment, requirements, sessions = progression_case()
    requirements['objectiveOrder'] = ['progression', 'preservation']
    before = copy.deepcopy(sessions)
    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment)
    assert result['feasible'], result
    assert all(item['definition_id'] == 'LIBRARY_1' for day in result['sessions'] for item in day['exercises'])
    assert 15 <= result['audit']['weeklyVolume']['chest']['effective'] <= 18
    assert all(day['estimatedSeconds'] <= 1000 for day in result['audit']['workouts'])
    assert all(margin['status'] == 'load_headroom' for margin in result['progressionMargins'])
    assert sessions == before


def test_overload_preference_cannot_override_source_required_movements():
    equipment, requirements, sessions = progression_case()
    requirements['requiredCoverage'] = [{'key': 'mandatory', 'description': 'Unweighted movement required', 'scope': 'eachSession'}]
    requirements['executionRules'] = [{'kind': 'workSets', 'coverageKey': 'mandatory', 'minimumSets': 5, 'maximumSets': 5}]
    for day in sessions:
        day['exercises'][0]['satisfiesCoverage'] = ['mandatory']
    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment)
    assert result['feasible'], result
    assert all(day['exercises'][0]['definition_id'] == 'LIBRARY_0' for day in result['sessions'])
    assert all(day['exercises'][0]['numWorkSets'] == 5 for day in result['sessions'])


def test_structured_progression_is_rendered_and_validated_with_the_notes_budget():
    equipment, requirements, sessions = progression_case()
    item = sessions[0]['exercises'][0]
    item.pop('workSetTemplate')
    item.update(progressionMethod='sourceDefined',
        progressionPlan={'kind': 'variant', 'nextDefinitionId': 'LIBRARY_1', 'nextDefinitionName': 'Weighted Push-Up'})
    plan = build_draft_plan({'name': 'Test', 'workouts': [sessions[0]]}, equipment, requirements)
    assert 'select Weighted Push-Up and re-audit before use' in plan['exercises'][0]['placementNotes']
    assert 'progressionPlan' not in plan['exercises'][0]  # Application output stays on the existing schema.
    contract = placement_notes_text_contract(item)
    assert 'Weighted Push-Up' in contract['generatedText']
    assert contract['maximumCharacters'] == 500 and contract['reservedCharacters'] == 0
    assert contract['exportMaximumCharacters'] == 500 + len(contract['generatedText'])
    invalid = copy.deepcopy(item['progressionPlan'])
    invalid['nextDefinitionName'] = 'Unconfirmed equipment'
    with pytest.raises(ValueError, match='canonical name'):
        recipe_contracts.validate_progression_plan(invalid, equipment['exerciseDefinitions'][0], equipment, {})
    with pytest.raises(ValueError, match='excluded'):
        recipe_contracts.validate_progression_plan(item['progressionPlan'], equipment['exerciseDefinitions'][0], equipment,
            {'excludedDefinitionIds': ['weighted_press']})


def test_progression_notes_name_the_ceiling_for_the_selected_progression_unit():
    reps = recipe_contracts.progression_note({'kind': 'reps', 'nextDefinitionId': None,
        'nextDefinitionName': None, 'atCeilingAction': 're_audit_higher_reps'})
    duration = recipe_contracts.progression_note({'kind': 'duration', 'nextDefinitionId': None,
        'nextDefinitionName': None, 'atCeilingAction': 're_audit_longer_duration'})
    load = recipe_contracts.progression_note({'kind': 'load', 'nextDefinitionId': None,
        'nextDefinitionName': None, 'atCeilingAction': 're_audit_higher_reps'})

    assert 'top of the prescribed range' in reps and 'maximum selectable load' not in reps
    assert 'duration ceiling' in duration and 'remains too easy at' in duration
    assert 'remains too easy at the maximum selectable load' in load


def test_progression_schema_enforces_units_and_named_paired_variant_targets():
    validator = Draft7Validator(recipe_contracts.PROGRESSION_PLAN_SCHEMA)
    assert validator.is_valid({'kind': 'variant', 'nextDefinitionId': 'LIBRARY_1',
        'nextDefinitionName': 'Weighted Push-Up'})
    assert validator.is_valid({'kind': 'reps', 'nextDefinitionId': 'LIBRARY_1',
        'nextDefinitionName': 'Weighted Push-Up'})  # Legacy named target with no ceiling action.
    assert not validator.is_valid({'kind': 'variant', 'nextDefinitionId': None,
        'nextDefinitionName': None})
    assert not validator.is_valid({'kind': 'reps', 'nextDefinitionId': None,
        'nextDefinitionName': None, 'atCeilingAction': 're_audit_variant'})
    assert not validator.is_valid({'kind': 'duration', 'nextDefinitionId': None,
        'nextDefinitionName': None, 'atCeilingAction': 're_audit_higher_reps'})
    assert not validator.is_valid({'kind': 'reps', 'nextDefinitionId': 'LIBRARY_1',
        'nextDefinitionName': None})
    assert not validator.is_valid({'kind': 'reps', 'nextDefinitionId': 'LIBRARY_1',
        'nextDefinitionName': 'Weighted Push-Up', 'atCeilingAction': 're_audit_higher_reps'})
    assert not validator.is_valid({'kind': 'duration', 'nextDefinitionId': 'LIBRARY_1',
        'nextDefinitionName': 'Timed Variant', 'atCeilingAction': 're_audit_longer_duration'})


def test_runtime_progression_validation_rejects_conflicting_named_target_route():
    equipment, _, _ = progression_case()
    with pytest.raises(ValidationError):
        recipe_contracts.validate_progression_plan({'kind': 'reps', 'nextDefinitionId': 'LIBRARY_1',
            'nextDefinitionName': 'Weighted Push-Up', 'atCeilingAction': 're_audit_higher_reps'},
            equipment['exerciseDefinitions'][0], equipment, {})


def test_qualified_progression_schema_is_provider_compatible_and_requires_variant_target():
    schema = recipe_contracts._qualified_progression_schema()
    validator = Draft7Validator(schema)
    for branch in schema['anyOf']:
        assert set(branch['properties']) == set(branch['required'])
        assert 'maxLength' not in branch['properties']['nextDefinitionName']
    assert validator.is_valid({'kind': 'reps', 'nextDefinitionId': None,
        'nextDefinitionName': None, 'atCeilingAction': 're_audit_higher_reps'})
    assert validator.is_valid({'kind': 'reps', 'nextDefinitionId': 'LIBRARY_1',
        'nextDefinitionName': 'Weighted Push-Up', 'atCeilingAction': 're_audit_variant'})
    assert not validator.is_valid({'kind': 'reps', 'nextDefinitionId': None,
        'nextDefinitionName': None, 'atCeilingAction': 're_audit_variant'})
    assert not validator.is_valid({'kind': 'duration', 'nextDefinitionId': None,
        'nextDefinitionName': None, 'atCeilingAction': 're_audit_higher_reps'})


def test_descriptions_follow_solved_units_and_reserve_the_full_schedule():
    _, requirements, sessions = progression_case()
    day = sessions[0]
    day.update(description='Vertical pull only', trainingDays=[0, 2, 4])
    assert recipe_contracts.solved_description(day, requirements) == 'Strength'
    day['exercises'][0]['durationSeconds'] = 30
    assert recipe_contracts.solved_description(day, requirements) == 'Mixed'


def test_empty_unknown_review_metadata_is_repaired_locally_but_meaningful_data_is_not(monkeypatch):
    finding = {'severity': 'blocking', 'basis': 'established_violation', 'path': '/draft',
        'message': 'Keep this blocker.', 'evidencePaths': ['/draft'], 'repair': 'Correct it.', 'action': 'repair',
        'decisionId': None, 'newConflictEvidencePaths': [], 'muscleTargets': [], 'newConflictErrorPaths': []}
    monkeypatch.setattr(plan_review, 'chat_call', lambda *a, **k: pytest.fail('Empty metadata needs no model call'))
    findings = plan_review._validated_findings(None, [], json.dumps({'findings': [finding]}), lambda item: item,
        None, 'test')
    assert findings[0]['severity'] == 'blocking' and 'newConflictErrorPaths' not in findings[0]
    assert 'newConflictErrorPaths' in finding
    finding['newConflictErrorPaths'] = ['/actual/evidence']
    monkeypatch.setattr(plan_review, 'chat_call', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('Substantive repair needed')))
    with pytest.raises(plan_review.ReviewOutputError):
        plan_review._validated_findings(None, [], json.dumps({'findings': [finding]}), lambda item: item, None, 'test')


def test_qualification_is_shared_cached_and_rejects_invented_progression(monkeypatch):
    equipment, requirements, _ = progression_case()
    stored = set_workout_requirements(requirements, [{'role': 'user', 'content': 'Use chest exercises with progression.'}], equipment)
    prepared = {'definition_ids': ['LIBRARY_0'], 'candidates': {'LIBRARY_0': equipment['exerciseDefinitions'][0]},
        'sourceMessages': [], 'libraryFingerprint': library_fingerprint(equipment)}
    calls = []
    def qualify(*args, **kwargs):
        def explicit_types(schema):
            assert any(key in schema for key in ('type', 'anyOf', '$ref'))
            for child in schema.get('properties', {}).values():
                explicit_types(child)
            if 'items' in schema:
                explicit_types(schema['items'])
        explicit_types(kwargs['output_schema'])
        calls.append(1)
        return json.dumps({'contracts': [{'definition_id': 'LIBRARY_0' ,
            'progressionPlan': {'kind': 'reps', 'nextDefinitionId': 'LIBRARY_1', 'nextDefinitionName': 'Weighted Push-Up',
                                'atCeilingAction': 're_audit_variant'}}]}), None, None
    monkeypatch.setattr(recipe_contracts, 'chat_call', qualify)
    result = recipe_contracts.qualify_recipe_contracts(None, prepared, stored, equipment, [], {})
    assert len(calls) == 1
    assert recipe_contracts.qualify_recipe_contracts(None, prepared, stored, equipment, [], {}, result) == result
    assert len(calls) == 1
    bad = copy.deepcopy(result)
    bad['contracts'][0]['progressionPlan']['kind'] = 'load'
    repaired = recipe_contracts.qualify_recipe_contracts(None, prepared, stored, equipment, [], {}, bad)
    assert len(calls) == 2 and repaired['contracts'][0]['progressionPlan']['kind'] == 'reps'


def test_provider_omits_unsupported_empty_coverage_field_and_backend_injects_it(monkeypatch):
    equipment, requirements, _ = progression_case()
    requirements['requiredCoverage'] = []
    stored = set_workout_requirements(requirements,
        [{'role': 'user', 'content': 'Use chest exercises with progression.'}], equipment)
    prepared = {'definition_ids': ['LIBRARY_0'], 'candidates': {'LIBRARY_0': equipment['exerciseDefinitions'][0]},
        'sourceMessages': [], 'libraryFingerprint': library_fingerprint(equipment)}
    calls = []

    def qualify(client, request, **kwargs):
        provider_schema = kwargs['output_schema']['properties']['contracts']['items']
        assert 'satisfiesCoverage' not in provider_schema['properties']
        assert 'satisfiesCoverage' not in provider_schema['required']
        calls.append(request)
        return json.dumps({'contracts': [{'definition_id': 'LIBRARY_0',
            'progressionPlan': {'kind': 'reps', 'nextDefinitionId': None, 'nextDefinitionName': None,
                                'atCeilingAction': 're_audit_higher_reps'}}]}), None, None

    monkeypatch.setattr(recipe_contracts, 'chat_call', qualify)
    result = recipe_contracts.qualify_recipe_contracts(None, prepared, stored, equipment, [], {})

    assert len(calls) == 1
    assert result['contracts'][0]['satisfiesCoverage'] == []


@pytest.mark.parametrize('omit_muscles', [False, True])
def test_unannotated_library_entry_does_not_block_qualification(monkeypatch, omit_muscles):
    equipment, requirements, _ = progression_case()
    unannotated = copy.deepcopy(equipment['exerciseDefinitions'][0])
    unannotated.update(id='zz_unannotated', name='Unannotated movement', muscleGroups=None)
    if omit_muscles:
        unannotated.pop('muscleGroups')
    equipment['exerciseDefinitions'].append(unannotated)
    stored = set_workout_requirements(requirements,
        [{'role': 'user', 'content': 'Use chest exercises with progression.'}], equipment)
    prepared = {'definition_ids': ['LIBRARY_0'],
        'candidates': {'LIBRARY_0': equipment['exerciseDefinitions'][0]},
        'sourceMessages': [], 'libraryFingerprint': library_fingerprint(equipment)}
    calls = []

    def qualify(_, request, **kwargs):
        context = json.loads(request[-1]['content'])
        calls.append(context)
        assert set(context['eligibleProgressionTargets']) == {'LIBRARY_1'}
        return json.dumps({'contracts': [{'definition_id': 'LIBRARY_0',
            'progressionPlan': {'kind': 'reps', 'nextDefinitionId': None,
                'nextDefinitionName': None, 'atCeilingAction': 're_audit_higher_reps'}}]}), None, None

    monkeypatch.setattr(recipe_contracts, 'chat_call', qualify)
    result = recipe_contracts.qualify_recipe_contracts(None, prepared, stored, equipment, [], {})
    assert len(calls) == 1 and len(result['contracts']) == 1
    plan = {'kind': 'reps', 'nextDefinitionId': 'LIBRARY_2',
        'nextDefinitionName': unannotated['name'], 'atCeilingAction': 're_audit_variant'}
    with pytest.raises(ValueError, match='share a primary muscle'):
        recipe_contracts.validate_progression_plan(plan, equipment['exerciseDefinitions'][0], equipment, {})
    equipment['exerciseDefinitions'][0]['muscleGroups'] = None
    plan.update(nextDefinitionId='LIBRARY_1', nextDefinitionName=equipment['exerciseDefinitions'][1]['name'])
    with pytest.raises(ValueError, match='share a primary muscle'):
        recipe_contracts.validate_progression_plan(plan, equipment['exerciseDefinitions'][0], equipment, {})


def test_provider_still_must_assign_nonempty_approved_coverage_roles(monkeypatch):
    equipment, requirements, _ = progression_case()
    requirements['requiredCoverage'] = [{'key': 'press', 'description': 'Press', 'scope': 'eachSession'}]
    stored = set_workout_requirements(requirements,
        [{'role': 'user', 'content': 'Include a press in every session.'}], equipment)
    prepared = {'definition_ids': ['LIBRARY_0'], 'candidates': {'LIBRARY_0': equipment['exerciseDefinitions'][0]},
        'sourceMessages': [], 'libraryFingerprint': library_fingerprint(equipment)}
    def qualify(client, request, **kwargs):
        item = kwargs['output_schema']['properties']['contracts']['items']
        assert 'satisfiesCoverage' in item['required']
        assert item['properties']['satisfiesCoverage']['items']['enum'] == ['press']
        return json.dumps({'contracts': [{'definition_id': 'LIBRARY_0', 'satisfiesCoverage': ['press'],
            'progressionPlan': {'kind': 'reps', 'nextDefinitionId': None, 'nextDefinitionName': None,
                                'atCeilingAction': 're_audit_higher_reps'}}]}), None, None
    monkeypatch.setattr(recipe_contracts, 'chat_call', qualify)

    result = recipe_contracts.qualify_recipe_contracts(None, prepared, stored, equipment, [], {})

    assert result['contracts'][0]['satisfiesCoverage'] == ['press']


def test_feedback_qualification_does_not_generate_or_replace_local_notes(monkeypatch):
    equipment, requirements, _ = progression_case()
    stored = set_workout_requirements(requirements, [{'role': 'user', 'content': 'Use chest exercises with progression.'}], equipment)
    prepared = {'definition_ids': ['LIBRARY_0'], 'candidates': {'LIBRARY_0': equipment['exerciseDefinitions'][0]},
        'sourceMessages': [], 'libraryFingerprint': library_fingerprint(equipment),
        'reviewFeedback': {'findings': [{'message': 'LIBRARY_0 needs a source-compatible progression route.'}]}}
    seen = []

    def assert_strict_schema(schema):
        if schema.get('type') == 'object':
            assert set(schema.get('properties', {})) == set(schema.get('required', []))
            assert schema.get('additionalProperties') is False
            for child in schema.get('properties', {}).values():
                assert_strict_schema(child)
        if 'items' in schema:
            assert_strict_schema(schema['items'])
        for branch in schema.get('oneOf', []):
            assert_strict_schema(branch)

    def qualify(client, request, **kwargs):
        schema = kwargs['output_schema']
        assert_strict_schema(schema)
        assert 'portableNotes' not in schema['properties']['contracts']['items']['properties']
        seen.append(schema)
        return json.dumps({'contracts': [{'definition_id': 'LIBRARY_0' ,
            'progressionPlan': {'kind': 'reps', 'nextDefinitionId': None, 'nextDefinitionName': None,
                                'atCeilingAction': 're_audit_higher_reps'}}]}), None, None

    monkeypatch.setattr(recipe_contracts, 'chat_call', qualify)
    result = recipe_contracts.qualify_recipe_contracts(None, prepared, stored, equipment, [], {})
    assert seen and 'portableNotes' not in result['contracts'][0]


def test_recipe_property_cache_ignores_unrelated_local_note_edits(monkeypatch):
    equipment, requirements, _ = progression_case()
    stored = set_workout_requirements(requirements, [{'role': 'user', 'content': 'Use chest exercises with progression.'}], equipment)
    prepared = {'definition_ids': ['LIBRARY_0'], 'candidates': {'LIBRARY_0': equipment['exerciseDefinitions'][0]},
        'sourceMessages': [], 'libraryFingerprint': library_fingerprint(equipment),
        'existingCoachingNotes': {'LIBRARY_0': ['Original cue: work sets at 2-3 RIR.']}}
    calls = []
    def qualify(client, request, **kwargs):
        calls.append(request)
        return json.dumps({'contracts': [{'definition_id': 'LIBRARY_0' ,
            'progressionPlan': {'kind': 'reps', 'nextDefinitionId': None, 'nextDefinitionName': None,
                                'atCeilingAction': 're_audit_higher_reps'}}]}), None, None
    monkeypatch.setattr(recipe_contracts, 'chat_call', qualify)
    first = recipe_contracts.qualify_recipe_contracts(None, prepared, stored, equipment, [], {})
    edited = copy.deepcopy(prepared)
    edited['existingCoachingNotes']['LIBRARY_0'] = ['Updated cue: work sets at 2 RIR.']
    reused = recipe_contracts.qualify_recipe_contracts(None, edited, stored, equipment, [], {}, first)
    assert len(calls) == 1 and reused == first


def test_qualification_returns_exact_semantic_error_once_and_stays_bounded(monkeypatch):
    equipment, requirements, _ = progression_case()
    stored = set_workout_requirements(requirements, [{'role': 'user', 'content': 'Use chest exercises with progression.'}], equipment)
    prepared = {'definition_ids': ['LIBRARY_0'], 'candidates': {'LIBRARY_0': equipment['exerciseDefinitions'][0]},
        'sourceMessages': [], 'libraryFingerprint': library_fingerprint(equipment)}
    calls = []
    def qualify(client, request, **kwargs):
        calls.append(copy.deepcopy(request))
        return json.dumps({'contracts': [{'definition_id': 'LIBRARY_0' ,
            'progressionPlan': {'kind': 'reps', 'nextDefinitionId': None,
                                'nextDefinitionName': 'Invented name' if len(calls) == 1 else None,
                                'atCeilingAction': 're_audit_higher_reps'}}]}), None, None
    monkeypatch.setattr(recipe_contracts, 'chat_call', qualify)
    result = recipe_contracts.qualify_recipe_contracts(None, prepared, stored, equipment, [], {})
    assert len(calls) == 2
    assert 'nextDefinitionId and nextDefinitionName must both be null' in calls[1][-1]['content']
    assert result['contracts'][0]['progressionPlan']['nextDefinitionName'] is None
    calls.clear()
    def always_invalid(*args, **kwargs):
        calls.append(1)
        return json.dumps({'contracts': []}), None, None
    monkeypatch.setattr(recipe_contracts, 'chat_call', always_invalid)
    with pytest.raises(Exception):
        recipe_contracts.qualify_recipe_contracts(None, prepared, stored, equipment, [], {})
    assert len(calls) == 2


def test_definition_cache_ignores_global_edits_and_requalifies_only_changed_dependencies(monkeypatch):
    equipment, requirements, _ = progression_case()
    extra = copy.deepcopy(equipment['exerciseDefinitions'][1])
    extra.update(id='weighted_press_variant', name='Weighted Press Variant')
    equipment['exerciseDefinitions'].append(extra)
    stored = set_workout_requirements(requirements, [{'role': 'user', 'content': 'Use chest exercises with progression.'}], equipment)
    prepared = {'definition_ids': ['LIBRARY_0', 'LIBRARY_1'],
        'candidates': {'LIBRARY_0': equipment['exerciseDefinitions'][0], 'LIBRARY_1': equipment['exerciseDefinitions'][1]},
        'sourceMessages': [], 'libraryFingerprint': library_fingerprint(equipment)}
    requests = []

    def qualify(_, request, **kwargs):
        payload = json.loads(request[-1]['content'])
        recipes = payload['recipes']
        requests.append([recipe['definition_id'] for recipe in recipes])
        available = payload['eligibleProgressionTargets']
        contracts = []
        for recipe in recipes:
            ref = recipe['definition_id']
            target = ('LIBRARY_2' if ref == 'LIBRARY_0' and 'LIBRARY_2' in recipe['eligibleProgressionTargetIds']
                      else None)
            contracts.append({'definition_id': ref , 'progressionPlan': {
                'kind': 'reps', 'nextDefinitionId': target,
                'nextDefinitionName': available[target]['name'] if target else None,
                'atCeilingAction': 're_audit_variant' if target else 're_audit_higher_reps'}})
        return json.dumps({'contracts': contracts}), None, None

    monkeypatch.setattr(recipe_contracts, 'chat_call', qualify)
    cached = recipe_contracts.qualify_recipe_contracts(None, prepared, stored, equipment, [], {})
    assert requests == [['LIBRARY_0', 'LIBRARY_1']]

    changed_requirements = copy.deepcopy(stored)
    changed_requirements['requirements']['objectiveOrder'] = ['progression', 'preservation']
    changed_requirements['requirements']['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 16, 'maximum': 19}
    recipe_contracts.qualify_recipe_contracts(None, prepared, changed_requirements, equipment, [], {}, cached)
    assert len(requests) == 1  # Objective order, title-level context and numeric targets do not qualify a recipe.

    equipment['equipments'][0]['availableWeights'].append({'weight': 21})
    prepared['libraryFingerprint'] = library_fingerprint(equipment)
    cached = recipe_contracts.qualify_recipe_contracts(None, prepared, stored, equipment, [], {}, cached)
    assert requests[-1] == ['LIBRARY_1']  # Only the selected setup whose selectable loads changed.

    equipment['exerciseDefinitions'] = equipment['exerciseDefinitions'][:-1]
    prepared['libraryFingerprint'] = library_fingerprint(equipment)
    cached = recipe_contracts.qualify_recipe_contracts(None, prepared, stored, equipment, [], {}, cached)
    assert requests[-1] == ['LIBRARY_0', 'LIBRARY_1']  # Both chest recipes depended on this eligible target.

    history_fingerprint = 'history-new'
    evidence_messages = [
        {'role': 'assistant', 'tool_calls': [{'id': 'evidence', 'function': {'name': 'get_training_evidence'}}]},
        {'role': 'tool', 'tool_call_id': 'evidence', 'content': json.dumps({
            'historyFingerprint': history_fingerprint, 'libraryFingerprint': prepared['libraryFingerprint'],
            'exercises': [{'definitionId': 'weighted_press', 'status': 'observed',
                           'loadHeadroom': {'latestSessionHeaviestLoadKg': 12}}]})}]
    recipe_contracts.qualify_recipe_contracts(None, prepared, stored, equipment, evidence_messages,
        {'historyFingerprint': history_fingerprint}, cached)
    assert requests[-1] == ['LIBRARY_1']  # Only the definition with new athlete evidence.


def test_unrelated_new_progression_target_does_not_invalidate_recipe_cache(monkeypatch):
    equipment, requirements, _ = progression_case()
    target = copy.deepcopy(equipment['exerciseDefinitions'][0])
    target.update(id='zz_hamstring', name='Hamstring Movement', muscleGroups=['hamstrings'],
                  equipmentId='UNAVAILABLE_EQUIPMENT')
    equipment['exerciseDefinitions'].append(target)
    stored = set_workout_requirements(requirements, [{'role': 'user', 'content': 'Use chest exercises.'}], equipment)
    prepared = {'definition_ids': ['LIBRARY_0', 'LIBRARY_1'],
        'candidates': {'LIBRARY_0': equipment['exerciseDefinitions'][0], 'LIBRARY_1': equipment['exerciseDefinitions'][1]},
        'sourceMessages': [], 'libraryFingerprint': library_fingerprint(equipment)}
    requests = []

    def qualify(_, request, **kwargs):
        payload = json.loads(request[-1]['content'])
        requests.append([recipe['definition_id'] for recipe in payload['recipes']])
        return json.dumps({'contracts': [{'definition_id': recipe['definition_id'],
            'progressionPlan': {'kind': 'reps', 'nextDefinitionId': None, 'nextDefinitionName': None,
                                'atCeilingAction': 're_audit_higher_reps'}}
            for recipe in payload['recipes']]}), None, None

    monkeypatch.setattr(recipe_contracts, 'chat_call', qualify)
    cached = recipe_contracts.qualify_recipe_contracts(None, prepared, stored, equipment, [], {})
    equipment['equipments'].append({'id': 'UNAVAILABLE_EQUIPMENT', 'name': 'Unused Equipment', 'type': 'MACHINE'})
    prepared['libraryFingerprint'] = library_fingerprint(equipment)
    recipe_contracts.qualify_recipe_contracts(None, prepared, stored, equipment, [], {}, cached)
    assert requests == [['LIBRARY_0', 'LIBRARY_1']]


def test_recipe_qualification_rejects_duplicate_definition_ids():
    equipment, requirements, _ = progression_case()
    stored = set_workout_requirements(requirements, [{'role': 'user', 'content': 'Use chest exercises.'}], equipment)
    prepared = {'definition_ids': ['LIBRARY_0', 'LIBRARY_0'],
        'candidates': {'LIBRARY_0': equipment['exerciseDefinitions'][0]},
        'sourceMessages': [], 'libraryFingerprint': library_fingerprint(equipment)}
    with pytest.raises(ValueError, match='exactly once'):
        recipe_contracts.qualify_recipe_contracts(None, prepared, stored, equipment, [], {})


def test_qualification_request_sends_shared_large_context_once(monkeypatch):
    equipment, requirements, _ = progression_case()
    base = copy.deepcopy(equipment['exerciseDefinitions'][0])
    for index in range(2, 306):
        definition = copy.deepcopy(base)
        definition.update(id=f'candidate_{index:03}', name=f'Candidate {index} Push-Up')
        equipment['exerciseDefinitions'].append(definition)
    ordered = sorted(equipment['exerciseDefinitions'], key=lambda item: item['id'])
    refs = [f'LIBRARY_{index}' for index in range(16)]
    stored = set_workout_requirements(requirements, [{'role': 'user', 'content': 'Use chest exercises with progression.'}], equipment)
    stored['requirements']['requirementAccounting'] = [{
        'instruction': 'Every selected movement should support continued progression. ' * 20,
        'sourceReferences': ['SOURCE_0'], 'requirementPaths': [], 'priority': 'preference',
        'enforcement': 'semantic_check', 'reason': 'movement-specific progression'}]
    prepared = {'definition_ids': refs,
        'candidates': {ref: ordered[index] for index, ref in enumerate(refs)},
        'sourceMessages': {'SOURCE_0': {'role': 'user', 'content': 'Source instruction. ' * 100}},
        'libraryFingerprint': library_fingerprint(equipment)}
    captured = {}

    def qualify(_, request, **kwargs):
        context = json.loads(request[-1]['content'])
        captured['context'] = context
        return json.dumps({'contracts': [{'definition_id': recipe['definition_id'] ,
            'progressionPlan': {'kind': 'reps', 'nextDefinitionId': None, 'nextDefinitionName': None,
                                'atCeilingAction': 're_audit_higher_reps'}} for recipe in context['recipes']]}), None, None

    monkeypatch.setattr(recipe_contracts, 'chat_call', qualify)
    recipe_contracts.qualify_recipe_contracts(None, prepared, stored, equipment, [], {})
    context = captured['context']
    assert len(context['eligibleProgressionTargets']) == 306
    assert len(context['sourceMessages']) == 1 and context['semanticRequirements']
    assert all('eligibleProgressionTargetIds' in recipe and 'eligibleProgressionTargets' not in recipe
               and 'sourceMessages' not in recipe
               and 'requirements' not in recipe and 'semanticRequirements' not in recipe
               for recipe in context['recipes'])
    shared_size = len(json.dumps({key: value for key, value in context.items() if key != 'recipes'}))
    actual_size = len(json.dumps(context))
    naive_repeated_size = shared_size * len(context['recipes']) + len(json.dumps(context['recipes']))
    assert actual_size < naive_repeated_size / 4
