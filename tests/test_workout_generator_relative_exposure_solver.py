import pytest

from workout_generator_pkg import joint_planning as joint
from workout_generator_pkg.programming_policy import relative_exposure_costs
from workout_generator_pkg.muscle_roles import MUSCLE_LABELS
from test_workout_generator_joint_prescriptions import _distribution_solver_case, prescription_case


def _relative_policy(requirements, sessions, existing=None):
    requirements['objectiveOrder'] = ['workload_economy', 'relative_role_concentration', 'relative_distribution']
    requirements['requiredCoverage'] = [{'key': 'chest', 'scope': 'eachSession',
        'intent': 'development', 'description': 'Chest working-set exposure'}]
    for day in [*(existing or {}).get('workouts', []), *sessions]:
        for item in day['exercises']:
            item['satisfiesCoverage'] = ['chest']


@pytest.mark.parametrize('counts', [[1, 3], [2, 6]])
@pytest.mark.parametrize('has_volume_targets', [False, True])
def test_joint_relative_metrics_match_audit_and_ignore_proportional_dose(counts, has_volume_targets):
    equipment, requirements, sessions, _ = _distribution_solver_case(counts)
    _relative_policy(requirements, sessions)
    if not has_volume_targets:
        requirements['auditTargets']['weeklyEffectiveSets'] = {}
        requirements['auditTargets']['perSessionEffectiveSets'] = {}
    solved = joint.solve_prescribed_week(sessions, requirements, equipment, preserve_source_selection=True)
    assert solved['feasible'], solved
    native = joint._joint_candidate_objective_costs(
        {'workouts': solved['sessions'], 'audit': solved['audit']}, requirements, {})
    for name in ('relative_role_concentration', 'relative_distribution'):
        stage = next(stage for stage in solved['objectiveProgress'] if stage['goal'] == name)
        assert stage['status'] in ('optimal', 'optimal_zero_lower_bound')
        expected = .5 if name == 'relative_role_concentration' else 2 * .5 / len(MUSCLE_LABELS)
        assert stage['value'] == pytest.approx(native[name]) == pytest.approx(expected)
    assert [day['exercises'][0]['numWorkSets'] for day in solved['sessions']] == counts
    assert solved['priorityExecution']['relativeExposure']['muscles'] == sorted(MUSCLE_LABELS)


def test_relative_metrics_include_repeated_fixed_workouts_and_half_set_credits():
    equipment, requirements, sessions, existing = _distribution_solver_case([1, 3], existing_counts=[2])
    existing['workouts'][0].update(timesCompletedInAWeek=2, trainingDays=[4, 6])
    requirements['sessionsPerWeek'] = 4
    # Substantial assistance contributes half an effective set per working set.
    equipment['exerciseDefinitions'][0]['muscleGroups'] = ['BACK_TRICEPS']
    equipment['exerciseDefinitions'][0]['secondaryMuscleGroups'] = ['FRONT_CHEST']
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 4, 'maximum': 4}
    requirements['auditTargets']['perSessionEffectiveSets']['chest'] = {'minimum': .5, 'maximum': 1.5}
    _relative_policy(requirements, sessions, existing)
    # Keep a source-backed development role distinct from direct muscle credit.
    requirements['requiredCoverage'][0]['key'] = 'press'
    for day in [*existing['workouts'], *sessions]:
        for item in day['exercises']:
            item['satisfiesCoverage'] = ['press']
    solved = joint.solve_prescribed_week(sessions, requirements, equipment, existing=existing)
    assert solved['feasible'], solved
    native = relative_exposure_costs([*existing['workouts'], *solved['sessions']], solved['audit'], requirements)
    for name in ('relative_role_concentration', 'relative_distribution'):
        stage = next(stage for stage in solved['objectiveProgress'] if stage['goal'] == name)
        expected = .167 if name == 'relative_role_concentration' else 2 * .167 / len(MUSCLE_LABELS)
        assert stage['value'] == pytest.approx(native[name]) == pytest.approx(expected)


def test_targeted_region_replaces_its_aggregate_in_solver_and_audited_distribution(monkeypatch):
    from workout_generator_pkg import recipe_contracts

    equipment, requirements, sessions, _ = _distribution_solver_case([1, 3])
    _relative_policy(requirements, sessions)
    region = 'pectoralis_clavicular'
    anatomy = {
        'primarySubregions': [region], 'secondarySubregions': [],
        'source': 'https://example.com/anatomy', 'basis': 'Controlled regional-credit fixture.'}
    definition = equipment['exerciseDefinitions'][0]
    definition['anatomy'] = anatomy
    monkeypatch.setattr(recipe_contracts, '_reviewed_exercise_annotations_by_definition',
        lambda: {definition['id']: {'anatomy': anatomy}})
    requirements['auditTargets']['weeklyEffectiveSets'][region] = {'minimum': 4, 'maximum': 4}
    solved = joint.solve_prescribed_week(sessions, requirements, equipment, preserve_source_selection=True)
    assert solved['feasible'], solved
    exposure = solved['priorityExecution']['relativeExposure']
    assert set(exposure['muscles']) == (set(MUSCLE_LABELS) - {'chest'}) | {region}
    stage = next(stage for stage in solved['objectiveProgress'] if stage['goal'] == 'relative_distribution')
    assert stage['value'] == pytest.approx(exposure['costs']['relative_distribution'])
    assert stage['value'] == pytest.approx(2 * .5 / len(MUSCLE_LABELS))


@pytest.mark.parametrize('balance_first', [False, True])
def test_arrangement_locks_chosen_dose_after_target_and_workload_selection(balance_first, monkeypatch):
    locked_muscles = []
    lock_doses = joint._lock_weekly_training_doses

    def capture_lock(features, chosen, options, workouts, roles, muscles):
        locked_muscles.append(set(muscles))
        return lock_doses(features, chosen, options, workouts, roles, muscles)

    monkeypatch.setattr(joint, '_lock_weekly_training_doses', capture_lock)
    equipment, requirements, sessions = prescription_case()
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 0, 'maximum': 9,
        'preferredMinimum': 7, 'preferredMaximum': 9}
    requirements['auditTargets']['perSessionEffectiveSets']['chest'] = {'minimum': 0, 'maximum': 3}
    _relative_policy(requirements, sessions)
    requirements['objectiveOrder'] = ['volume_target', *requirements['objectiveOrder']]
    if balance_first:
        requirements['objectiveOrder'].insert(2, 'session_set_balance')
    requirements['objectiveTiers'] = [[
        {'metric': 'weekly_volume:chest', 'target': 0, 'scale': 7},
    ]]
    requirements['executionRules'] = [{'kind': 'workSets', 'coverageKey': None,
        'minimumSets': 1, 'maximumSets': 3}]
    for day in sessions:
        day['exercises'][0]['numWorkSets'] = 1
    solved = joint.solve_prescribed_week(sessions, requirements, equipment)
    assert solved['feasible'], solved
    assert solved['audit']['weeklyWorkingSets'] == 7
    assert sorted(day['exercises'][0]['numWorkSets'] for day in solved['sessions']) == [2, 2, 3]
    arrangement = [stage for stage in solved['objectiveProgress'] if stage['goal'] in ('relative_role_concentration', 'relative_distribution')]
    assert arrangement and all(stage['weeklyDosesLocked'] for stage in arrangement)
    assert locked_muscles and all(muscles == {'chest'} for muscles in locked_muscles)
    if balance_first:
        balance = next(stage for stage in solved['objectiveProgress'] if stage['goal'] == 'session_set_balance')
        assert balance['weeklyDosesLocked'] and balance['value'] > 0
    native = joint._joint_candidate_objective_costs(
        {'workouts': solved['sessions'], 'audit': solved['audit']}, requirements, {})
    for stage in solved['objectiveProgress']:
        if stage['goal'].startswith('goal_tier_'):
            assert stage['value'] == pytest.approx(native[stage['goal']]) == 0


def test_unknown_regional_exposure_does_not_become_a_zero_distribution_cost():
    equipment, requirements, sessions = prescription_case()
    requirements['auditTargets']['weeklyEffectiveSets'] = {
        'pectoralis_clavicular': {'minimum': 0, 'maximum': None,
            'preferredMinimum': 1, 'preferredMaximum': 10}}
    requirements['auditTargets']['perSessionEffectiveSets'] = {}
    requirements['objectiveOrder'] = ['workload_economy', 'relative_distribution', 'session_set_balance']
    solved = joint.solve_prescribed_week(sessions, requirements, equipment, preserve_source_selection=True)
    assert solved['feasible'], solved
    priority = next(row for row in solved['priorityExecution']['approvedPriorities']
        if row['priority'] == 'relative_distribution')
    assert priority['status'] == 'unavailable_evidence'
    assert solved['priorityExecution']['relativeExposure']['costs']['relative_distribution'] is None


def test_unknown_relative_priority_blocks_promotion_from_a_later_duration_improvement():
    from test_workout_generator_joint_candidate_comparison import _candidate, _context, _requirements

    requirements = _requirements(['relative_distribution', 'duration_economy'])
    baseline = _candidate([2, 2], durations=[500, 500])
    candidate = _candidate([2, 2], durations=[300, 300])
    for value in (baseline, candidate):
        value['audit']['regionalTargetEvidence'] = {
            'CHEST': {'status': 'unknown_selected_aggregate_contributions'}}
    compared = joint.compare_audited_joint_candidates(
        baseline, candidate, requirements=requirements, context=_context())
    assert compared['decision'] == 'incomparable'
    assert compared['reason'] == 'objective_evidence_unavailable:relative_distribution'
    assert compared['arrangementComparison']['status'] == 'unknown_weekly_doses'


@pytest.mark.parametrize('explicit_tradeoffs', [False, True])
def test_candidate_comparison_does_not_buy_symmetry_with_extra_weekly_work(explicit_tradeoffs):
    from test_workout_generator_joint_candidate_comparison import _candidate, _context, _requirements

    requirements = _requirements(['relative_distribution', 'workload_economy'])
    if explicit_tradeoffs:
        requirements['preferenceResolution'] = 'explicit_tradeoffs'
    before, after = _candidate([2, 3, 3]), _candidate([3, 3, 3])
    compared = joint.compare_audited_joint_candidates(
        before, after, requirements=requirements, context=_context())
    assert compared['decision'] == 'retain_baseline', compared
    assert compared['arrangementComparison']['status'] == 'inapplicable_different_weekly_doses'
    assert not any(row['objective'] == 'relative_distribution' for row in compared['comparisons'])
    assert compared['objectiveCosts']['candidate']['relative_distribution'] == 0


def test_quality_tier_search_keeps_a_bounded_budget_when_many_polish_ties_remain(monkeypatch):
    from test_workout_generator_joint_prescriptions import two_recipe_order_case

    equipment, requirements, sessions = two_recipe_order_case()
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 0, 'maximum': 12,
        'preferredMinimum': 6, 'preferredMaximum': 12}
    requirements['auditTargets']['perSessionEffectiveSets'] = {}
    requirements['objectiveOrder'] = ['volume_target', 'workload_economy']
    requirements['objectiveTiers'] = [[
        {'metric': 'weekly_volume:chest', 'target': 0, 'scale': 6},
        {'metric': 'workload_economy', 'target': 0, 'scale': 6},
    ]]
    requirements['executionRules'] = [{'kind': 'workSets', 'coverageKey': None,
        'minimumSets': 2, 'maximumSets': 3}]
    for item in sessions[0]['exercises']:
        item['numWorkSets'] = 2
    original_goals, original_solve = joint._goal_programming_objectives, joint._cp_solve
    budgets = {}

    def quality_then_polishing(*args, **kwargs):
        return original_goals(*args, **kwargs) + [(f'polish_{index}', {0: 1}) for index in range(20)]

    def record_search(*args, **kwargs):
        name = kwargs.get('diagnostics', {}).get('goal')
        budgets[name] = kwargs['timeout_seconds']
        if name and name.startswith('polish_'):
            return 'unproven', None
        return original_solve(*args, **kwargs)

    monkeypatch.setattr(joint, '_goal_programming_objectives', quality_then_polishing)
    monkeypatch.setattr(joint, '_cp_solve', record_search)
    monkeypatch.setenv('MYWORKOUT_SOLVER_SEARCH_SECONDS', '120')
    solved = joint.solve_prescribed_week(sessions, requirements, equipment)
    assert solved['feasible'], solved
    assert 20 < budgets['goal_tier_0_total'] <= joint._SOLVER_STAGE_SECONDS
    assert 0 < budgets['goal_tier_0_worst'] <= 120 / 3
    assert all(0 < value <= joint._SOLVER_STAGE_SECONDS for value in budgets.values())
