import copy
import json
from unittest.mock import patch

import pytest

from workout_generator_pkg.domain_ops import _materialize_exercise_definition
from workout_generator_pkg.exercise_contracts import execution_semantics_problem, execution_set_mode
from workout_generator_pkg.plan_contract import (
    ContractValidationError,
    _exercise_requires_unilateral_rest,
    validate_plan_index_contract,
)
from workout_generator_pkg import recipe_contracts


def _exercise(**updates):
    return {
        'id': 'EXERCISE_0', 'name': 'Renamed movement', 'exerciseType': 'WEIGHT',
        'equipmentId': 'EQUIPMENT_0', 'bodyWeightPercentage': None,
        'minReps': 10, 'maxReps': 15, 'requiredAccessoryEquipmentIds': [],
        'muscleGroups': ['FRONT_OBLIQUES'], 'secondaryMuscleGroups': [],
        'exerciseCategory': 'MODERATE_COMPOUND', 'numWorkSets': 2,
        'restBetweenSetsSeconds': 90, 'generateWarmUpSets': False,
        'intraSetRestInSeconds': None, **updates,
    }


def _plan(exercise):
    return {'planName': 'Test', 'equipments': [{'id': 'EQUIPMENT_0'}],
            'accessoryEquipments': [], 'exercises': [exercise], 'workouts': []}


@pytest.mark.parametrize(('limb_mode', 'set_mode', 'paired'), [
    ('bilateral', 'paired_sides', True),
    ('unilateral', 'single_sequence', False),
    ('alternating', 'single_sequence', False),
])
def test_set_count_basis_is_independent_of_limb_count(limb_mode, set_mode, paired):
    definition = {'reviewedExecution': {'limbMode': limb_mode, 'setMode': set_mode}}
    exercise = _exercise(satisfiesCoverage=['rotational_core'])
    assert _exercise_requires_unilateral_rest(exercise, definition) is paired
    assert execution_semantics_problem(exercise, definition) is None


def test_unknown_direction_and_alternating_counting_cannot_be_inferred_or_forged():
    exercise = _exercise(satisfiesCoverage=['rotational_core'],
                         reviewedExecution={'setMode': 'single_sequence'})
    definition = {'reviewedExecution': {'limbMode': 'bilateral'}}
    assert execution_set_mode(exercise, definition) is None
    assert 'direction or rep/time counting' in execution_semantics_problem(exercise, definition)
    assert execution_semantics_problem(exercise, {})
    alternating = _exercise(reviewedExecution={'limbMode': 'alternating'})
    assert not _exercise_requires_unilateral_rest(alternating)
    assert 'total or repeated per side' in execution_semantics_problem(alternating)
    assert execution_semantics_problem(_exercise()) is None
    assert execution_semantics_problem(_exercise(satisfiesCoverage=['transverse_plane'])) is None


def test_plan_and_materialization_block_unknown_counting_without_changing_prescription():
    exercise = _exercise(satisfiesCoverage=['rotational_core'])
    original = copy.deepcopy(exercise)
    with pytest.raises(ContractValidationError) as caught:
        validate_plan_index_contract(_plan(exercise))
    assert any(issue.code == 'execution_semantics_unresolved' for issue in caught.value.issues)
    with pytest.raises(ValueError, match='source-backed setMode'):
        _materialize_exercise_definition(exercise)
    assert exercise == original


def test_explicit_counting_uses_native_side_rest_without_changing_logged_sets():
    exercise = _exercise(reviewedExecution={'limbMode': 'bilateral', 'setMode': 'paired_sides'},
                         intraSetRestInSeconds=15, satisfiesCoverage=['rotational_core'])
    validate_plan_index_contract(_plan(exercise))
    emitted = _materialize_exercise_definition(exercise)
    assert emitted['intraSetRestInSeconds'] == 15
    assert [item['reps'] for item in emitted['sets'] if item['type'] == 'WeightSet'] == [10, 10]
    exercise['reviewedExecution']['setMode'] = 'single_sequence'
    with pytest.raises(ContractValidationError) as caught:
        validate_plan_index_contract(_plan(exercise))
    assert any(issue.code == 'execution_set_mode_mismatch' for issue in caught.value.issues)
    with pytest.raises(ValueError, match='single_sequence execution requires null'):
        _materialize_exercise_definition(exercise)
    exercise['intraSetRestInSeconds'] = None
    validate_plan_index_contract(_plan(exercise))
    assert _materialize_exercise_definition(exercise)['intraSetRestInSeconds'] is None


def test_reviewed_set_mode_annotation_is_validated_and_projected():
    definition_id = '00000000-0000-0000-0000-000000000001'
    execution = {'setMode': 'paired_sides', 'source': 'https://example.com/execution',
                 'basis': 'Perform the prescribed repetitions in each direction.'}
    annotations = {'byDefinitionId': {definition_id: {'execution': execution}}}
    recipe_contracts._reviewed_exercise_annotations_by_definition.cache_clear()
    try:
        with patch.object(recipe_contracts.Path, 'read_text', return_value=json.dumps(annotations)):
            payload = {'exerciseDefinitions': [{'id': definition_id}]}
            overlaid = recipe_contracts.apply_reviewed_exercise_annotations(payload)
            assert overlaid['exerciseDefinitions'][0]['reviewedExecution'] == execution
            assert recipe_contracts.reviewed_execution_properties(payload)['propertiesByReference'] == {
                'LIBRARY_0': {'setMode': 'paired_sides'}}
            execution['setMode'] = 'guessed'
            recipe_contracts._reviewed_exercise_annotations_by_definition.cache_clear()
        with patch.object(recipe_contracts.Path, 'read_text', return_value=json.dumps(annotations)):
            with pytest.raises(ValueError, match='execution.setMode'):
                recipe_contracts._reviewed_exercise_annotations_by_definition()
    finally:
        recipe_contracts._reviewed_exercise_annotations_by_definition.cache_clear()


def test_native_allocation_audit_uses_compile_time_execution_without_changing_library():
    from workout_generator_pkg.allocation import _audit_raw
    from workout_generator_pkg.planning_tools import library_fingerprint
    from test_workout_generator_planning_tools import planning_case

    equipment, requirements, _, draft = planning_case()
    original = copy.deepcopy(equipment)
    fingerprint = library_fingerprint(equipment)
    exercise = draft['workouts'][0]['exercises'][0]
    exercise['satisfiesCoverage'] = ['rotational_core']
    exercise['intraSetRestInSeconds'] = 15
    definition = copy.deepcopy(equipment['exerciseDefinitions'][0])
    definition['reviewedExecution'] = {'limbMode': 'bilateral', 'setMode': 'paired_sides'}

    plan, report = _audit_raw(draft, equipment, requirements, None, True,
        execution_definitions={definition['id']: definition})

    assert plan['exercises'][0]['reviewedExecution']['setMode'] == 'paired_sides'
    assert plan['exercises'][0]['intraSetRestInSeconds'] == 15
    assert report['workouts'][0]['timing']['workSeconds'] == 5 * 10 * 3 * 2
    assert equipment == original
    assert library_fingerprint(equipment) == fingerprint


def test_required_execution_choice_returns_question_before_any_worker_call(monkeypatch):
    from workout_generator_pkg import session_drafting
    from test_workout_generator_parallel_planning import week_case

    # This fixture isolates execution counting from its separate personal-capability gate.
    monkeypatch.setattr(session_drafting, '_history_configuration_concerns', lambda *a, **k: {})
    monkeypatch.setattr(recipe_contracts, 'qualify_recipe_contracts', lambda *a, **k: {
        'contracts': [{'definition_id': 'LIBRARY_0', 'satisfiesCoverage': ['rotational_core']}]})
    equipment, messages, prepared, _ = week_case(coverage=[{'key': 'rotational_core', 'scope': 'weekly'}])
    monkeypatch.setattr(session_drafting, 'chat_call', lambda *a, **k: pytest.fail(
        'An unresolved required execution choice must stop before prescription workers.'))

    result = session_drafting.draft_workout_sessions(None,
        {'preparationId': prepared['preparationId']}, messages, equipment, {})

    assert not result['passed']
    assert result['errors'][0]['code'] == 'execution_semantics_unresolved'
    assert result['userQuestion']['executionChoices'][0]['canonicalDefinitionId'] == 'press'
    assert 'every listed movement' in result['userQuestion']['question']
    assert equipment['exerciseDefinitions'][0]['name'] + ' (LIBRARY_0)' in result['userQuestion']['question']
    assert 'before drafting' in result['instruction']
    assert not result.get('executionFailure')


def test_optional_ambiguous_menu_defers_native_audit_without_changing_worker_paths():
    from workout_generator_pkg.session_drafting import _execution_auditable_session, _execution_recipe_issues

    equipment = {'exerciseDefinitions': [{'id': 'a'}, {'id': 'b'}]}
    session = {'exercises': [
        {'definition_id': 'LIBRARY_0', 'satisfiesCoverage': ['rotational_core'], 'superset': None},
        {'definition_id': 'LIBRARY_1', 'satisfiesCoverage': ['horizontal_push'], 'superset': None},
    ]}
    original = copy.deepcopy(session)
    issues = _execution_recipe_issues([session], equipment, {})
    assert set(issues) == {'LIBRARY_0'}
    assert _execution_auditable_session(session, issues)['exercises'] == []
    assert _execution_auditable_session(session, {}) == original
    assert session == original


def test_solver_execution_question_survives_session_failure_wrapper(monkeypatch):
    from workout_generator_pkg import joint_planning, session_drafting
    from test_workout_generator_parallel_planning import week_case

    monkeypatch.setattr(session_drafting, '_history_configuration_concerns', lambda *a, **k: {})
    monkeypatch.setattr(recipe_contracts, 'qualify_recipe_contracts', lambda *a, **k: {'contracts': []})
    equipment, messages, prepared, exercises = week_case()
    calls = []
    def worker(client, request, **options):
        payload = json.loads(request[-1]['content'])
        calls.append(payload['recipes'])
        values = {key: {field: copy.deepcopy(value) for field, value in exercises[0].items()
                        if field in schema['properties']}
                  for key, schema in payload['responseSchema']['properties'].items()}
        return json.dumps(values), None, None
    monkeypatch.setattr(session_drafting, 'chat_call', worker)
    question = {'question': 'How should repetitions be counted?', 'options': ['Total', 'Per side']}
    issue = {'code': 'execution_semantics_unresolved', 'path': '/workouts/0/exercises/0'}
    monkeypatch.setattr(joint_planning, 'solve_prescribed_week', lambda *a, **k: {
        'feasible': False, 'status': 'execution_semantics_unresolved', 'userQuestion': question,
        'errors': [issue], 'instruction': 'Resolve the qualitative execution choice; do not repair numeric prescriptions.'})

    result = session_drafting.draft_workout_sessions(None,
        {'preparationId': prepared['preparationId']}, messages, equipment, {})

    assert result.get('userQuestion') == question, result
    assert result['errors'] == [issue]
    assert len(calls) == 1
    assert not result.get('executionFailure')
    assert 'do not repair numeric' in result['instruction']
