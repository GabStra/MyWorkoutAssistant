import copy
import json

from workout_generator_pkg import session_drafting
from workout_generator_pkg.planner_context import request_planning_state
from test_workout_generator_parallel_planning import week_case, store_tool, shell


def test_prescription_context_preserves_related_configuration_evidence_and_load_ceilings():
    equipment = {'exerciseDefinitions': [{'id': 'movement', 'equipmentId': 'selected'}]}
    related = {'reference': 'HISTORY_0', 'candidateContext': {'equipmentId': 'historical'},
        'candidateConfigurationHistory': {'matchingConfigurationPerformanceCount': 2},
        'otherSetupSessions': [{'comparisonLimitations': ['Accounting differs']}],
        'uncertainty': ['Effort unknown'], 'loadHeadroom': {'maximumSelectableLoadKg': 42}}
    direct = {'reference': 'LIBRARY_0', 'candidateContext': {'equipmentId': 'selected'},
        'relatedMovementHistory': [{'reference': 'HISTORY_0', 'loadTransfer': 'Forbidden'}],
        'loadSuitabilityConcerns': [{'code': 'related_history_ceiling_requires_reassessment'}]}
    state = {'trainingEvidence': {'LIBRARY_0': direct, 'HISTORY_0': related,
        'UNUSED': {'unrelated': True}}, 'equipmentLoadOptions': {
            'selected': {'selectableLoadsKg': [0, 17, 42]},
            'historical': {'selectableLoadsKg': [3, 11]},
            'unused': {'selectableLoadsKg': [999]}}}
    original = copy.deepcopy(state)
    sources = {'messages': ['Exactly 17 reps; exclude the unweighted variant.']}
    payload = session_drafting._prescription_payload(
        {'RECIPE_0': {'definition_id': 'LIBRARY_0', 'minReps': 17}},
        {'requirements': {'workingSetRIR': {'minimum': 1, 'maximum': 2}}},
        {'sourceMessages': sources, 'candidates': {'LIBRARY_0': {'name': 'Selected variant'}}},
        {}, state, equipment)
    assert payload['history'] == {'LIBRARY_0': direct, 'HISTORY_0': related}
    assert payload['sourceMessages'] == sources
    assert payload['equipmentLoadOptions'] == {key: state['equipmentLoadOptions'][key]
        for key in ('selected', 'historical')}
    assert 'responseSchema' not in payload
    assert state == original
    state['trainingEvidence']['HISTORY_0']['candidateContext'] = {}
    legacy = session_drafting._prescription_payload(payload['recipes'], {'requirements': {}},
        {'sourceMessages': sources, 'candidates': payload['candidates']}, {}, state, equipment)
    assert legacy['equipmentLoadOptions'] == state['equipmentLoadOptions']


def test_changed_menu_reuses_only_unchanged_prescriptions_and_history_changes_invalidate_them(monkeypatch):
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
        lambda *a, **k: {'inputHash': 'qualified-fixture', 'contracts': [], 'capabilities': {}})
    equipment, messages, prepared, exercises = week_case(working_set_rir={'minimum': 1, 'maximum': 2})
    state = request_planning_state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    state['trainingEvidence'] = {'LIBRARY_0': {
        'candidateContext': {'equipmentId': 'EQUIPMENT_0'},
        'relatedMovementHistory': [{'reference': 'HISTORY_0'}]}, 'HISTORY_0': {
        'candidateContext': {'equipmentId': None}, 'uncertainty': ['Effort unknown'],
        'candidateConfigurationHistory': {'matchingConfigurationPerformanceCount': 1}}}
    calls, checkpoints = [], []

    def choose(client, request, **options):
        payload = json.loads(request[-1]['content'])
        calls.append(payload)
        assert 'responseSchema' not in payload
        values = {key: {field: copy.deepcopy(value) for field, value in exercises[0].items()
            if field in schema['properties']}
            for key, schema in options['output_schema']['properties'].items()}
        return json.dumps(values), None, None

    def interrupt_workers(*args, **kwargs):
        raise RuntimeError('Interrupted after the complete prescription response')

    monkeypatch.setattr(session_drafting, 'chat_call', choose)
    monkeypatch.setattr(session_drafting, 'parallel_proposals', interrupt_workers)
    arguments = {'preparationId': prepared['preparationId']}

    def run():
        result = session_drafting.draft_workout_sessions(None, arguments, messages, equipment, state,
            checkpoint=lambda value: checkpoints.append(copy.deepcopy(value)))
        assert result['errors'][0]['message'] == 'Interrupted after the complete prescription response'
        store_tool(messages, 'draft_workout_sessions', arguments, result)
        return result

    first = run()
    assert len(first['prescriptionResults']) == 1
    assert len(calls[0]['recipes']) == 1
    assert not first['workerResults']
    # Change one occurrence's authoritative prescription, keeping other recipes intact.
    prepared['recipeSessions'][0]['exercises'][0].update(minReps=10, maxReps=10)
    store_tool(messages, 'prepare_workout_sessions', {}, prepared)
    checkpoints.clear()
    second = run()
    assert len(second['prescriptionResults']) == 2
    assert len(calls[1]['recipes']) == 1
    assert next(iter(calls[1]['recipes'].values()))['minReps'] == 10
    assert checkpoints[0]['prescriptionResults'] == first['prescriptionResults']
    # Refining a related setup comparison changes the actual judgment input.
    state['trainingEvidence']['HISTORY_0']['candidateConfigurationHistory']['matchingConfigurationPerformanceCount'] = 2
    third = run()
    assert len(third['prescriptionResults']) == 2
    assert len(calls[2]['recipes']) == 2
    assert all(payload['history']['HISTORY_0']['uncertainty'] == ['Effort unknown'] for payload in calls)
