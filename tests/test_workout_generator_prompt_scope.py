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
