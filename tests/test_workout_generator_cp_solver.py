import copy
import itertools
import math

import pytest

from workout_generator_pkg import cp_solver, joint_planning
from workout_generator_pkg.generation_audit import setup_resource_profile
from workout_generator_pkg.programming_guidelines import execution_interference_score


def test_joint_sequence_opener_changes_winning_selection_against_exhaustive_menu():
    requirements = {'objectiveOrder': ['execution_order'],
        'orderingPreferences': {'phaseOrder': [], 'protectionOrder': ['heavy_direct']}}
    profiles = [
        {'primary': {'chest': 1}, 'supporting': {}, 'known': True, 'priority': False,
         'heavy_primary': [], 'heavy_supporting': [], 'main_compound': True,
         'main_primary': ['chest'], 'main_supporting': []},
        {'primary': {'chest': 1}, 'supporting': {}, 'known': True, 'priority': False,
         'heavy_primary': ['chest'], 'heavy_supporting': [], 'main_compound': True,
         'main_primary': ['chest'], 'main_supporting': []},
        {'primary': {'quads': 1}, 'supporting': {}, 'known': True, 'priority': False,
         'heavy_primary': ['quads'], 'heavy_supporting': [], 'main_compound': True,
         'main_primary': ['quads'], 'main_supporting': []}]

    def solve(pinned):
        variables, features, blocks = [], [], []

        def variable(upper=1, lower=0, integer=True, domain_identity=None):
            variables.append({'upper': upper, 'lower': lower, 'integer': integer,
                'domainIdentity': domain_identity, 'objectiveCost': 0})
            return len(variables) - 1

        def constraint(label, lower, upper, coefficients, intercept=0):
            features.append((label, lower, upper, intercept, coefficients))

        for index, profile in enumerate(profiles):
            option = variable(lower=int(index == 0))
            first = variable()
            definition = {'id': str(index), 'exerciseType': 'WEIGHT', 'equipmentId': 'bar'}
            item = {'definition_id': str(index), 'numWorkSets': 1, 'workSetTemplate': {'reps': 1, 'weight': 10}}
            blocks.append({'first': first, 'options': [option],
                'optionValues': {option: {'count': 1, 'setupProfiles': [setup_resource_profile(definition, item)]}},
                'recipe': {'roles': set(), 'orderPriority': 0,
                    'interferencePerRound': profile}})
        constraint(('selection',), 1, 1, {blocks[1]['options'][0]: 1, blocks[2]['options'][0]: 1})
        costs, _ = joint_planning._add_execution_sequence(blocks, requirements,
            variable, constraint, 0, 1)
        if pinned:
            constraint(('pin_opener',), 1, 1, {blocks[0]['first']: 1})
        for name, objective in [('heavy_direct', costs['ordering_heavy_direct']),
                ('tie', {blocks[2]['options'][0]: 1})]:
            current = [{**item, 'objectiveCost': objective.get(index, 0)} for index, item in enumerate(variables)]
            status, chosen = cp_solver.solve(current, features)
            assert status == 'optimal'
            value = sum(chosen[index] * cost for index, cost in objective.items())
            constraint(('objective', name), -math.inf, value, objective)
        return joint_planning._execution_order(blocks, chosen, requirements)

    def exhaustive(pinned):
        options = [order for optional in (1, 2) for order in itertools.permutations((0, optional))
            if not pinned or order[0] == 0]
        return min(options, key=lambda order: (*execution_interference_score(order, profiles, requirements), int(2 in order)))

    assert solve(False) == list(exhaustive(False)) == [1, 0]
    assert solve(True) == list(exhaustive(True)) == [0, 2]


@pytest.mark.parametrize('cap', [3, 4])
def test_cap_pruned_sequence_preserves_every_admissible_selected_order(cap):
    from workout_generator_pkg.programming_guidelines import execution_order_is_admissible
    requirements = {'objectiveOrder': ['execution_order'],
        'executionRules': [{'kind': 'order', 'before': 'source', 'after': 'receiver'}],
        'orderingPreferences': {'phaseOrder': [['HEAVY_COMPOUND'], ['MODERATE_COMPOUND'], ['ISOLATION']],
            'protectionOrder': ['heavy_direct', 'adjacent_direct']}}
    variables, features, blocks = [], [], []

    def variable(upper=1, lower=0, integer=True, domain_identity=None):
        variables.append({'upper': upper, 'lower': lower, 'integer': integer,
            'domainIdentity': domain_identity, 'objectiveCost': 0})
        return len(variables) - 1

    def constraint(label, lower, upper, coefficients, intercept=0):
        features.append((label, lower, upper, intercept, coefficients))

    for index, priority in enumerate((0, 2, 1)):
        reference = 'shared' if index < 2 else 'other'
        option, first = variable(), variable()
        definition = {'id': reference, 'exerciseType': 'WEIGHT', 'equipmentId': 'bar'}
        item = {'definition_id': reference, 'numWorkSets': 2, 'workSetTemplate': {'reps': 1, 'weight': 10}}
        blocks.append({'first': first, 'options': [option],
            'optionValues': {option: {'count': 2, 'items': [item],
                'setupProfiles': [setup_resource_profile(definition, item)]}},
            'recipe': {'definitions': {reference}, 'roles': [{'source'}, set(), {'receiver'}][index],
                'orderPriority': priority, 'interferencePerRound': {'known': True,
                    'primary': {'chest': 1}, 'supporting': {}, 'priority': False,
                    'heavy_primary': ['chest'], 'heavy_supporting': [],
                    'main_primary': [], 'main_supporting': [], 'main_compound': False}}})
    constraint(('shared_cap',), -math.inf, cap, {blocks[0]['options'][0]: 2, blocks[1]['options'][0]: 2})
    costs, evidence = joint_planning._add_execution_sequence(blocks, requirements,
        variable, constraint, 0, 1, {'shared': cap})
    variables = [{**item, 'objectiveCost': sum(cost.get(index, 0) for cost in costs.values())}
        for index, item in enumerate(variables)]
    arcs = blocks[0]['sequenceArcs']
    assert ((1, 2) not in arcs) is (cap == 3)
    assert evidence == {'anatomyComplete': True, 'setupTransitionsComplete': True,
        'resourceReferencesComplete': True}
    for size in range(1, 4):
        for order in itertools.permutations(range(3), size):
            selected = set(order)
            rows = [*features, *((('selected', index), int(index in selected), int(index in selected),
                0, {block['options'][0]: 1}) for index, block in enumerate(blocks))]
            path = [(0, order[0] + 1), *[(a + 1, b + 1) for a, b in zip(order, order[1:])],
                (order[-1] + 1, 0)]
            if any(edge not in arcs for edge in path):
                assert {0, 1} <= selected and cap == 3
                continue
            rows.extend((('path', *edge), 1, 1, 0, {arcs[edge]: 1}) for edge in path)
            status, chosen = cp_solver.solve(variables, rows)
            local_blocks = [blocks[index] for index in sorted(selected)]
            local_order = [sorted(selected).index(index) for index in order]
            expected = (2 * len(selected & {0, 1}) <= cap and execution_order_is_admissible(
                local_order, [block['recipe']['roles'] for block in local_blocks],
                [(block['recipe']['orderPriority'], ()) for block in local_blocks], requirements))
            assert (chosen is not None) is expected, (cap, order, status)
            if chosen is not None:
                profiles = [{**block['recipe']['interferencePerRound'], 'primary': {'chest': 2}}
                    for block in local_blocks]
                for name, expected_score in zip(('heavy_direct', 'adjacent_direct'),
                        execution_interference_score(local_order, profiles, requirements)):
                    assert sum(chosen[index] * cost for index, cost in costs['ordering_' + name].items()) == expected_score


def test_exact_fractional_auxiliary_and_unsupported_quantity_are_distinct_from_infeasibility():
    variables = [{'lower': 0, 'upper': 1, 'integer': True, 'objectiveCost': 0},
        {'lower': 0, 'upper': 2, 'integer': False, 'objectiveCost': 1,
         'domainIdentity': {'kind': 'duration_balance_excess'}}]
    rows = [(('fixed',), 1, 1, 0, {0: 1}), (('duration',), 0.5, math.inf, 0, {1: 1, 0: -0.5})]
    status, chosen = cp_solver.solve(variables, rows)
    assert status == 'optimal' and chosen == [1, 1]
    diagnostics = {}
    rows.append((('unsupported',), 0, 1, 0, {0: 0.1 + 0.2}))
    status, chosen = cp_solver.solve(variables, rows, diagnostics=diagnostics)
    assert status == 'unavailable' and chosen is None
    assert diagnostics['returnReason'] == 'unsupported_exact_model'


def test_production_cp_preserves_hard_frequency_bounds_and_soft_budget_count():
    from test_workout_generator_planning_tools import planning_case
    equipment, requirements, _, draft = planning_case()
    requirements.update(sessionsPerWeek=2, preferredSessionSeconds=500,
        exerciseSelection={'preferredMinimum': 2, 'preferredMaximum': 3, 'muscles': ['chest']},
        objectiveOrder=['time_budget', 'exercise_count', 'duration_economy'])
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 12, 'maximum': 12}
    requirements['auditTargets']['perSessionEffectiveSets']['chest'] = {'minimum': 6, 'maximum': 6}
    requirements['auditTargets']['maximumSessionSeconds'] = 2000
    day = copy.deepcopy(draft['workouts'][0])
    day.update(timesCompletedInAWeek=2, trainingDays=[0, 3])
    day['exercises'][0].pop('placementNotes', None)
    day['exercises'][0]['allocationBounds'] = {'minimum': 2, 'maximum': 8}
    result = joint_planning.solve_prescribed_week([day], requirements, equipment)
    assert result['feasible'], result
    assert result['solverBackend'] == 'ortools_cp_sat'
    assert result['audit']['weeklyVolume']['chest']['effective'] == 12
    assert result['sessions'][0]['exercises'][0]['numWorkSets'] == 6
    assert result['audit']['workouts'][0]['estimatedSeconds'] <= 2000
    stages = {stage['goal']: stage for stage in result['objectiveProgress']}
    assert stages['exercise_count']['value'] == 1
    context = {'setupDefinitions': {'LIBRARY_0': equipment['exerciseDefinitions'][0]}, 'fixedWorkouts': []}
    costs = joint_planning._joint_candidate_objective_costs(
        {'workouts': result['sessions'], 'audit': result['audit']}, requirements, context)
    assert stages['time_budget']['value'] == pytest.approx(costs['time_budget'])
    assert stages['exercise_count']['value'] == costs['exercise_count']


def test_native_prescription_warm_start_does_not_freeze_its_count():
    from test_workout_generator_planning_tools import planning_case
    equipment, requirements, _, draft = planning_case()
    requirements['objectiveOrder'] = ['volume_target']
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {
        'minimum': 0, 'maximum': 8, 'preferredMinimum': 6, 'preferredMaximum': 6}
    requirements['auditTargets']['perSessionEffectiveSets']['chest'] = {'minimum': 0, 'maximum': 8}
    requirements['auditTargets']['maximumSessionSeconds'] = 2000
    day = copy.deepcopy(draft['workouts'][0])
    day['exercises'][0].pop('placementNotes', None)
    day['exercises'][0]['allocationBounds'] = {'minimum': 2, 'maximum': 8}
    result = joint_planning.solve_prescribed_week([day], requirements, equipment)
    assert result['feasible'], result
    assert result['prescriptionWarmStart']['status'] == 'native_audited_recipe_decision_hint'
    assert result['prescriptionWarmStart']['selectionFixed'] is False
    assert result['sessions'][0]['exercises'][0]['numWorkSets'] == 6


def test_preferred_time_budget_includes_fixed_workouts_in_its_audited_score():
    from test_workout_generator_planning_tools import planning_case
    equipment, requirements, _, draft = planning_case()
    requirements.update(sessionsPerWeek=2, preferredSessionSeconds=500, objectiveOrder=['time_budget'])
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 6, 'maximum': 6}
    requirements['auditTargets']['perSessionEffectiveSets']['chest'] = {'minimum': 3, 'maximum': 3}
    requirements['auditTargets']['maximumSessionSeconds'] = 2000
    fixed = copy.deepcopy(draft['workouts'][0])
    fixed.update(name='Fixed', trainingDays=[0])
    fixed['exercises'][0].pop('placementNotes', None)
    fixed['exercises'][0].update(numWorkSets=3, allocationBounds={'minimum': 3, 'maximum': 3})
    variable = copy.deepcopy(fixed)
    variable.update(name='Variable', trainingDays=[3])
    result = joint_planning.solve_prescribed_week([variable], requirements, equipment,
        existing={'name': 'Existing', 'workouts': [fixed]})
    assert result['feasible'], result
    score = sum(max(0, day['estimatedSeconds'] - 500) for day in result['audit']['workouts'])
    assert result['objectiveProgress'][0]['value'] == score > 0


def test_unknown_execution_evidence_keeps_its_place_before_cheaper_duration():
    requirements = {'objectiveOrder': ['execution_order', 'duration_economy'],
        'orderingPreferences': {'protectionOrder': ['heavy_direct']}}
    ordered = joint_planning._ordered_joint_objective_names(requirements,
        {'execution_order': True, 'ordering_heavy_direct': False, 'duration_economy': True})
    assert ordered == ['ordering_heavy_direct', 'duration_economy']


def test_missing_approved_regional_count_metric_preserves_feasibility_without_claiming_optimality():
    from test_workout_generator_planning_tools import planning_case
    equipment, requirements, _, draft = planning_case()
    requirements.update(objectiveOrder=['exercise_count'], exerciseSelection={
        'preferredMinimum': 2, 'preferredMaximum': 3, 'muscles': ['pectoralis_clavicular']})
    draft['workouts'][0]['exercises'][0].pop('placementNotes', None)
    result = joint_planning.solve_prescribed_week(draft['workouts'], requirements, equipment)
    assert result['feasible'] and not result['audit']['errors'], result
    assert result['jointModelStatus'] == 'optimal'
    assert result['status'] == 'feasible'
    assert result['priorityExecution']['approvedPriorities'][0]['status'] == 'unavailable_evidence'
    assert result['exerciseCountEvidence']['pectoralis_clavicular']['count'] is None


@pytest.mark.parametrize('cap,preserve,feasible,node_count', [(3, False, True, 1),
    (20, False, True, 2), (3, True, False, 1)])
def test_physical_quotient_preserves_every_variant_source_and_cap_regime(cap, preserve, feasible, node_count):
    from test_workout_generator_planning_tools import planning_case
    from workout_generator_pkg.allocation import _audit_raw
    equipment, requirements, _, draft = planning_case()
    requirements.update(objectiveOrder=['duration_economy'], executionRules=[{
        'kind': 'workSets', 'coverageKey': None, 'minimumSets': 2, 'maximumSets': cap}])
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 2, 'maximum': 2}
    requirements['auditTargets']['perSessionEffectiveSets']['chest'] = {'minimum': 2, 'maximum': 2}
    day = copy.deepcopy(draft['workouts'][0])
    first = day['exercises'][0]
    first.pop('placementNotes', None)
    first.update(numWorkSets=2, setupSeconds=300, restBetweenSetsSeconds=30,
        allocationBounds={'minimum': 2, 'maximum': 3})
    second = copy.deepcopy(first)
    second.update(setupSeconds=0, restBetweenSetsSeconds=90)
    day['exercises'].append(second)
    result = joint_planning.solve_prescribed_week([day], requirements, equipment,
        preserve_source_selection=preserve)
    assert result['feasible'] is feasible, result
    assert result['physicalBlockCount'] == node_count
    assert result['physicalVisitQuotient']['unmergedSourceVariantCount'] == 2
    assert result['optionCount'] == 2 * (cap - 1)
    if not feasible:
        assert result['status'] == 'infeasible'
        return
    costs = []
    for variant in (first, second):
        candidate = {'name': 'Exhaustive variant', 'workouts': [{**day, 'exercises': [variant]}]}
        _, audit = _audit_raw(candidate, equipment, requirements, None, True)
        assert not audit['errors']
        costs.append(audit['workouts'][0]['estimatedSeconds'])
    assert result['audit']['workouts'][0]['estimatedSeconds'] == min(costs)
    assert result['sessions'][0]['exercises'][0]['setupSeconds'] == 0
    assert result['occurrenceLineage'] == [[[0, 1]]]
