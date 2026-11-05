"""Provider-free outcome checks for the confirmed-plan compiler."""
import json
from pathlib import Path

import pytest
from jsonschema import Draft7Validator

from workout_generator_pkg import api_client, generation_pipeline as pipeline, plan_review as review
from workout_generator_pkg.constants import JSON_SCHEMA
from test_workout_generator_single_review import request_data, response_for


def retained_weight_vest():
    return {'id': 'e95fb928-2fc9-49b3-8dc9-2c60f5f48cd0', 'name': 'Weight Vest', 'type': 'WEIGHTVEST',
        'availableWeights': [{'weight': float(weight)} for weight in range(1, 21)],
        'extraWeights': [], 'loadingPoints': 1, 'maxExtraWeightsPerLoadingPoint': 0}


def confirmed_recipe(monkeypatch, *, execution_mode=None):
    from test_workout_generator_planning_tools import planning_case
    equipment, requirements, _, draft = planning_case()
    equipment['exerciseDefinitions'][0]['id'] = 'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee'
    from workout_generator_pkg.planning_tools import audit_workout_plan, set_workout_requirements
    from test_workout_generator_planning_tools import planning_case, capability_requirement_messages
    requirements['preferredSessionSeconds'] = 4500
    requirements['auditTargets']['maximumSessionSeconds'] = 5400
    requirements['exerciseSelection'] = {'preferredMinimum': 2, 'preferredMaximum': 3, 'muscles': ['chest']}
    stored = set_workout_requirements(requirements, [{'role': 'user', 'content':
        'Plan 5-6 chest sets, prefer 75-minute sessions with a 90-minute ceiling and 2-3 chest exercises.'}], equipment)
    draft['requirementsId'] = stored['requirementsId']
    messages = capability_requirement_messages(stored, equipment)
    if execution_mode:
        from workout_generator_pkg.planning_tools import library_fingerprint
        choice = json.loads(messages[-1]['content'])
        choice['decisions']['DECISION_1'] = {
            'topic': 'Synthetic fixture execution counting',
            'choice': 'Repeat the prescribed repetitions on each side.',
            'executionPrescription': {'definitionId': equipment['exerciseDefinitions'][0]['id'],
                                      'setMode': execution_mode},
            'factualContextLibraryFingerprint': library_fingerprint(equipment),
        }
        messages[-1]['content'] = json.dumps(choice)
        draft['workouts'][0]['exercises'][0]['intraSetRestInSeconds'] = 15
    audited = audit_workout_plan(draft, equipment, messages)
    def respond(client, request, **options):
        return json.dumps(response_for(request_data(request), options['output_schema'])), None, None
    monkeypatch.setattr(review, '_review_call', respond)
    audited = review.review_draft(None, audited, messages, equipment)
    assert audited['passed'], audited
    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': 'draft', 'function': {'name': 'audit_workout_plan'}}]},
        {'role': 'tool', 'tool_call_id': 'draft', 'content': json.dumps(audited)},
        {'role': 'assistant', 'content': audited['preview'], 'canonicalDraftPreview': audited['draftId']},
        {'role': 'user', 'content': 'CONFIRM GENERATE'},
    ])
    return equipment, messages


def test_weight_vest_export_uses_native_factory_without_changing_source_or_load_grid(tmp_path, monkeypatch):
    import copy
    from test_workout_generator_planning_tools import planning_case
    from workout_generator_pkg.domain_ops import validate_schema_repair

    def source_case():
        equipment, requirements, stored, draft = planning_case()
        equipment['equipments'] = [retained_weight_vest()]
        return equipment, requirements, stored, draft

    monkeypatch.setattr('test_workout_generator_planning_tools.planning_case', source_case)
    equipment, messages = confirmed_recipe(monkeypatch)
    original = copy.deepcopy(equipment)
    factory, calls = pipeline.EquipmentItem, []
    def normalize(item):
        calls.append(copy.deepcopy(item))
        return factory(item)
    monkeypatch.setattr(pipeline, 'EquipmentItem', normalize)
    def forbidden(*args, **kwargs):
        pytest.fail('The confirmed weight-vest package must compile without a provider.')
    monkeypatch.setattr(api_client, 'chat_call', forbidden)
    monkeypatch.setattr(review, '_review_call', forbidden)

    outcome = pipeline.execute_workout_generation(None, messages, provided_equipment=equipment,
        script_dir=str(tmp_path))

    assert outcome['success'], outcome['error']
    package = json.loads(Path(outcome['filepath']).read_text(encoding='utf-8'))
    vest = next(item for item in package['equipments'] if item['type'] == 'WEIGHTVEST')
    expected = {key: value for key, value in retained_weight_vest().items()
                if key not in ('extraWeights', 'loadingPoints', 'maxExtraWeightsPerLoadingPoint')}
    assert vest == expected and len(calls) == 1
    assert equipment == original
    schema = {'type': 'object', 'properties': {'equipments': {'type': 'array',
        'items': {'$ref': '#/$defs/EquipmentWeightVest'}}}, '$defs': JSON_SCHEMA['$defs']}
    validator = Draft7Validator(schema)
    validator.validate({'equipments': [vest]})
    validate_schema_repair({'equipments': [retained_weight_vest()]}, {'equipments': [vest]},
        list(validator.iter_errors({'equipments': [retained_weight_vest()]})))
    report = json.loads(Path(outcome['filepath']).with_suffix('.audit.json').read_text(encoding='utf-8'))
    assert not report['issues']


@pytest.mark.parametrize('field,value', [
    ('extraWeights', [{'weight': 1}]), ('loadingPoints', 2),
    ('maxExtraWeightsPerLoadingPoint', 1), ('loadingPoints', True), ('unknownConfiguration', 7),
])
def test_weight_vest_nonconstant_configuration_is_preserved_for_strict_rejection(field, value):
    from workout_generator_pkg.domain_ops import EquipmentItem, SchemaRepairError, validate_schema_repair

    vest = retained_weight_vest()
    vest[field] = value
    normalized = EquipmentItem(vest)
    assert normalized[field] == value and type(normalized[field]) is type(value)
    schema = {'$ref': '#/$defs/EquipmentWeightVest', '$defs': JSON_SCHEMA['$defs']}
    errors = list(Draft7Validator(schema).iter_errors(normalized))
    assert errors
    removed = {key: value for key, value in normalized.items() if key != field}
    with pytest.raises(SchemaRepairError, match='changed supplied equipment data'):
        validate_schema_repair({'equipments': [normalized]}, {'equipments': [removed]}, errors)


def test_confirmed_recipe_exports_native_schema_and_audit_without_provider_calls(tmp_path, monkeypatch):
    equipment, messages = confirmed_recipe(monkeypatch)
    def forbidden(*args, **kwargs):
        pytest.fail('The confirmed-plan compiler must not call a provider.')
    monkeypatch.setattr(api_client, 'chat_call', forbidden)
    monkeypatch.setattr(review, '_review_call', forbidden)
    outcome = pipeline.execute_workout_generation(None, messages, provided_equipment=equipment, script_dir=str(tmp_path))
    assert outcome['success'], outcome['error']
    package = json.loads(Path(outcome['filepath']).read_text(encoding='utf-8'))
    legacy = {key: package[key] for key in ('name', 'workouts', 'equipments', 'accessoryEquipments')}
    import copy
    legacy = copy.deepcopy(legacy)
    for day in legacy['workouts']:
        for exercise in day['workoutComponents']:
            exercise.pop('exerciseDefinitionId', None)
    Draft7Validator(JSON_SCHEMA).validate(legacy)
    assert package['exerciseDefinitions'][0]['id'] == package['workouts'][0]['workoutComponents'][0]['exerciseDefinitionId']
    assert package['schemaVersion'] == 2
    exercise = package['workouts'][0]['workoutComponents'][0]
    assert [s['reps'] for s in exercise['sets'] if s['type'] == 'BodyWeightSet'] == [8] * 5
    assert not exercise['requiresLoadCalibration']
    report = json.loads(Path(outcome['filepath']).with_suffix('.audit.json').read_text(encoding='utf-8'))
    assert report['issues'] == []
    assert report['workouts'][0]['workingSets'] == 5
    assert report['weeklyVolume']['chest']['effective'] == 5
    budget = report['sessionTimeBudgetEvidence']
    assert budget['preferredSessionSeconds'] == 4500
    assert budget['maximumSessionSeconds'] == 5400
    assert budget['sessions'][0]['estimatedSeconds'] == report['workouts'][0]['estimatedSeconds']
    selected = report['exerciseSelectionEvidence']['chest']
    assert selected['exerciseIds'] == ['aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee']
    assert selected['count'] == selected['shortfall'] == 1
    assert Path(outcome['guidance_filepath']).is_file()


def test_export_without_a_confirmed_plan_returns_to_planning(tmp_path):
    outcome = pipeline.execute_workout_generation(None, [], script_dir=str(tmp_path))
    assert not outcome['success']
    assert 'requirements' in outcome['error'].lower()
    assert not list(tmp_path.rglob('*.json'))


def test_reviewed_execution_choice_survives_compiler_hydration_and_native_export(tmp_path, monkeypatch):
    import copy

    equipment, messages = confirmed_recipe(monkeypatch, execution_mode='paired_sides')
    source_equipment = copy.deepcopy(equipment)
    def forbidden(*args, **kwargs):
        pytest.fail('The confirmed execution choice must compile without a provider.')
    monkeypatch.setattr(api_client, 'chat_call', forbidden)
    monkeypatch.setattr(review, '_review_call', forbidden)

    outcome = pipeline.execute_workout_generation(None, messages, provided_equipment=equipment,
                                                  script_dir=str(tmp_path))

    assert outcome['success'], outcome['error']
    package = json.loads(Path(outcome['filepath']).read_text(encoding='utf-8'))
    exercise = package['workouts'][0]['workoutComponents'][0]
    assert exercise['intraSetRestInSeconds'] == 15
    assert [item['reps'] for item in exercise['sets'] if item['type'] == 'BodyWeightSet'] == [8] * 5
    report = json.loads(Path(outcome['filepath']).with_suffix('.audit.json').read_text(encoding='utf-8'))
    assert report['workouts'][0]['timing']['workSeconds'] == 5 * 10 * 3 * 2
    assert equipment == source_equipment
