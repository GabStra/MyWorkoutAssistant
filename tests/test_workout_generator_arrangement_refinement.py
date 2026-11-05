import copy

import pytest

from workout_generator_pkg.joint_planning import refine_group_arrangements
from workout_generator_pkg.planning_tools import library_fingerprint
from test_workout_generator_planning_tools import planning_case


def arrangement_case():
    equipment, requirements, _, draft = planning_case()
    source = draft['workouts']
    template = copy.deepcopy(source[0]['exercises'][0])
    definition = copy.deepcopy(equipment['exerciseDefinitions'][0])
    equipment['exerciseDefinitions'] = []
    source[0]['exercises'] = []
    for index in range(4):
        equipment['exerciseDefinitions'].append({**copy.deepcopy(definition),
            'id': f'exercise_{index}', 'requiredAccessoryEquipmentIds': ['ACCESSORY_0' if index % 2 == 0 else 'ACCESSORY_1']})
        source[0]['exercises'].append({**copy.deepcopy(template), 'definition_id': f'LIBRARY_{index}',
            'numWorkSets': 3, 'workSetTemplate': {'reps': 8, 'additionalWeight': 0},
            'restBetweenSetsSeconds': 90, 'setupSeconds': 10})
    equipment['accessoryEquipments'] = [{'id': value, 'name': value} for value in ('ACCESSORY_0', 'ACCESSORY_1')]
    requirements['auditTargets'].update(maximumSessionSeconds=10000,
        weeklyEffectiveSets={'chest': {'minimum': 12, 'maximum': 12}},
        perSessionEffectiveSets={'chest': {'minimum': 12, 'maximum': 12}})
    requirements.update(objectiveOrder=['setup_economy', 'duration_economy'],
        requiredCoverage=[], executionRules=[])
    sessions = copy.deepcopy(source)
    for index, item in enumerate(sessions[0]['exercises']):
        item.update(superset=f'PAIR_{index // 2}', restBetweenSetsSeconds=0,
            restAfterSupersetExerciseSeconds=10 if index % 2 == 0 else 90)
    definitions = {f'LIBRARY_{index}': value for index, value in enumerate(equipment['exerciseDefinitions'])}
    context = {'restrictionPolicy': {}, 'libraryFingerprint': library_fingerprint(equipment),
        'historyFingerprint': None, 'sourceWorkingSetBudget': None,
        'qualifiedRoleEvidence': {reference: [] for reference in definitions},
        'demandEvidence': {'status': 'disabled_by_approved_objective_order'}, 'demandUnion': None,
        'setupDefinitions': definitions, 'fixedWorkouts': []}
    return equipment, requirements, source, sessions, context


def test_setup_only_arrangements_choose_fewer_switches_without_changing_dose():
    equipment, requirements, source, sessions, context = arrangement_case()
    requirements['objectiveOrder'] = ['setup_economy']
    source.append(copy.deepcopy(source[0]))
    sessions.append(copy.deepcopy(sessions[0]))
    requirements['sessionsPerWeek'] = 2
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 24, 'maximum': 24}
    requirements['requiredCoverage'] = [{'key': 'horizontal_push', 'scope': 'weekly',
        'description': 'Include horizontal pressing during the week.'}]
    for item in source[0]['exercises'] + sessions[0]['exercises']:
        item['satisfiesCoverage'] = ['horizontal_push']
    for index in range(4):
        reference = f'LIBRARY_{index + 4}'
        definition = {**copy.deepcopy(equipment['exerciseDefinitions'][index]),
            'id': f'exercise_{index + 4}'}
        equipment['exerciseDefinitions'].append(definition)
        source[1]['exercises'][index]['definition_id'] = reference
        sessions[1]['exercises'][index]['definition_id'] = reference
        context['qualifiedRoleEvidence'][f'LIBRARY_{index}'] = ['horizontal_push']
        context['qualifiedRoleEvidence'][reference] = []
        context['setupDefinitions'][reference] = definition
    context['libraryFingerprint'] = library_fingerprint(equipment)
    result = refine_group_arrangements(sessions, requirements, equipment,
        source_sessions=source, context=context)

    assert not result['audit']['errors'], result
    assert result['selectedMask'] == '11/11'
    assert result['evaluatedSessionVariantCount'] == 8
    assert result['evaluatedWeeklyCombinationCount'] == 16
    assert result['fullWeekAuditCount'] == 2
    assert result['audit']['weeklyWorkingSets'] == 24
    assert result['audit']['weeklyVolume']['chest']['effective'] == 24
    original = {item['definition_id']: item for item in source[0]['exercises']}
    for item in result['sessions'][0]['exercises']:
        assert item['numWorkSets'] == 3
        assert item['restBetweenSetsSeconds'] == 90
        for field in ('workSetTemplate', 'effortAcceptance', 'generateWarmUpSets'):
            assert item[field] == original[item['definition_id']][field]
    assert len(result['frontier']) >= 2


def test_repeated_definition_lineage_restoration_keeps_occurrence_specific_recovery():
    equipment, requirements, source, sessions, context = arrangement_case()
    requirements['objectiveOrder'] = ['setup_economy']
    source[0]['exercises'][2]['definition_id'] = 'LIBRARY_0'
    sessions[0]['exercises'][2]['definition_id'] = 'LIBRARY_0'
    source[0]['exercises'][2]['restBetweenSetsSeconds'] = 120
    result = refine_group_arrangements(sessions, requirements, equipment,
        source_sessions=source, context=context)

    assert result['selectedMask'] == '11', result
    for item, token in zip(result['sessions'][0]['exercises'], result['occurrenceLineage'][0]):
        assert item['restBetweenSetsSeconds'] == source[token[0]]['exercises'][token[1]]['restBetweenSetsSeconds']
    assert sorted(result['occurrenceLineage'][0]) == [[0, index] for index in range(4)]


def test_approved_rest_range_is_the_only_authority_for_shorter_recovery():
    equipment, requirements, source, sessions, context = arrangement_case()
    requirements['objectiveOrder'] = ['setup_economy']
    requirements['executionRules'] = [{'kind': 'rest', 'context': 'straightSets',
        'coverageKey': None, 'minimumSeconds': 75, 'maximumSeconds': 120}]
    result = refine_group_arrangements(sessions, requirements, equipment,
        source_sessions=source, context=context)

    assert result['selectedMask'] == '11', result
    assert all(item['restBetweenSetsSeconds'] == 75 for item in result['sessions'][0]['exercises'])
    assert not result['audit']['errors']


@pytest.mark.parametrize('reviewed', [False, True])
def test_joint_solver_refines_final_groups_and_preserves_patch_lineage_and_proof_scope(reviewed):
    from workout_generator_pkg.joint_planning import solve_prescribed_week, prescription_patch
    from workout_generator_pkg.json_patching import apply_json_patch
    from workout_generator_pkg.generation_audit import render_optimization_disclosure

    equipment, requirements, source, paired, _ = arrangement_case()
    requirements['objectiveOrder'] = ['setup_economy', 'exercise_distribution', 'role_concentration']
    requirements['executionRules'] = [{'kind': 'workSets', 'coverageKey': None,
        'minimumSets': 3, 'maximumSets': 3}]
    source[0]['exercises'].extend(copy.deepcopy(paired[0]['exercises']))
    for item in source[0]['exercises']:
        item.pop('placementNotes', None)
    before = copy.deepcopy(source)
    result = solve_prescribed_week(source, requirements, equipment,
        reviewed_baseline_workouts=source if reviewed else None)

    assert result['feasible'], result
    assert not result['audit']['errors']
    refinement = result['arrangementRefinement']
    assert refinement['selectedMask'] is not None
    assert refinement['after']['weeklyDeclaredResourceSwitches'] < refinement['before']['weeklyDeclaredResourceSwitches']
    assert result['status'] == 'feasible'
    assert result['jointModelStatus'] == 'optimal'
    assert all(entry['status'] not in ('optimal', 'optimal_zero_lower_bound')
        for entry in result['priorityExecution']['approvedPriorities'])
    assert result['exerciseDistribution']['status'] not in ('optimal', 'optimal_zero_lower_bound')
    assert result['exerciseDistribution']['developmentPriority']['status'] not in ('optimal', 'optimal_zero_lower_bound')
    assert result['priorityExecution']['structuralConcentration']['rolePlacement']['sumTieBreakStatus'] not in ('optimal', 'optimal_zero_lower_bound')
    patch = prescription_patch(before, result['sessions'], result['occurrenceLineage'])
    assert apply_json_patch({'workouts': before}, patch)['workouts'] == result['sessions']
    assert source == before
    assert 'global optimality of this final arrangement is not established' in render_optimization_disclosure(result['priorityExecution'])


def test_weekly_cartesian_limit_retains_the_audited_plan_without_a_search_claim():
    equipment, requirements, source, sessions, context = arrangement_case()
    source = [copy.deepcopy(source[0]) for _ in range(7)]
    sessions = [copy.deepcopy(sessions[0]) for _ in range(7)]
    requirements['sessionsPerWeek'] = 7
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 84, 'maximum': 84}
    result = refine_group_arrangements(sessions, requirements, equipment,
        source_sessions=source, context=context)

    assert result['status'] == 'not_searched_weekly_combination_limit'
    assert result['availableWeeklyCombinationCount'] == 16384
    assert result['selectedMask'] is None
    assert result['sessions'] == sessions
    assert not result['audit']['errors']
