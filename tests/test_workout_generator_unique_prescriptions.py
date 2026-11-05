import copy
import json

import pytest
from jsonschema import ValidationError

from workout_generator_pkg import session_drafting
from workout_generator_pkg.prescription_choices import unique_recipe_request, expand_recipe_choices
from workout_generator_pkg.planner_context import request_planning_state
from test_workout_generator_parallel_planning import week_case, store_tool, shell


def test_unique_recipe_binding_preserves_source_variants_and_exact_targets():
    schema = session_drafting._worker_response_schema({'workingSetRIR': {'minimum': 1, 'maximum': 2}})
    source = {'definition_id': 'LIBRARY_0', 'numWorkSets': 2, 'superset': None}
    variant = {**source, 'minReps': 4, 'maxReps': 4,
               'targetSetPrescriptions': [{'workSetIndex': 0, 'reps': 4, 'weight': 37.5}]}
    sessions = [{'exercises': [source, copy.deepcopy(source)]},
                {'exercises': [{**source, 'numWorkSets': 5}, variant]}]
    recipes, response, bindings, saved = unique_recipe_request(
        sessions, {}, {}, schema['properties']['exercises']['items'])
    assert len(recipes) == 2
    assert bindings == {'0': ['RECIPE_0', 'RECIPE_0'], '1': ['RECIPE_0', 'RECIPE_1']}
    assert 'definition_id' not in response['properties']['RECIPE_0']['properties']
    assert 'targetSetPrescriptions' not in response['properties']['RECIPE_1']['properties']
    choices = {key: {'minReps': 8, 'maxReps': 12, 'durationSeconds': None,
        'restBetweenSetsSeconds': 120, 'restAfterExerciseSeconds': 60,
        'restAfterSupersetExerciseSeconds': 0} for key in recipes}
    choices['RECIPE_1'].pop('minReps')
    choices['RECIPE_1'].pop('maxReps')
    expanded = expand_recipe_choices(sessions, bindings, saved, choices, response)
    assert expanded['1']['exercises'][0]['numWorkSets'] == 5
    assert expanded['1']['exercises'][1]['targetSetPrescriptions'] == variant['targetSetPrescriptions']
    assert expanded['1']['exercises'][1]['minReps'] == 4
    expanded['0']['exercises'][0]['minReps'] = 99
    assert expanded['0']['exercises'][1]['minReps'] == 8
    with pytest.raises(ValidationError):
        expand_recipe_choices(sessions, bindings, saved, {}, response)
    with pytest.raises(ValidationError):
        expand_recipe_choices(sessions, bindings, saved, {**choices, 'RECIPE_99': {}}, response)


def test_fully_specified_timed_source_needs_no_model_choice():
    exercise_schema = session_drafting._worker_response_schema(
        {'workingSetRIR': {'minimum': 1, 'maximum': 2}})['properties']['exercises']['items']
    source = {'definition_id': 'LIBRARY_0', 'numWorkSets': 2, 'superset': None,
        'minReps': None, 'maxReps': None, 'durationSeconds': 73,
        'restBetweenSetsSeconds': 47, 'restAfterExerciseSeconds': 19,
        'restAfterSupersetExerciseSeconds': 0, 'repDurationSeconds': None}
    sessions = [{'exercises': [source]}]
    recipes, schema, bindings, saved = unique_recipe_request(sessions, {}, {}, exercise_schema)
    assert not recipes
    expanded = expand_recipe_choices(sessions, bindings, saved, {}, schema)
    assert expanded['0']['exercises'] == [source]


def test_three_sessions_use_one_unique_prescription_call_and_replay_without_calls(monkeypatch):
    import test_workout_generator_parallel_planning as fixtures
    original_case = fixtures.planning_case

    def calibratable_case():
        equipment, requirements, stored, draft = original_case()
        equipment['equipments'] = [{'id': 'EQUIPMENT_0', 'name': 'Fixture dumbbells',
            'type': 'DUMBBELLS', 'availableWeights': [{'weight': 5}]}]
        equipment['exerciseDefinitions'][0]['equipmentId'] = 'EQUIPMENT_0'
        return equipment, requirements, stored, draft

    monkeypatch.setattr(fixtures, 'planning_case', calibratable_case)
    monkeypatch.setattr('workout_generator_pkg.recipe_contracts.qualify_recipe_contracts',
        lambda *args, **kwargs: {'inputHash': 'qualified-fixture', 'contracts': [], 'capabilities': {}})
    equipment, messages, prepared, exercises = week_case(working_set_rir={'minimum': 1, 'maximum': 2})
    state = request_planning_state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    calls = []

    def choose(client, request, **options):
        payload = json.loads(request[-1]['content'])
        calls.append(payload)
        assert options['output_schema'] == payload['responseSchema']
        assert len(payload['recipes']) == 1
        assert not {'session', 'sharedWeek', 'existingSessions'} & payload.keys()
        values = {}
        for key, schema in payload['responseSchema']['properties'].items():
            values[key] = {field: copy.deepcopy(value) for field, value in exercises[0].items()
                           if field in schema['properties']}
        return json.dumps(values), None, None

    monkeypatch.setattr(session_drafting, 'chat_call', choose)
    arguments = {'preparationId': prepared['preparationId']}
    result = session_drafting.draft_workout_sessions(None, arguments, messages, equipment, state)
    assert 'proposedSubmission' in result, result.get('errors')
    assert len(calls) == 1
    assert set(result['workerResults']) == {'0', '1', '2'}
    store_tool(messages, 'draft_workout_sessions', arguments, result)
    monkeypatch.setattr(session_drafting, 'chat_call', lambda *a, **k: pytest.fail('Saved recipes must be reused'))
    replay = session_drafting.draft_workout_sessions(None, arguments, messages, equipment, state)
    assert 'proposedSubmission' in replay, replay.get('errors')
