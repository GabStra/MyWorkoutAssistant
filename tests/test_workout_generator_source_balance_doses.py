import copy

import pytest

from workout_generator_pkg import joint_planning
from workout_generator_pkg.cp_solver import solve
from workout_generator_pkg.programming_policy import source_balance_dose_components
from test_workout_generator_joint_candidate_comparison import _candidate, _context, _requirements


def balance_requirements():
    requirements = _requirements(['volume_target', 'source_balance'])
    requirements['auditTargets']['weeklyEffectiveSets']['CHEST'].update(
        preferredMinimum=0, preferredMaximum=10)
    requirements['executionRules'] = [{'kind': 'coverageBalance', 'scope': 'weekly',
        'first': first, 'second': second} for first, second in [('A', 'B'), ('B', 'C')]]
    return requirements


def test_connected_balance_roles_redistribute_without_shrinking_or_inflating_combined_dose():
    requirements = balance_requirements()
    assert source_balance_dose_components(requirements) == [{'scope': 'weekly', 'roles': ['A', 'B', 'C']}]
    allocations = [(8, 2, 2), (4, 4, 4), (2, 2, 2), (8, 8, 8)]
    options = [(index, 0, None, {'coverage': dict(zip(('A', 'B', 'C'), allocation))})
        for index, allocation in enumerate(allocations)]
    features = [(('choose_one',), 1, 1, 0, {index: 1 for index in range(4)})]
    evidence = joint_planning._lock_source_balance_doses(features, [1, 0, 0, 0], options,
        [{'timesCompletedInAWeek': 1}], requirements, {})
    assert evidence[0]['combinedWorkingSetExposure'] == [12]
    assert len(features) == 2  # One component lock, not a lock for every pair or individual role.
    variables = [{'lower': 0, 'upper': 1, 'integer': True,
        'objectiveCost': abs(a - b) + abs(b - c)} for a, b, c in allocations]
    status, chosen = solve(variables, features, timeout_seconds=5)
    assert status == 'optimal' and chosen == [0, 1, 0, 0]


def test_fixed_workload_balance_can_replace_isolation_work_with_compounds():
    requirements = balance_requirements()
    requirements['objectiveOrder'] = ['volume_target', 'workload_economy', 'source_balance', 'execution_order']
    # Same physical workload; the better balance requires more compound-role exposure.
    allocations = [(6, 5, 2), (6, 4, 4), (2, 2, 2)]
    options = [(index, 0, None, {'coverage': dict(zip(('A', 'B', 'C'), values))})
        for index, values in enumerate(allocations)]
    features = [(('choose_one',), 1, 1, 0, {index: 1 for index in range(3)}),
        (('physical_workload',), 57, 57, 0, {index: 57 for index in range(3)})]
    joint_planning._lock_source_balance_doses(features, [1, 0, 0], options,
        [{'timesCompletedInAWeek': 1}], requirements, {})
    variables = [{'lower': 0, 'upper': 1, 'integer': True,
        'objectiveCost': abs(a - b) + abs(b - c)} for a, b, c in allocations]
    status, chosen = solve(variables, features, timeout_seconds=5)
    assert status == 'optimal' and chosen == [0, 1, 0]
    baseline, candidate = _candidate([4, 4]), _candidate([4, 4])
    for plan, values in ((baseline, allocations[0]), (candidate, allocations[1])):
        plan['audit']['targets'] = copy.deepcopy(requirements['auditTargets'])
        plan['audit']['weeklyCoverageSets'] = dict(zip(('A', 'B', 'C'), values))
    compared = joint_planning.compare_audited_joint_candidates(
        baseline, candidate, requirements=requirements, context=_context())
    assert compared['decision'] == 'promote_candidate', compared
    candidate['audit']['weeklyCoverageSets'] = dict(zip(('A', 'B', 'C'), allocations[2]))
    compared = joint_planning.compare_audited_joint_candidates(
        baseline, candidate, requirements=requirements, context=_context())
    assert compared['decision'] == 'incomparable'
    assert compared['reason'] == 'combined_role_doses_differ_at_source_balance'


def test_component_lock_respects_session_scope_and_weekly_frequency():
    requirements = balance_requirements()
    requirements['executionRules'].append({'kind': 'coverageBalance', 'scope': 'eachSession',
        'first': 'A', 'second': 'D'})
    options = [(0, 0, None, {'coverage': {'A': 3, 'B': 1, 'C': 2, 'D': 4}}),
        (1, 1, None, {'coverage': {'A': 1, 'B': 2, 'C': 1, 'D': 2}})]
    rows = []
    evidence = joint_planning._lock_source_balance_doses(rows, [1, 1], options,
        [{'timesCompletedInAWeek': 2}, {'timesCompletedInAWeek': 1}], requirements,
        {'weeklyCoverageSets': {'A': 3}})
    assert evidence == [
        {'scope': 'weekly', 'roles': ['A', 'B', 'C'], 'combinedWorkingSetExposure': [19]},
        {'scope': 'eachSession', 'roles': ['A', 'D'], 'combinedWorkingSetExposure': [7, 3]},
    ]
    requirements['objectiveOrder'] = ['source_balance', 'volume_target']
    assert source_balance_dose_components(requirements) == []


def test_production_solver_records_component_conservation_after_volume_selection():
    from test_workout_generator_joint_prescriptions import two_recipe_order_case

    equipment, requirements, sessions = two_recipe_order_case()
    requirements['objectiveOrder'] = ['volume_target', 'source_balance']
    requirements['auditTargets']['weeklyEffectiveSets']['chest'].update(
        preferredMinimum=10, preferredMaximum=12)
    requirements['executionRules'] = [{'kind': 'coverageBalance', 'scope': 'weekly',
        'first': 'first', 'second': 'second'}]
    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment)
    assert result['feasible'], result
    stage = next(stage for stage in result['objectiveProgress'] if stage['goal'] == 'source_balance')
    coverage = result['audit']['weeklyCoverageSets']
    assert stage['combinedRoleDoseConservation'] == [{'scope': 'weekly',
        'roles': ['first', 'second'],
        'combinedWorkingSetExposure': [coverage['first'] + coverage['second']]}]


@pytest.mark.parametrize('after, decision', [((4, 4, 4), 'promote_candidate'),
    ((2, 2, 2), 'incomparable'), ((8, 8, 8), 'incomparable')])
def test_candidate_balance_comparison_uses_the_same_connected_dose_face(after, decision):
    requirements = balance_requirements()
    baseline, candidate = _candidate([4, 4]), _candidate([4, 4])
    for plan, totals in ((baseline, (8, 2, 2)), (candidate, after)):
        plan['audit']['targets'] = copy.deepcopy(requirements['auditTargets'])
        plan['audit']['weeklyCoverageSets'] = dict(zip(('A', 'B', 'C'), totals))
    result = joint_planning.compare_audited_joint_candidates(
        baseline, candidate, requirements=requirements, context=_context())
    assert result['decision'] == decision
    assert result['firstDifferingObjective'] == 'source_balance'
    if decision == 'incomparable':
        assert result['reason'] == 'combined_role_doses_differ_at_source_balance'


def test_execution_order_scoring_materializes_blocks_before_reusing_them():
    requirements = _requirements(['execution_order'])
    requirements['orderingPreferences'] = {'protectionOrder': ['adjacent_direct']}
    context = _context()
    context['setupDefinitions'] = {'LIBRARY_1': {'id': 'press', 'exerciseType': 'WEIGHT',
        'muscleGroups': ['FRONT_CHEST'], 'secondaryMuscleGroups': []}}
    candidate = _candidate([2])
    candidate['workouts'][0]['exercises'][0]['superset'] = None
    candidate['workouts'][0]['exercises'].append(copy.deepcopy(candidate['workouts'][0]['exercises'][0]))
    costs = joint_planning._joint_candidate_objective_costs(candidate, requirements, context)
    assert costs['ordering_adjacent_direct'] == 2


def test_solver_preserves_source_authority_and_uses_resolved_execution_in_every_audit(monkeypatch):
    from workout_generator_pkg import planning_decisions
    from test_workout_generator_joint_prescriptions import two_recipe_order_case

    equipment, requirements, sessions = two_recipe_order_case()
    sessions[0]['exercises'][0]['satisfiesCoverage'].append('rotational_core')
    requirements['requiredCoverage'].append({'key': 'rotational_core', 'scope': 'weekly',
        'description': 'Dedicated rotation'})
    original_equipment, original_requirements = copy.deepcopy(equipment), copy.deepcopy(requirements)
    unresolved = joint_planning.solve_prescribed_week(sessions, requirements, equipment)
    assert unresolved['status'] == 'execution_semantics_unresolved'
    assert unresolved['userQuestion']['executionChoices'][0]['definition_id'] == 'LIBRARY_0'
    definition = copy.deepcopy(equipment['exerciseDefinitions'][0])
    definition['reviewedExecution'] = {'setMode': 'single_sequence'}
    monkeypatch.setattr(planning_decisions, 'execution_decision_definitions',
        lambda messages, equipment: {definition['id']: definition})
    audit_raw, forwarded = joint_planning._audit_raw, []

    def audit(*args, **kwargs):
        forwarded.append(kwargs['execution_definitions'])
        return audit_raw(*args, **kwargs)

    monkeypatch.setattr(joint_planning, '_audit_raw', audit)
    result = joint_planning.solve_prescribed_week(sessions, requirements, equipment)
    assert result['feasible'], result
    assert forwarded and all(row == {definition['id']: definition} for row in forwarded)
    assert result['executionPrescriptions'] == {definition['id']: 'single_sequence'}
    assert equipment == original_equipment and requirements == original_requirements
    assert result['objectiveInputFingerprint'] == joint_planning.joint_objective_input_fingerprint(
        result['sessions'], original_requirements, original_equipment)


def test_resolved_context_changes_existing_solver_input_fingerprints(monkeypatch):
    from workout_generator_pkg import planning_decisions
    from test_workout_generator_joint_prescriptions import two_recipe_order_case

    equipment, requirements, sessions = two_recipe_order_case()
    functions = (joint_planning.joint_problem_fingerprint, joint_planning.joint_objective_input_fingerprint)
    before = [function(sessions, requirements, equipment) for function in functions]
    monkeypatch.setattr(planning_decisions, 'resolved_decisions', lambda messages: {'DECISION_0': {
        'topic': 'Counting basis', 'choice': 'One sequence', 'sourceReferences': ['SOURCE_0'],
        'executionPrescription': {'definitionId': 'press', 'setMode': 'single_sequence'}}})
    after = [function(sessions, requirements, equipment) for function in functions]
    assert all(first != second for first, second in zip(before, after))
