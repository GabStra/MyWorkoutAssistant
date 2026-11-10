import copy

import pytest

from test_workout_generator_joint_candidate_comparison import _context
from test_workout_generator_joint_prescriptions import two_recipe_order_case
from workout_generator_pkg import joint_planning as joint
from workout_generator_pkg.programming_policy import programming_policy_errors


def dose_boundary_case():
    equipment, requirements, sessions = two_recipe_order_case()
    sessions.append(copy.deepcopy(sessions[0]))
    sessions[1].update(name='Day 2', trainingDays=[2])
    for day in sessions:
        for exercise in day['exercises']:
            exercise['numWorkSets'] = 2
    requirements.update(
        sessionsPerWeek=2,
        objectiveOrder=['goal_tier_0', 'workload_economy', 'source_balance',
            'goal_tier_1', 'session_set_balance'],
        objectiveTiers=[
            [{'metric': 'weekly_volume:chest', 'target': 0, 'scale': 9}],
            [{'metric': 'session_set_balance', 'target': 0, 'scale': 1}]],
        goalAggregation='total_then_worst',
        preferenceResolution='explicit_tradeoffs',
        executionRules=[
            {'kind': 'workSets', 'coverageKey': None, 'minimumSets': 2, 'maximumSets': 3},
            {'kind': 'coverageBalance', 'first': 'first', 'second': 'second',
                'scope': 'weekly', 'relationship': 'balanced'}])
    requirements['auditTargets'] = {'weeklyEffectiveSets': {'chest': {
        'minimum': 0, 'maximum': None, 'preferredMinimum': 9, 'preferredMaximum': 12}},
        'perSessionEffectiveSets': {}}
    return equipment, requirements, sessions


def test_source_equality_cannot_buy_work_after_the_dose_boundary(monkeypatch):
    monkeypatch.setenv('MYWORKOUT_SOLVER_SEARCH_SECONDS', '15')
    equipment, requirements, sessions = dose_boundary_case()
    assert not programming_policy_errors(requirements)
    selected = joint.solve_prescribed_week(sessions, requirements, equipment)
    assert selected['feasible'] and not selected['audit']['errors'], selected
    assert selected['audit']['weeklyWorkingSets'] == 9
    role_sets = selected['audit']['weeklyCoverageSets']
    assert abs(role_sets['first'] - role_sets['second']) == 1

    balance_first = copy.deepcopy(requirements)
    balance_first['objectiveOrder'] = ['goal_tier_0', 'source_balance',
        'workload_economy', 'goal_tier_1', 'session_set_balance']
    inflated = joint.solve_prescribed_week(sessions, balance_first, equipment)
    assert inflated['feasible'] and not inflated['audit']['errors'], inflated
    assert inflated['audit']['weeklyWorkingSets'] == 10
    role_sets = inflated['audit']['weeklyCoverageSets']
    assert role_sets['first'] == role_sets['second'] == 5

    context = _context()
    context['qualifiedRoleEvidence'] = {'LIBRARY_0': ['first'], 'LIBRARY_1': ['second']}
    compared = joint.compare_audited_joint_candidates(
        {'workouts': inflated['sessions'], 'audit': inflated['audit']},
        {'workouts': selected['sessions'], 'audit': selected['audit']},
        requirements=requirements, context=context)
    assert compared['decision'] == 'promote_candidate', compared
    assert any(row['objective'] == 'source_balance'
        for row in compared['programmingTradeoff']['worsened'])
    assert any(row['objective'] == 'workload_economy'
        for row in compared['programmingTradeoff']['improved'])


@pytest.mark.parametrize('hard_maximum, expected_sets, aspiration_shortfall', [
    (None, 10, 0), (9, 9, 1)])
def test_explicit_dose_aspiration_precedes_workload_and_respects_hard_bounds(
        monkeypatch, hard_maximum, expected_sets, aspiration_shortfall):
    monkeypatch.setenv('MYWORKOUT_SOLVER_SEARCH_SECONDS', '15')
    equipment, requirements, sessions = dose_boundary_case()
    requirements['objectiveTiers'][0].append({
        'metric': 'weekly_effective_sets:chest', 'target': -10, 'scale': 1})
    if hard_maximum is not None:
        bounds = requirements['auditTargets']['weeklyEffectiveSets']['chest']
        bounds.update(maximum=hard_maximum, preferredMaximum=hard_maximum)
    assert not programming_policy_errors(requirements)
    selected = joint.solve_prescribed_week(sessions, requirements, equipment)
    assert selected['feasible'] and not selected['audit']['errors'], selected
    assert selected['audit']['weeklyWorkingSets'] == expected_sets
    assert selected['audit']['weeklyVolume']['chest']['effective'] == expected_sets
    stages = {stage['goal']: stage for stage in selected['objectiveProgress']}
    assert stages['goal_tier_0_total']['value'] == aspiration_shortfall
    assert stages['goal_tier_1_total']['weeklyDosesLocked'] is True


@pytest.mark.parametrize('intent, authority, first_conserved', [
    ('inclusion', None, False),
    ('development', None, True),
    (None, None, True),
    ('inclusion', 'goal', True),
    ('inclusion', 'balance', True),
])
def test_arrangement_conserves_approved_dose_roles_in_comparison_and_native_locks(
        monkeypatch, intent, authority, first_conserved):
    from workout_generator_pkg.programming_policy import (
        conserved_coverage_roles, same_weekly_training_doses,
    )

    monkeypatch.setenv('MYWORKOUT_SOLVER_SEARCH_SECONDS', '15')
    equipment, requirements, sessions = dose_boundary_case()
    first, second = requirements['requiredCoverage']
    if intent is not None:
        first['intent'] = intent
    second['intent'] = 'development'
    if authority != 'balance':
        requirements['executionRules'] = [rule for rule in requirements['executionRules']
            if rule['kind'] != 'coverageBalance']
    if authority == 'goal':
        requirements['objectiveTiers'][0].append({
            'metric': 'coverage:first', 'target': -4, 'scale': 1})
    expected_roles = {'first', 'second'} if first_conserved else {'second'}
    assert set(conserved_coverage_roles(requirements)) == expected_roles

    locked_roles = []
    lock_doses = joint._lock_weekly_training_doses

    def capture_lock(features, chosen, options, workouts, roles, muscles):
        start = len(features)
        lock_doses(features, chosen, options, workouts, roles, muscles)
        locked_roles.append({row[0][2] for row in features[start:]
            if row[0][:2] == ('training_dose_conservation', 'coverage')})

    monkeypatch.setattr(joint, '_lock_weekly_training_doses', capture_lock)
    selected = joint.solve_prescribed_week(sessions, requirements, equipment)
    assert selected['feasible'] and not selected['audit']['errors'], selected
    assert locked_roles and all(roles == expected_roles for roles in locked_roles)

    baseline = {'workouts': selected['sessions'], 'audit': selected['audit']}
    candidate = copy.deepcopy(baseline)
    candidate['audit']['weeklyCoverageSets']['first'] += 1
    assert same_weekly_training_doses(baseline, candidate, requirements) == (not first_conserved)
    candidate = copy.deepcopy(baseline)
    candidate['audit']['weeklyCoverageSets']['second'] += 1
    assert same_weekly_training_doses(baseline, candidate, requirements) is False
