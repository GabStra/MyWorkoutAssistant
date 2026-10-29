from workout_generator_pkg.generation_audit import (
    audit_workout_package, family_set_audit_options, validate_family_set_bounds,
    weekly_family_set_counts,
)


FAMILY_A = '00000000-0000-0000-0000-000000000001'
FAMILY_B = '00000000-0000-0000-0000-000000000002'
FAMILY_BY_REFERENCE = {'definition-a': FAMILY_A, 'definition-b': FAMILY_A,
    'definition-c': FAMILY_B}


def _exercise(identifier, sets, family_reference):
    return {'id': identifier, 'libraryDefinitionId': family_reference, 'type': 'Exercise',
        'name': identifier, 'exerciseType': 'WEIGHT', 'muscleGroups': ['FRONT_CHEST'],
        'sets': [{'type': 'WeightSet', 'reps': 8, 'weight': 20} for _ in range(sets)]}


def _package(*components):
    return {'workouts': [{'name': 'A', 'timesCompletedInAWeek': 2,
        'workoutComponents': list(components)}]}


def test_family_bounds_use_reviewed_identity_and_weekly_frequency_across_superset_members():
    first = _exercise('exercise-1', 2, 'definition-a')
    second = _exercise('exercise-2', 2, 'definition-b')
    third = _exercise('exercise-3', 1, 'definition-b')
    package = _package({'type': 'Superset', 'exercises': [first, second]}, third)
    assert weekly_family_set_counts([{'timesCompletedInAWeek': 2, 'exercises': [
        {'definition_id': 'definition-a', 'numWorkSets': 2},
        {'definition_id': 'definition-b', 'numWorkSets': 2},
        {'definition_id': 'definition-b', 'numWorkSets': 1}]}], FAMILY_BY_REFERENCE) == {FAMILY_A: 10}

    requirements = {'familySetBounds': [{'exerciseFamilyId': FAMILY_A,
        'minimumWeeklySets': 10, 'maximumWeeklySets': 10}]}
    report = audit_workout_package(package, {}, family_set_requirements=requirements,
        family_by_reference=FAMILY_BY_REFERENCE)
    assert report['weeklyFamilyWorkingSets'] == {FAMILY_A: 10}
    assert report['errors'] == []


def test_family_bound_audit_rejects_exposure_above_approved_maximum():
    package = _package(_exercise('exercise-1', 6, 'definition-a'))
    requirements = {'familySetBounds': [{'exerciseFamilyId': FAMILY_A,
        'maximumWeeklySets': 10}]}
    report = audit_workout_package(package, {}, family_set_requirements=requirements,
        family_by_reference=FAMILY_BY_REFERENCE)
    assert [error['code'] for error in report['errors']] == ['family_weekly_sets_above_maximum']
    assert report['errors'][0]['actual'] == 12


def test_family_bounds_fail_preflight_when_id_is_unreviewed_or_bounds_are_invalid():
    errors = validate_family_set_bounds({'familySetBounds': [
        {'exerciseFamilyId': 'unknown', 'minimumWeeklySets': 3, 'maximumWeeklySets': 2},
        {'exerciseFamilyId': FAMILY_A, 'maximumWeeklySets': True},
    ]}, FAMILY_BY_REFERENCE)
    assert {error['code'] for error in errors} == {
        'unrepresentable_family_set_bound', 'invalid_family_set_bounds'}


def test_family_bound_audit_does_not_treat_unclassified_selected_exercise_as_zero():
    package = _package(_exercise('exercise-1', 3, 'unclassified-definition'))
    requirements = {'familySetBounds': [{'exerciseFamilyId': FAMILY_A,
        'maximumWeeklySets': 10}]}
    report = audit_workout_package(package, {}, family_set_requirements=requirements,
        family_by_reference=FAMILY_BY_REFERENCE)
    assert [error['code'] for error in report['errors']] == ['family_bound_evidence_unknown']
    assert 'weeklyFamilyWorkingSets' not in report


def test_bound_uses_reviewed_current_library_definition_and_family_uuids():
    definition_id = '2692280b-4775-5d6e-abf9-fec2a637f023'
    family_id = '27e7555c-cfb4-5d80-9e66-5544abd12e36'
    equipment = {'exerciseDefinitions': [{'id': definition_id}]}
    requirements = {'familySetBounds': [{'exerciseFamilyId': family_id,
        'minimumWeeklySets': 2, 'maximumWeeklySets': 2}]}
    package = _package(_exercise('exercise-1', 1, definition_id))

    report = audit_workout_package(package, {}, **family_set_audit_options(requirements, equipment))

    assert report['weeklyFamilyWorkingSets'] == {family_id: 2}
    assert report['errors'] == []


def test_requirement_family_choices_preflight_and_final_audit_share_reviewed_identity(monkeypatch):
    import copy
    from jsonschema import validate
    import pytest
    from workout_generator_pkg import planning_tools, recipe_contracts
    from test_workout_generator_planning_tools import planning_case, requirement_messages

    equipment, requirements, _, draft = planning_case()
    monkeypatch.setattr(recipe_contracts, 'reviewed_exercise_family_evidence',
        lambda equipment, references=None: {'familyByReference': {'LIBRARY_0': FAMILY_A}})
    requirements['familySetBounds'] = [{'exerciseFamilyId': FAMILY_A, 'maximumWeeklySets': 4}]
    tool = planning_tools.workout_requirements_tool(equipment)
    selector = tool['function']['parameters']['properties']['familySetBounds']['items']['properties']['exerciseFamilyId']
    assert selector['enum'] == [FAMILY_A]
    stored = planning_tools.set_workout_requirements(requirements,
        [{'role': 'user', 'content': 'Keep the weekly family maximum at four working sets.'}], equipment)
    assert stored['requirements']['familySetBounds'] == requirements['familySetBounds']
    assert 'at most 4 working sets' in stored['requirementsPreview']
    draft['requirementsId'] = stored['requirementsId']
    result = planning_tools.audit_workout_plan(draft, equipment, requirement_messages(stored))
    assert result['planIndex']['familySetBounds'] == requirements['familySetBounds']
    assert any(error['code'] == 'family_weekly_sets_above_maximum' and error['actual'] == 5
        for error in result['errors'])
    unsupported = copy.deepcopy(requirements)
    unsupported['familySetBounds'][0]['exerciseFamilyId'] = FAMILY_B
    with pytest.raises(planning_tools.PlanningInputError) as error:
        planning_tools.set_workout_requirements(unsupported,
            [{'role': 'user', 'content': 'An unknown family maximum.'}], equipment)
    assert error.value.code == 'unrepresentable_family_set_bound'


def test_unannotated_library_exposes_no_family_bound_choices():
    from jsonschema import Draft7Validator, validate, ValidationError
    import pytest
    from workout_generator_pkg.planning_tools import workout_requirements_tool
    from test_workout_generator_planning_tools import planning_case

    equipment, _, _, _ = planning_case()
    schema = workout_requirements_tool(equipment)['function']['parameters']
    Draft7Validator.check_schema(schema)
    family_schema = schema['properties']['familySetBounds']
    validate([], family_schema)
    with pytest.raises(ValidationError):
        validate([{'exerciseFamilyId': FAMILY_A, 'maximumWeeklySets': 4}], family_schema)


def test_family_bounds_requirements_project_to_strict_provider_schema(monkeypatch):
    from workout_generator_pkg import recipe_contracts
    from workout_generator_pkg.api_client import _strict_wire_schema, _strict_parameters_compatible
    from workout_generator_pkg.planning_tools import workout_requirements_tool
    from test_workout_generator_planning_tools import planning_case

    equipment, _, _, _ = planning_case()
    monkeypatch.setattr(recipe_contracts, 'reviewed_exercise_family_evidence',
        lambda equipment, references=None: {'familyByReference': {'LIBRARY_0': FAMILY_A}})
    wire = _strict_wire_schema(workout_requirements_tool(equipment)['function']['parameters'])
    assert _strict_parameters_compatible(wire)
    errors = validate_family_set_bounds({'familySetBounds': [{'exerciseFamilyId': FAMILY_A}]},
        FAMILY_BY_REFERENCE)
    assert any(error['code'] == 'invalid_family_set_bounds' for error in errors)
