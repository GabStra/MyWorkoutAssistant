import copy
import time

import pytest

from workout_generator_pkg import joint_planning as joint
from workout_generator_pkg.generation_audit import executable_setup_evidence
from workout_generator_pkg.planning_tools import library_fingerprint


def _case(include_unknown=False):
    from test_workout_generator_joint_prescriptions import two_recipe_order_case

    equipment, requirements, sessions = two_recipe_order_case()
    equipment['accessoryEquipments'] = [{'id': 'ACCESSORY_0', 'name': 'Adjustable bench'}]
    requirements['objectiveOrder'] = ['setup_economy']
    for definition, state in zip(equipment['exerciseDefinitions'], ('flat', 'inclined')):
        definition['requiredAccessoryEquipmentIds'] = ['ACCESSORY_0']
        definition['requiresLoadCalibration'] = True
        definition['reviewedExecution'] = {'setupConfiguration': [{'resourceId': 'ACCESSORY_0',
            'state': {'backrest': state}, 'source': 'https://example.test/bench',
            'basis': 'Required bench state for this controlled fixture.'}]}
    for source in sessions[0]['exercises']:
        source['setupSeconds'] = 0
    if include_unknown:
        definition = copy.deepcopy(equipment['exerciseDefinitions'][1])
        definition.update(id='zzz_unknown', name='Undescribed bench variant')
        definition.pop('reviewedExecution')
        equipment['exerciseDefinitions'].append(definition)
        source = copy.deepcopy(sessions[0]['exercises'][1])
        source['definition_id'] = 'LIBRARY_2'
        sessions[0]['exercises'].append(source)
    definitions = {f'LIBRARY_{index}': definition for index, definition in enumerate(
        sorted(equipment['exerciseDefinitions'], key=lambda item: item['id']))}
    context = {'restrictionPolicy': {}, 'libraryFingerprint': library_fingerprint(equipment),
        'historyFingerprint': None, 'sourceWorkingSetBudget': None,
        'qualifiedRoleEvidence': {source['definition_id']: source['satisfiesCoverage']
            for source in sessions[0]['exercises']},
        'demandEvidence': {'status': 'unavailable', 'groups': {}}, 'demandUnion': None,
        'setupDefinitions': definitions, 'setupEquipmentById': {}}
    return equipment, requirements, sessions, context


def _solve(equipment, requirements, sessions, selected=None):
    fixed = ({definition['id']: 5 if definition['id'] in selected else 0
        for definition in equipment['exerciseDefinitions']} if selected is not None else None)
    result = joint._solve_prescribed_week(sessions, requirements, equipment,
        _fixed_session_work=[fixed] if fixed is not None else None,
        search_deadline=time.monotonic() + 10)
    assert result['feasible'] and not result['audit']['errors'], result
    return result


def test_native_primary_setup_cost_matches_shared_tracker_with_unknown_loads():
    equipment, requirements, sessions, context = _case()
    result = _solve(equipment, requirements, sessions)
    candidate = {'workouts': result['sessions'], 'audit': result['audit']}
    audit = executable_setup_evidence(result['sessions'][0], context['setupDefinitions'])
    costs = joint._joint_candidate_objective_costs(candidate, requirements, context)
    stage = next(stage for stage in result['objectiveProgress'] if stage['goal'] == 'setup_economy')
    assert stage['value'] == costs['setup_economy'] == audit['physicalPreparationCount'] == 2
    assert audit['physicalRequiredChanges'] == costs['setup_economy_transitions'] == 1
    assert audit['unknownPhysicalPreparationCount'] > 0


def test_undescribed_replacement_cannot_win_by_hiding_known_setup_conflict():
    from workout_generator_pkg.allocation import _audit_raw

    equipment, requirements, sessions, context = _case(include_unknown=True)
    candidates = []
    for selected in ({'LIBRARY_0', 'LIBRARY_1'}, {'LIBRARY_0', 'LIBRARY_2'}):
        workouts = copy.deepcopy(sessions)
        workouts[0]['exercises'] = [source for source in workouts[0]['exercises']
            if source['definition_id'] in selected]
        _, audit = _audit_raw({'name': 'Controlled setup comparison', 'workouts': workouts},
            equipment, requirements, {}, True)
        assert not audit['errors'], audit
        candidates.append({'workouts': workouts, 'audit': audit})
    baseline, candidate = candidates
    assert joint._joint_candidate_objective_costs(candidate, requirements, context)['setup_economy'] < (
        joint._joint_candidate_objective_costs(baseline, requirements, context)['setup_economy'])
    comparison = joint.compare_audited_joint_candidates(baseline, candidate,
        requirements=requirements, context=context)
    assert comparison['baselineAuditErrors'] == comparison['candidateAuditErrors'] == []
    assert comparison['decision'] == 'incomparable'
    assert comparison['reason'] == 'candidate_setup_evidence_loss'


@pytest.mark.parametrize('unknown_selected', [False, True])
def test_menu_annotation_gaps_are_diagnostic_not_hard_infeasibility(unknown_selected):
    equipment, requirements, sessions, _ = _case(include_unknown=True)
    selected = {equipment['exerciseDefinitions'][0]['id'],
        'zzz_unknown' if unknown_selected else 'row'}
    result = joint._solve_prescribed_week(sessions, requirements, equipment,
        _fixed_session_work=[{d['id']: 5 if d['id'] in selected else 0
            for d in equipment['exerciseDefinitions']}],
        search_deadline=time.monotonic() + 10)
    assert result['feasible'] and not result['audit']['errors'], result
    assert bool(result['setupEvidenceGaps']) == unknown_selected
    if unknown_selected:
        assert result['setupEvidenceGaps'][0]['missingStateDimensions'] == ['backrest']


def test_unused_annotated_alternative_does_not_invalidate_selected_plan():
    equipment, requirements, sessions, _ = _case(include_unknown=True)
    equipment['exerciseDefinitions'][0].pop('reviewedExecution')
    selected = {equipment['exerciseDefinitions'][0]['id'], 'zzz_unknown'}
    full = _solve(equipment, requirements, sessions, selected)
    equipment['exerciseDefinitions'] = [d for d in equipment['exerciseDefinitions'] if d['id'] != 'row']
    sessions[0]['exercises'] = [item for item in sessions[0]['exercises'] if item['definition_id'] != 'LIBRARY_1']
    sessions[0]['exercises'][1]['definition_id'] = 'LIBRARY_1'
    reduced = _solve(equipment, requirements, sessions, selected)
    assert full['setupEvidenceGaps'] and not reduced['setupEvidenceGaps']
    assert full['audit']['weeklyWorkingSets'] == reduced['audit']['weeklyWorkingSets']


def test_selected_setup_gate_ignores_unselected_resource_roles():
    row = {'resourceId': 'bench', 'role': 'accessory', 'implementQuantity': None,
        'loadRequired': False, 'knownStateDimensions': ['backrest'], 'loadKnown': False}
    selected = {**row, 'resourceId': 'floor', 'knownStateDimensions': []}
    assert joint._selected_setup_evidence_gaps([row], [
        {'workoutIndex': 0, 'setup': {'setupEvidenceCoverage': [selected]}}]) == []


def test_unchanged_mixed_setup_evidence_is_not_reported_as_new_evidence_loss():
    _, requirements, sessions, context = _case(include_unknown=True)
    workout = copy.deepcopy(sessions[0])
    workout['exercises'] = [source for source in workout['exercises']
        if source['definition_id'] != 'LIBRARY_1']
    evidence = joint._candidate_setup_transition_evidence(workout,
        context['setupDefinitions'], requirements)
    assert joint._setup_evidence_losses([evidence], [copy.deepcopy(evidence)]) == []


@pytest.mark.parametrize('from_decision', [False, True])
def test_known_setup_configuration_uses_coupled_search_without_approximate_prefix(monkeypatch, from_decision):
    equipment, requirements, sessions, context = _case()
    requirements['objectiveOrder'] = ['setup_economy', 'workload_economy', 'execution_order']
    calls, solve = [], joint._solve_prescribed_week
    if from_decision:
        from workout_generator_pkg import planning_decisions
        overrides = {d['id']: copy.deepcopy(d) for d in equipment['exerciseDefinitions']}
        for definition in overrides.values():
            definition['reviewedExecution']['setMode'] = 'single_sequence'
        for definition in equipment['exerciseDefinitions']:
            definition.pop('reviewedExecution')
        monkeypatch.setattr(planning_decisions, 'execution_decision_definitions', lambda *a: overrides)
        context['setupDefinitions'] = {reference: overrides[d['id']]
            for reference, d in context['setupDefinitions'].items()}

    def recorded(*args, **kwargs):
        calls.append(kwargs)
        return solve(*args, **kwargs)

    monkeypatch.setattr(joint, '_solve_prescribed_week', recorded)
    result = joint.solve_prescribed_week(sessions, requirements, equipment,
        search_deadline=time.monotonic() + 10)
    assert result['feasible'] and not result['audit']['errors'], result
    assert len(calls) == 1
    assert not calls[0].get('_selection_only')
    assert '_selection_prefix_bounds' not in calls[0]
    assert 'splitArchitecture' not in result
    costs = joint._joint_candidate_objective_costs(
        {'workouts': result['sessions'], 'audit': result['audit']}, requirements, context)
    stage = next(stage for stage in result['objectiveProgress'] if stage['goal'] == 'setup_economy')
    assert stage['value'] == costs['setup_economy'] == 2
