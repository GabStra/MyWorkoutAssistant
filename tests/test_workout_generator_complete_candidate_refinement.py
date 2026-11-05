import copy
import time

import pytest

from workout_generator_pkg import candidate_refinement, joint_planning as joint
from workout_generator_pkg.planning_tools import library_fingerprint


def _case():
    from test_workout_generator_joint_prescriptions import two_recipe_order_case

    equipment, requirements, sessions = two_recipe_order_case()
    requirements.update(objectiveOrder=['workload_economy', 'duration_economy', 'execution_order'],
        requiredCoverage=[{'key': 'first', 'scope': 'eachSession', 'description': 'Required fixture movement.'}],
        objectiveTiers=[[{'metric': 'workload_economy', 'target': 0, 'scale': 10, 'group': 'economy'},
            {'metric': 'duration_economy', 'target': 0, 'scale': 3000, 'group': 'economy'}]])
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 5, 'maximum': 6}
    requirements['auditTargets']['perSessionEffectiveSets'] = {}
    for index, item in enumerate(sessions[0]['exercises']):
        item.update(satisfiesCoverage=['first'], setupSeconds=300 if index == 0 else 0)
    definitions = {f'LIBRARY_{index}': definition for index, definition in enumerate(
        sorted(equipment['exerciseDefinitions'], key=lambda definition: definition['id']))}
    context = {'restrictionPolicy': {}, 'libraryFingerprint': library_fingerprint(equipment),
        'historyFingerprint': None, 'sourceWorkingSetBudget': None,
        'qualifiedRoleEvidence': {reference: ['first'] for reference in definitions},
        'demandEvidence': {'status': 'unavailable', 'groups': {}}, 'demandUnion': None,
        'setupDefinitions': definitions}
    fixed_work = [{definition['id']: 5 if index == 0 else 0
        for index, definition in enumerate(definitions.values())}]
    seed = joint._solve_prescribed_week(sessions, requirements, equipment,
        _fixed_session_work=fixed_work, search_deadline=time.monotonic() + 10)
    assert seed['feasible'] and not seed['audit']['errors'], seed
    return equipment, requirements, sessions, context, seed


def test_complete_feedback_promotes_audited_cross_menu_improvement_under_same_grouped_policy():
    equipment, requirements, sessions, context, seed = _case()
    before = copy.deepcopy((requirements, sessions, seed))
    result = candidate_refinement.refine_complete_candidate(seed, sessions, requirements, equipment,
        search_deadline=time.monotonic() + 10, context=context)

    assert result['completeCandidateRefinement']['status'] == 'promoted_complete_candidate', result
    assert seed['sessions'][0]['exercises'][0]['definition_id'] == 'LIBRARY_0'
    assert result['sessions'][0]['exercises'][0]['definition_id'] == 'LIBRARY_1'
    assert seed['audit']['weeklyWorkingSets'] == result['audit']['weeklyWorkingSets'] == 5
    assert seed['audit']['weeklyVolume'] == result['audit']['weeklyVolume']
    assert seed['audit']['weeklyCoverageSets'] == result['audit']['weeklyCoverageSets'] == {'first': 5}
    assert result['audit']['workouts'][0]['estimatedSeconds'] == seed['audit']['workouts'][0]['estimatedSeconds'] - 300
    assert not result['audit']['errors']
    compared = result['completeCandidateRefinement']['comparison']
    assert compared['baselineAuditErrors'] == compared['candidateAuditErrors'] == []
    assert compared['firstDifferingObjective'] == 'goal_tier_0_total'
    assert result['completeCandidateRefinement']['candidateModel']['physicalBlockCount'] == 2
    assert result['status'] == result['jointModelStatus'] == 'feasible'
    assert all(stage['status'] == 'feasible' and stage['neighborhoodOptimal']
        and stage['scope'] == 'bounded_complete_candidate_neighborhood'
        for stage in result['objectiveProgress'])
    assert not any(priority['status'] in ('optimal', 'optimal_zero_lower_bound')
        for priority in result['priorityExecution']['approvedPriorities'])
    assert (requirements, sessions, seed) == before


@pytest.mark.parametrize('failure', ['timeout', 'native_error', 'unqualified_role'])
def test_complete_feedback_retains_incumbent_when_candidate_cannot_be_promoted(monkeypatch, failure):
    equipment, requirements, sessions, context, seed = _case()
    attempted = []
    deadline = time.monotonic() + 10

    def candidate(*args, **kwargs):
        attempted.append(kwargs)
        if failure == 'timeout':
            return {'feasible': False, 'status': 'unproven'}
        value = copy.deepcopy(seed)
        if failure == 'native_error':
            value['audit']['errors'].append({'code': 'fixture_hard_failure'})
        else:
            value['sessions'][0]['exercises'][0]['satisfiesCoverage'] = ['unqualified']
        return value

    monkeypatch.setattr(joint, '_solve_prescribed_week', candidate)
    result = candidate_refinement.refine_complete_candidate(seed, sessions, requirements, equipment,
        search_deadline=deadline, context=context,
        redistribution_constraints=[{'fixture': 'preserve'}])

    assert result['sessions'] == seed['sessions'] and result['audit'] == seed['audit']
    assert result['completeCandidateRefinement']['promotedCandidateCount'] == 0
    assert len(attempted) == 1 and attempted[0]['search_deadline'] == deadline
    assert attempted[0]['_prescription_seed'] == seed['sessions']
    assert attempted[0]['redistribution_constraints'] == [{'fixture': 'preserve'}]
    assert '_fixed_session_work' not in attempted[0] and '_selection_prefix_bounds' not in attempted[0]


def test_complete_feedback_skips_model_construction_when_shared_budget_is_nearly_spent(monkeypatch):
    equipment, requirements, sessions, context, seed = _case()
    monkeypatch.setattr(joint, '_solve_prescribed_week',
        lambda *args, **kwargs: pytest.fail('A nearly expired budget constructed another coupled model.'))
    result = candidate_refinement.refine_complete_candidate(seed, sessions, requirements, equipment,
        search_deadline=time.monotonic() + 1, context=context)
    assert result['sessions'] == seed['sessions']
    assert result['completeCandidateRefinement']['status'] == 'skipped_insufficient_remaining_budget'
    assert result['completeCandidateRefinement']['attemptedCandidateCount'] == 0


def test_bounded_neighborhood_reduces_actual_model_and_preserves_original_occurrence_indexes():
    equipment, requirements, sessions, context, _ = _case()
    original_items = sessions[0]['exercises']
    for index, identifier in enumerate(('unused_a', 'unused_b'), 2):
        definition = {**copy.deepcopy(equipment['exerciseDefinitions'][0]), 'id': identifier}
        equipment['exerciseDefinitions'].append(definition)
        reference = f'LIBRARY_{index}'
        original_items.append({**copy.deepcopy(original_items[0]), 'definition_id': reference,
            'setupSeconds': 500 + index * 10})
        context['setupDefinitions'][reference] = definition
        context['qualifiedRoleEvidence'][reference] = ['first']
    sessions[0]['exercises'] = [original_items[index] for index in (2, 0, 3, 1)]
    context['libraryFingerprint'] = library_fingerprint(equipment)
    definitions = dict(sorted((definition['id'], definition)
        for definition in equipment['exerciseDefinitions']))
    selected_id = context['setupDefinitions']['LIBRARY_0']['id']
    seed = joint._solve_prescribed_week(sessions, requirements, equipment,
        _fixed_session_work=[{identifier: 5 if identifier == selected_id else 0
            for identifier in definitions}], search_deadline=time.monotonic() + 10)
    full = joint._solve_prescribed_week(sessions, requirements, equipment,
        search_deadline=time.monotonic() + 10)
    before = copy.deepcopy(sessions)
    result = candidate_refinement.refine_complete_candidate(seed, sessions, requirements, equipment,
        search_deadline=time.monotonic() + 10, context=context)

    evidence = result['completeCandidateRefinement']
    assert evidence['status'] == 'promoted_complete_candidate', evidence
    assert evidence['neighborhood']['addedDefinitionIds'] == ['row']
    assert evidence['neighborhood']['eligibleDefinitionCount'] == 2
    assert evidence['neighborhood']['fullMenuDefinitionCount'] == 4
    assert evidence['neighborhood']['omittedDefinitionCount'] == 2
    assert evidence['candidateModel']['physicalBlockCount'] == 2 < full['physicalBlockCount'] == 4
    assert evidence['candidateModel']['optionCount'] < full['optionCount']
    assert result['occurrenceLineage'] == [[[0, 3]]]
    assert result['sessions'][0]['exercises'][0]['definition_id'] == sessions[0]['exercises'][3]['definition_id']
    assert not result['audit']['errors'] and sessions == before


def test_neighborhood_admits_late_sorted_audited_goal_improvement_instead_of_first_unused_ids():
    equipment, requirements, sessions, context, seed = _case()
    sessions[0]['exercises'][1]['setupSeconds'] = 250
    for index, (identifier, setup, roles) in enumerate((
            ('unused_a', 200, ['first']), ('zzz_best', 0, ['first']),
            ('zzzz_unqualified', 0, [])), 2):
        definition = {**copy.deepcopy(equipment['exerciseDefinitions'][0]), 'id': identifier}
        equipment['exerciseDefinitions'].append(definition)
        reference = f'LIBRARY_{index}'
        sessions[0]['exercises'].append({**copy.deepcopy(sessions[0]['exercises'][0]),
            'definition_id': reference, 'setupSeconds': setup, 'satisfiesCoverage': roles})
        context['setupDefinitions'][reference] = definition
        context['qualifiedRoleEvidence'][reference] = roles
    context['libraryFingerprint'] = library_fingerprint(equipment)
    before = copy.deepcopy((requirements, sessions, seed))
    result = candidate_refinement.refine_complete_candidate(seed, sessions, requirements, equipment,
        search_deadline=time.monotonic() + 10, context=context,
        source_working_set_budget={'source': 'user_fixed', 'variableWeeklyWorkingSets': 5})

    evidence = result['completeCandidateRefinement']
    assert evidence['neighborhood']['addedDefinitionIds'] == ['zzz_best', 'unused_a']
    assert evidence['exchangeScreening']['evaluatedDefinitionIds'] == [
        'row', 'unused_a', 'zzz_best', 'zzzz_unqualified']
    assert not evidence['exchangeScreening']['budgetExhausted']
    assert all(entry['firstDifferingObjective'] == 'goal_tier_0_total'
        for entry in evidence['exchangeScreening']['admittedWitnesses'])
    assert result['sessions'][0]['exercises'][0]['definition_id'] == 'LIBRARY_3'
    assert result['occurrenceLineage'] == [[[0, 3]]]
    assert not result['audit']['errors']
    assert result['audit']['weeklyWorkingSets'] == seed['audit']['weeklyWorkingSets'] == 5
    assert result['audit']['weeklyVolume'] == seed['audit']['weeklyVolume']
    assert result['audit']['weeklyCoverageSets'] == seed['audit']['weeklyCoverageSets']
    assert evidence['candidateModel']['physicalBlockCount'] == 3
    assert (requirements, sessions, seed) == before


@pytest.mark.parametrize('exact_prescriptions', [False, True])
def test_neighborhood_falls_back_to_selected_definitions_without_a_beneficial_exchange(exact_prescriptions):
    equipment, requirements, sessions, context, seed = _case()
    alternative = sessions[0]['exercises'][1]
    if exact_prescriptions:
        alternative['targetSetPrescriptions'] = [{'workSetIndex': index, 'reps': 8} for index in range(3)]
        alternative['numWorkSets'] = 3
    else:
        alternative['setupSeconds'] = 500
    before = copy.deepcopy((sessions, seed))
    result = candidate_refinement.refine_complete_candidate(seed, sessions, requirements, equipment,
        search_deadline=time.monotonic() + 10, context=context)

    evidence = result['completeCandidateRefinement']
    assert evidence['neighborhood']['addedDefinitionIds'] == []
    assert evidence['exchangeScreening']['fallback'] == 'selected_definitions_only'
    assert evidence['exchangeScreening']['beneficialExchangeCount'] == 0
    if exact_prescriptions:
        assert evidence['exchangeScreening']['evaluatedExchangeCount'] == 0
    assert result['sessions'] == seed['sessions']
    assert (sessions, seed) == before


def test_bounded_neighborhood_skips_source_selection_preservation(monkeypatch):
    equipment, requirements, sessions, context, seed = _case()
    monkeypatch.setattr(joint, '_solve_prescribed_week',
        lambda *args, **kwargs: pytest.fail('Preserved source selection entered a pruned domain.'))
    result = candidate_refinement.refine_complete_candidate(seed, sessions, requirements, equipment,
        search_deadline=time.monotonic() + 10, context=context, preserve_source_selection=True)
    assert result['sessions'] == seed['sessions']
    assert result['completeCandidateRefinement']['status'] == 'skipped_preserved_source_selection'


def test_unknown_neighborhood_recipe_retains_the_audited_seed(monkeypatch):
    equipment, requirements, sessions, context, seed = _case()
    sessions[0]['exercises'][1]['definition_id'] = 'UNAVAILABLE_RECIPE'
    monkeypatch.setattr(joint, '_solve_prescribed_week',
        lambda *args, **kwargs: pytest.fail('An unsupported recipe reached coupled search.'))
    result = candidate_refinement.refine_complete_candidate(seed, sessions, requirements, equipment,
        search_deadline=time.monotonic() + 10, context=context)
    assert result['sessions'] == seed['sessions']
    assert result['completeCandidateRefinement']['status'] == 'skipped_unsupported_recipe_reference'
    assert result['completeCandidateRefinement']['unsupportedDefinitionReferences'] == ['UNAVAILABLE_RECIPE']


def test_public_solver_can_reconsider_seed_selection_within_the_same_deadline(monkeypatch):
    from workout_generator_pkg import allocation

    equipment, requirements, sessions, context, seed = _case()
    core = joint._solve_prescribed_week
    deadlines = []

    def seed_then_coupled(*args, **kwargs):
        deadlines.append(kwargs['search_deadline'])
        if kwargs.get('_selection_only') or kwargs.get('_fixed_session_work') is not None:
            return copy.deepcopy(seed)
        return core(*args, **kwargs)

    monkeypatch.setattr(joint, '_solve_prescribed_week', seed_then_coupled)
    monkeypatch.setattr(allocation, '_joint_candidate_comparison_context', lambda *args, **kwargs: context)
    deadline = time.monotonic() + 15
    result = joint.solve_prescribed_week(sessions, requirements, equipment, search_deadline=deadline)

    assert len(deadlines) == 3 and deadlines[0] < deadlines[1] < deadlines[2] == deadline
    assert result['completeCandidateRefinement']['status'] == 'promoted_complete_candidate'
    assert result['sessions'][0]['exercises'][0]['definition_id'] == 'LIBRARY_1'
    assert result['audit']['weeklyWorkingSets'] == seed['audit']['weeklyWorkingSets'] == 5
    assert not result['audit']['errors']
