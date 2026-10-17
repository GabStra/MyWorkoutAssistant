import copy
import json

import pytest
from jsonschema import Draft7Validator

from workout_generator_pkg import cli, interactive_shell as shell
from workout_generator_pkg.constants import BASE_SYSTEM_PROMPT, SCHEMA_REPAIR_INSTRUCTION, SELF_HEAL_SYSTEM_PROMPT
from workout_generator_pkg.domain_ops import fix_equipment_errors, fix_set_errors, fix_timed_sets, SchemaRepairError, validate_schema_repair
from workout_generator_pkg.muscle_roles import MUSCLE_ROLE_GUIDANCE
from workout_generator_pkg.planner_context import request_planning_state
from workout_generator_pkg.stage_prompts import EQUIPMENT_SYSTEM_PROMPT, PLAN_INDEX_SYSTEM_PROMPT, JSON_PATCH_REPAIR_SYSTEM_PROMPT
from test_workout_generator_planning_tools import planning_case, requirement_messages


def test_resume_replaces_old_application_prompts_without_changing_saved_data_or_custom_context():
    gear, _, stored, _ = planning_case()
    messages = shell._build_initial_messages(BASE_SYSTEM_PROMPT, gear, lambda _: 'Provided equipment facts.', gear['exerciseDefinitions'])
    messages[-1]['content'] += MUSCLE_ROLE_GUIDANCE + ' Old workflow instructions.'
    messages.append({'role': 'system', 'content': 'Custom caller instructions.'})
    messages.extend(requirement_messages(stored))
    before = copy.deepcopy(messages)
    outgoing = shell._messages_for_api(messages, True, provided_equipment=gear)
    systems = [item['content'] for item in outgoing if item['role'] == 'system']
    assert systems.count(shell.CANONICAL_PLANNING_INSTRUCTION) == 1
    assert 'Provided equipment facts.' in systems and 'Custom caller instructions.' in systems
    assert BASE_SYSTEM_PROMPT not in systems
    assert MUSCLE_ROLE_GUIDANCE not in '\n'.join(systems)
    assert 'Old workflow instructions.' not in '\n'.join(systems)
    assert request_planning_state(outgoing)['requirementsApproved']
    assert request_planning_state(outgoing)['constructionTask']['action'] == 'create_first_session'
    assert messages == before
    # The ordinary conversation path retains its own instructions.
    assert shell._messages_for_api(messages)[0]['content'] == BASE_SYSTEM_PROMPT


@pytest.mark.parametrize('stage', ['equipment', 'accessory', 'index'])
def test_json_stage_requests_do_not_inherit_conversation_workflow(monkeypatch, stage):
    requests = []
    def capture(client, messages, *args, **kwargs):
        requests.append(messages)
        return None
    monkeypatch.setattr(cli, 'json_call_reasoner_only_with_loading', capture)
    if stage == 'equipment':
        cli.emit_equipment_item('EQUIPMENT_0', None, 'Source facts', {'equipments': [{'id': 'EQUIPMENT_0'}]})
    elif stage == 'accessory':
        cli.emit_accessory_equipment_item('ACCESSORY_0', None, 'Source facts', {'accessoryEquipments': [{'id': 'ACCESSORY_0'}]})
    else:
        cli.generate_index(None, 'Source facts')
    systems = [item['content'] for item in requests[0] if item['role'] == 'system']
    assert systems == [PLAN_INDEX_SYSTEM_PROMPT if stage == 'index' else EQUIPMENT_SYSTEM_PROMPT]
    assert MUSCLE_ROLE_GUIDANCE not in '\n'.join(systems)


@pytest.mark.parametrize('supported', [True, False])
def test_schema_repair_preserves_known_values_and_leaves_unsupported_facts_unresolved(monkeypatch, supported):
    document = {'equipments': [{'id': 'EQUIPMENT_0', 'type': 'WEIGHTVEST', 'availableWeights': [5]}]}
    schema = {'type': 'object', 'properties': {'equipments': {'type': 'array', 'items': {
        'type': 'object', 'properties': {'availableWeights': {'type': 'array', 'items': {
            'type': 'object', 'properties': {'weight': {'type': 'number'}}, 'required': ['weight']}}}}}}}
    original = copy.deepcopy(document)
    validator = Draft7Validator(schema)
    def capture(client, messages, *args, **kwargs):
        assert [m['content'] for m in messages if m['role'] == 'system'] == [JSON_PATCH_REPAIR_SYSTEM_PROMPT]
        assert SCHEMA_REPAIR_INSTRUCTION in messages[0]['content']
        targets = json.loads(messages[-1]['content'].split('Structured repair targets:\n')[1].split('\n\n')[0])
        assert targets[0]['schemaFragment']['type'] == 'object'
        return json.dumps([{'op': 'replace', 'path': '/equipments/0/availableWeights/0', 'value': {'weight': 5}}] if supported else [])
    monkeypatch.setattr(cli, 'json_call_reasoner_only_with_loading', capture)
    if not supported:
        with pytest.raises(SchemaRepairError, match='made no change'):
            cli.repair_with_json_patch(None, 'No additional facts are known.', document, list(validator.iter_errors(document)))
        assert document == original
        return
    repaired = cli.repair_with_json_patch(None, 'Only known source values are supplied.', document, list(validator.iter_errors(document)))
    assert document == original
    assert repaired['equipments'][0]['id'] == original['equipments'][0]['id']
    validator.validate(repaired)
    assert repaired['equipments'][0]['availableWeights'] == [{'weight': 5}]


def test_legacy_healing_keeps_missing_facts_as_a_failure(monkeypatch):
    schema = {'type': 'object', 'properties': {'measurement': {'type': 'number'}}, 'required': ['measurement']}
    document = {'id': 'EQUIPMENT_0'}
    error = next(Draft7Validator(schema).iter_errors(document))
    calls = []
    def unchanged(client, messages, *args, **kwargs):
        calls.append(1)
        assert messages[0]['content'] == SELF_HEAL_SYSTEM_PROMPT
        assert SCHEMA_REPAIR_INSTRUCTION in messages[0]['content']
        return json.dumps(document)
    monkeypatch.setattr(cli, 'JSON_SCHEMA', schema)
    monkeypatch.setattr(cli, 'json_call_reasoner_only_with_loading', unchanged)
    with pytest.raises(SchemaRepairError, match='made no change'):
        cli.self_heal_validation_error_full_json(None, document, error, 'No measurement is known.', max_attempts=3)
    assert calls == [1]
    assert document == {'id': 'EQUIPMENT_0'}


@pytest.mark.parametrize('changed_weights', [[{'weight': 50}], [{'weight': 5}, {'weight': 50}], []])
@pytest.mark.parametrize('mode', ['patch', 'targeted', 'full'])
def test_all_repair_paths_reject_changed_equipment_without_mutating_input(monkeypatch, changed_weights, mode):
    document = {'equipments': [{'id': 'EQUIPMENT_0', 'type': 'WEIGHTVEST', 'availableWeights': [5]}]}
    before = copy.deepcopy(document)
    schema = {'type': 'object', 'properties': {'equipments': {'type': 'array', 'items': {
        'type': 'object', 'properties': {'availableWeights': {'type': 'array', 'items': {'type': 'object'}}}}}}}
    errors = list(Draft7Validator(schema).iter_errors(document))
    altered = copy.deepcopy(document)
    altered['equipments'][0]['availableWeights'] = changed_weights
    response = ([{'op': 'replace', 'path': '/equipments/0/availableWeights', 'value': changed_weights}]
                if mode == 'patch' else altered['equipments'][0] if mode == 'targeted' else altered)
    calls = []
    monkeypatch.setattr(cli, 'JSON_SCHEMA', schema)
    monkeypatch.setattr(cli, 'json_call_reasoner_only_with_loading', lambda *a, **k: (calls.append(1) or json.dumps(response)))
    with pytest.raises(SchemaRepairError, match='changed supplied equipment|outside allowed error paths'):
        if mode == 'patch':
            cli.repair_with_json_patch(None, 'The available weight is 5 kg.', document, errors)
        else:
            heal = cli.self_heal_validation_error if mode == 'targeted' else cli.self_heal_validation_error_full_json
            heal(None, document, errors[0], 'The available weight is 5 kg.', max_attempts=3)
    assert calls == [1] and document == before


def test_empty_patch_stops_the_validation_loop_after_one_model_call(monkeypatch):
    schema = {'type': 'object', 'required': ['measurement']}
    document = {'equipments': []}
    calls = []
    monkeypatch.setattr(cli, 'create_placeholder_schema', lambda: schema)
    monkeypatch.setattr(cli, 'analyze_and_log_validation_errors', lambda *a: ({}, None))
    monkeypatch.setattr(cli, 'json_call_reasoner_only_with_loading', lambda *a, **k: (calls.append(1) or '[]'))
    with pytest.raises(SchemaRepairError, match='made no change') as error:
        cli.validate_and_repair_placeholder_json(None, 'No measurement is known.', document, max_attempts=5)
    assert "'measurement' is a required property" in str(error.value)
    assert calls == [1] and document == {'equipments': []}


@pytest.mark.parametrize('mode', ['patch', 'targeted', 'full'])
@pytest.mark.parametrize('change_sibling', [False, True])
def test_every_schema_repair_mode_uses_the_same_exact_write_scope(monkeypatch, mode, change_sibling):
    document = {'workouts': [{'id': 'WORKOUT_0', 'name': 'Session',
        'workoutComponents': [], 'notes': 'Preserve this note.'}]}
    schema = {'type': 'object', 'properties': {'workouts': {'type': 'array', 'items': {
        'type': 'object', 'required': ['description'], 'properties': {'description': {'type': 'string'}}}}}}
    before = copy.deepcopy(document)
    repaired = copy.deepcopy(document)
    repaired['workouts'][0]['description'] = 'Short'
    if change_sibling:
        repaired['workouts'][0]['notes'] = 'Unauthorized change.'
    operations = [{'op': 'add', 'path': '/workouts/0/description', 'value': 'Short'}]
    if change_sibling:
        operations.append({'op': 'replace', 'path': '/workouts/0/notes', 'value': 'Unauthorized change.'})
    response = operations if mode == 'patch' else repaired['workouts'][0] if mode == 'targeted' else repaired
    calls = []
    def respond(client, messages, *args, **kwargs):
        calls.append(1)
        assert 'Permitted document paths' in messages[-1]['content']
        return json.dumps(response)
    monkeypatch.setattr(cli, 'JSON_SCHEMA', schema)
    monkeypatch.setattr(cli, 'json_call_reasoner_only_with_loading', respond)
    error = next(Draft7Validator(schema).iter_errors(document))
    def invoke():
        if mode == 'patch':
            return cli.repair_with_json_patch(None, 'Preserve all other facts.', document, [error])
        heal = cli.self_heal_validation_error if mode == 'targeted' else cli.self_heal_validation_error_full_json
        return heal(None, document, error, 'Preserve all other facts.', max_attempts=3)
    if change_sibling:
        with pytest.raises(SchemaRepairError, match='outside allowed error'):
            invoke()
    else:
        assert invoke() == repaired
    assert calls == [1] and document == before


@pytest.mark.parametrize('original,repaired,schema', [
    ({'reps': 50}, {'reps': 8}, {'properties': {'reps': {'maximum': 20}}}),
    ({'id': 'wrong'}, {'id': 'SET_0'}, {'properties': {'id': {'pattern': '^SET_[0-9]+$'}}}),
    ({'muscleGroups': []}, {'muscleGroups': ['FRONT_CHEST']}, {'properties': {'muscleGroups': {'minItems': 1}}}),
    ({'sets': []}, {'sets': [{'id': 'SET_0', 'reps': 8}]}, {'properties': {'sets': {'minItems': 1}}}),
    ({'auditTargets': {}}, {'auditTargets': {'weeklyEffectiveSets': {}}}, {'properties': {'auditTargets': {'required': ['weeklyEffectiveSets']}}}),
])
def test_a_failing_field_does_not_authorize_changing_training_facts(original, repaired, schema):
    errors = list(Draft7Validator(schema).iter_errors(original))
    assert errors
    with pytest.raises(SchemaRepairError):
        validate_schema_repair(original, repaired, errors)


def test_known_numeric_representation_can_be_fixed_without_changing_its_value():
    schema = {'properties': {'reps': {'type': 'integer'}}}
    original = {'reps': '8'}
    validate_schema_repair(original, {'reps': 8}, list(Draft7Validator(schema).iter_errors(original)))


def test_required_field_error_does_not_open_its_siblings_for_repair():
    original = {'notes': 'Keep this.'}
    error = next(Draft7Validator({'required': ['description']}).iter_errors(original))
    with pytest.raises(SchemaRepairError, match='outside allowed error'):
        validate_schema_repair(original, {'notes': 'Changed.', 'description': 'Added.'}, [error])


def test_other_schema_alternatives_do_not_authorize_removing_valid_fields():
    schema = {'oneOf': [
        {'type': 'object', 'properties': {'kind': {'const': 'A'}, 'description': {'maxLength': 5}, 'notes': {'type': 'string'}},
         'required': ['kind'], 'additionalProperties': False},
        {'type': 'object', 'properties': {'kind': {'const': 'B'}}, 'required': ['kind'], 'additionalProperties': False},
    ]}
    original = {'kind': 'A', 'description': 'too long', 'notes': 'Keep this.'}
    error = next(Draft7Validator(schema).iter_errors(original))
    permitted = {**original, 'description': 'Short'}
    validate_schema_repair(original, permitted, [error])
    with pytest.raises(SchemaRepairError, match='outside allowed error'):
        validate_schema_repair(original, {'kind': 'A', 'description': 'Short'}, [error])


def test_targeted_equipment_healing_reassembles_the_actual_extracted_object(monkeypatch):
    document = {'equipments': [{'id': 'EQUIPMENT_0', 'type': 'WEIGHTVEST', 'availableWeights': [5]}]}
    schema = {'properties': {'equipments': {'items': {'properties': {'availableWeights': {'items': {'type': 'object'}}}}}}}
    repaired = copy.deepcopy(document)
    repaired['equipments'][0]['availableWeights'] = [{'weight': 5}]
    monkeypatch.setattr(cli, 'JSON_SCHEMA', schema)
    monkeypatch.setattr(cli, 'json_call_reasoner_only_with_loading', lambda *a, **k: json.dumps(repaired['equipments'][0]))
    error = next(Draft7Validator(schema).iter_errors(document))
    assert cli.self_heal_validation_error(None, document, error, 'The weight is 5 kg.') == repaired
    assert document['equipments'][0]['availableWeights'] == [5]


def test_repair_without_concrete_permissions_does_not_call_the_model(monkeypatch):
    monkeypatch.setattr(cli, 'json_call_reasoner_only_with_loading', lambda *a, **k: pytest.fail('No repair was permitted.'))
    with pytest.raises(SchemaRepairError, match='permitted repair paths'):
        cli.repair_with_json_patch(None, 'Unknown failure.', {'workouts': []}, ['Validation failed without a field path.'])


def test_equipment_normalization_preserves_unknowns_and_only_converts_supplied_values():
    equipment = [
        {'id': 'EQUIPMENT_0', 'type': 'BARBELL', 'availablePlates': [5, {'weight': 10}, {'weight': 20, 'thickness': 30}]},
        {'id': 'EQUIPMENT_1', 'type': 'WEIGHTED_VEST', 'maxWeight': 20},
        {'id': 'EQUIPMENT_2', 'type': 'DUMBBELL'},
        {'id': 'EQUIPMENT_3', 'type': 'BENCH'},
        {'id': 'EQUIPMENT_4', 'type': 'DUMBBELL', 'dumbbellWeight': 7},
        {'id': 'EQUIPMENT_5', 'type': 'WEIGHTVEST', 'availableWeights': [{'weight': 5}, 10, True]},
    ]
    before = copy.deepcopy(equipment)
    fixed = fix_equipment_errors(equipment)
    assert [item['id'] for item in fixed] == [item['id'] for item in equipment]
    assert fixed[0]['availablePlates'] == [{'weight': 5}, {'weight': 10}, {'weight': 20, 'thickness': 30}]
    assert fixed[1] == {**equipment[1], 'type': 'WEIGHTVEST'}
    assert fixed[2:4] == equipment[2:4]
    assert fixed[4]['dumbbells'] == [{'weight': 7}]
    assert fixed[5]['availableWeights'] == [{'weight': 5}, {'weight': 10}, True]
    assert equipment == before
    fixed[0]['availablePlates'][2]['thickness'] = 99
    assert equipment == before


@pytest.mark.parametrize('item', [
    {'type': 'TimedDurationSet'},
    {'type': 'EnduranceSet', 'timeInSeconds': 30, 'timeInMillis': 45000},
    {'type': 'TimedDurationSet', 'timeInMillis': 0, 'autoStop': True, 'subCategory': 'WorkSet'},
    {'type': 'DistanceSet'},
    {'type': 'DistanceSet', 'distance': 100, 'targetDistanceMeters': 200},
    {'type': 'DistanceSet', 'distance': 100, 'autoStop': True},
])
def test_set_cleanup_preserves_targets_and_tracking_settings_instead_of_inventing_repairs(item):
    before = copy.deepcopy(item)
    fixed = fix_set_errors([item])[0]
    for field, value in item.items():
        assert fixed[field] == value
    assert ('timeInMillis' in fixed) == ('timeInMillis' in item)
    assert item == before
    exercise = {'sets': [copy.deepcopy(item)]}
    fix_timed_sets(exercise)
    assert exercise['sets'] == [fixed]


def test_set_cleanup_only_converts_explicit_nonconflicting_duration_units():
    source = [{'type': 'TimedDurationSet', 'timeInSeconds': 1.25, 'autoStart': True}]
    assert fix_set_errors(source) == [{'type': 'TimedDurationSet', 'timeInMillis': 1250,
                                      'autoStart': True, 'autoStop': False}]
    assert source[0]['timeInSeconds'] == 1.25
