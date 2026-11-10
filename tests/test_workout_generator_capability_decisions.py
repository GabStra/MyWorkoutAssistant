import copy
import json

import pytest
from jsonschema import ValidationError

from workout_generator_pkg.planning_decisions import propose_decisions, record_planning_decisions_tool
from workout_generator_pkg.planning_tools import library_fingerprint
from test_workout_generator_planning_tools import planning_case, requirement_messages


def capability_question():
    equipment, _, stored, _ = planning_case()
    stored['libraryFingerprint'] = library_fingerprint(equipment)
    messages = requirement_messages(stored)
    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': 'prepare', 'function': {
            'name': 'prepare_workout_sessions', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'prepare', 'content': json.dumps({'passed': False,
            'errors': [{'definition_id': 'LIBRARY_0', 'concerns': [
                {'code': 'unverified_fixed_bodyweight_capability'}]}]})},
        {'role': 'user', 'content': 'I can perform this exact unweighted push-up configuration.'},
    ])
    return equipment, messages


def test_capability_decision_choices_are_current_code_reported_exercises():
    _, messages = capability_question()
    properties = record_planning_decisions_tool(messages)['function']['parameters']['properties']['decisions']['items']['properties']
    assert properties['confirmedCapabilityReference']['enum'] == ['LIBRARY_0']
    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': 'prepare2', 'function': {
            'name': 'prepare_workout_sessions', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'prepare2', 'content': '{"passed":true}'},
    ])
    properties = record_planning_decisions_tool(messages)['function']['parameters']['properties']['decisions']['items']['properties']
    assert 'confirmedCapabilityReference' not in properties


def test_capability_proposal_binds_library_and_requires_the_existing_review_before_use():
    from workout_generator_pkg.training_history import confirmed_capability_references
    equipment, messages = capability_question()
    args = {'decisions': [{'topic': 'Push-up capability', 'choice': 'User reports ability for this exact configuration.',
        'sourceReferences': ['SOURCE_1'], 'confirmedCapabilityReference': 'LIBRARY_0'}]}
    proposal = propose_decisions(args, messages)
    assert proposal['decisions']['DECISION_0']['capabilityLibraryFingerprint'] == library_fingerprint(equipment)
    assert confirmed_capability_references(messages, equipment) == set()
    # Persist only after the existing independent decision review passes.
    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': 'decision', 'function': {
            'name': 'record_planning_decisions', 'arguments': json.dumps(args)}}]},
        {'role': 'tool', 'tool_call_id': 'decision', 'content': json.dumps({
            **proposal, 'passed': True, 'decisionReview': {'passed': True}})},
    ])
    assert confirmed_capability_references(messages, equipment) == {'LIBRARY_0'}
    changed = copy.deepcopy(equipment)
    changed['exerciseDefinitions'][0]['bodyWeightPercentage'] = 60
    assert confirmed_capability_references(messages, changed) == set()
    proposal['decisions']['DECISION_0'].pop('confirmedCapabilityReference')
    messages[-1]['content'] = json.dumps({**proposal, 'passed': True, 'decisionReview': {'passed': True}})
    assert confirmed_capability_references(messages, equipment) == set()


def test_capability_proposal_cannot_assert_unoffered_movement_or_set_backend_provenance():
    _, messages = capability_question()
    item = {'topic': 'Ability', 'choice': 'Able', 'sourceReferences': ['SOURCE_1'],
            'confirmedCapabilityReference': 'LIBRARY_1'}
    with pytest.raises(ValidationError):
        propose_decisions({'decisions': [item]}, messages)

    item['confirmedCapabilityReference'] = 'LIBRARY_0'
    item['capabilityLibraryFingerprint'] = 'invented'
    with pytest.raises(ValidationError):
        propose_decisions({'decisions': [item]}, messages)


@pytest.mark.parametrize('change,expected', [
    ('derived_metadata', {'LIBRARY_0'}), ('bodyweight', set()),
    ('equipment', set()), ('movement', set()), ('execution', set()),
    ('reference_order', set()), ('missing_snapshot', set()), ('wrong_fingerprint', set()),
])
def test_capability_reuse_proves_original_audited_configuration_after_metadata_change(change, expected):
    from workout_generator_pkg.planning_tools import audit_workout_plan
    from workout_generator_pkg.training_history import confirmed_capability_references

    equipment, messages = capability_question()
    equipment['equipments'] = [{'id': 'EQUIPMENT_0', 'name': 'Vest', 'type': 'WEIGHTVEST', 'availableWeights': []}]
    equipment['exerciseDefinitions'][0]['equipmentId'] = 'EQUIPMENT_0'
    # Bind the original source receipt to this actual equipment snapshot.
    _, _, stored, draft = planning_case()
    stored['libraryFingerprint'] = library_fingerprint(equipment)
    messages = requirement_messages(stored) + messages[-3:]
    original_audit = audit_workout_plan(draft, equipment, messages)
    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': 'original_audit', 'function': {
            'name': 'audit_workout_plan', 'arguments': json.dumps(draft)}}]},
        {'role': 'tool', 'tool_call_id': 'original_audit', 'content': json.dumps(original_audit)},
    ])
    args = {'decisions': [{'topic': 'Push-up capability', 'choice': 'User reports this exact physical configuration.',
        'sourceReferences': ['SOURCE_1'], 'confirmedCapabilityReference': 'LIBRARY_0'}]}
    proposal = propose_decisions(args, messages)
    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': 'decision', 'function': {
            'name': 'record_planning_decisions', 'arguments': json.dumps(args)}}]},
        {'role': 'tool', 'tool_call_id': 'decision', 'content': json.dumps({
            **proposal, 'passed': True, 'decisionReview': {'passed': True}})},
    ])
    current = copy.deepcopy(equipment)
    current['exerciseDefinitions'][0]['trainingMuscles'] = {'primary': ['chest'], 'secondary': ['triceps']}
    if change == 'bodyweight':
        current['exerciseDefinitions'][0]['bodyWeightPercentage'] = 60
    elif change == 'equipment':
        current['equipments'][0]['availableWeights'] = [{'weight': 10}]
    elif change == 'movement':
        current['exerciseDefinitions'][0]['movementRef'] = {'id': 'changed'}
    elif change == 'execution':
        current['exerciseDefinitions'][0]['reviewedExecution'] = {'setMode': 'paired_sides'}
    elif change == 'reference_order':
        current['exerciseDefinitions'].insert(0, {**copy.deepcopy(equipment['exerciseDefinitions'][0]), 'id': 'aaa'})
    elif change == 'missing_snapshot':
        messages = [message for message in messages if message.get('tool_call_id') != 'original_audit']
    elif change == 'wrong_fingerprint':
        original_audit['libraryFingerprint'] = 'unrelated_snapshot'
        messages[-3]['content'] = json.dumps(original_audit)
    assert confirmed_capability_references(messages, current) == expected
