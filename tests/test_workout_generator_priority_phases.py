import pytest

from workout_generator_pkg.programming_policy import (
    assess_audited_programming_tradeoff, expand_goal_tiers, programming_policy_errors,
    settled_dose_goal_stages, marked_arrangement_comparable,
)


def phased_policy():
    return {'objectiveOrder': ['exercise_count', 'workload_economy', 'goal_tier_1',
        'session_exercise_balance', 'session_set_balance', 'setup_economy'],
        'objectiveTiers': [[{'metric': 'exercise_count', 'target': 0, 'scale': 1}], [
            {'metric': 'session_exercise_balance', 'target': 0, 'scale': 300},
            {'metric': 'session_set_balance', 'target': 0, 'scale': 1},
            {'metric': 'setup_economy', 'target': 0, 'scale': 40}]]}


def test_unmarked_tiers_keep_legacy_prepend_and_explicit_tiers_follow_workload():
    requirements = phased_policy()
    expected = ['goal_tier_0_worst', 'goal_tier_0_total', 'workload_economy',
        'goal_tier_1_worst', 'goal_tier_1_total']
    assert expand_goal_tiers(requirements, requirements['objectiveOrder']) == expected
    assert expand_goal_tiers(requirements, expected) == expected
    assert settled_dose_goal_stages(requirements) == set(expected[-2:])
    assert not programming_policy_errors(requirements)
    requirements['objectiveOrder'].remove('goal_tier_1')
    assert expand_goal_tiers(requirements, requirements['objectiveOrder']) == [
        *expected[:2], *expected[-2:], 'workload_economy']
    assert not settled_dose_goal_stages(requirements)
    assert not programming_policy_errors(requirements)
    assert expand_goal_tiers({}, ['setup_economy']) == ['setup_economy']


def test_explicit_tier_order_keeps_approved_aggregation_and_native_tiebreaks():
    requirements = phased_policy()
    requirements['goalAggregation'] = 'total_then_worst'
    assert expand_goal_tiers(requirements, [*requirements['objectiveOrder'],
        'setup_economy_transitions']) == ['goal_tier_0_total', 'goal_tier_0_worst',
            'workload_economy', 'goal_tier_1_total', 'goal_tier_1_worst',
            'setup_economy_transitions']


@pytest.mark.parametrize('markers', [
    ['goal_tier_2'], ['goal_tier_8'], ['goal_tier_invalid'], ['goal_tier_1', 'goal_tier_1'],
])
def test_invalid_tier_markers_are_rejected(markers):
    requirements = phased_policy()
    requirements['objectiveOrder'] = [name for name in requirements['objectiveOrder']
        if name != 'goal_tier_1'] + markers
    assert any(error['path'] == '/objectiveOrder' for error in programming_policy_errors(requirements))


@pytest.mark.parametrize('metric', ['session_exercise_balance', 'session_set_balance',
    'session_heavy_exercise_balance', 'session_heavy_set_balance'])
def test_marked_session_balance_can_participate_before_workload_or_preserve_it_afterward(metric):
    requirements = {'objectiveOrder': ['goal_tier_0', 'workload_economy', metric],
        'objectiveTiers': [[{'metric': metric, 'target': 0, 'scale': 1}]]}
    assert not programming_policy_errors(requirements)
    assert not settled_dose_goal_stages(requirements)
    requirements['objectiveOrder'].remove('workload_economy')
    assert not programming_policy_errors(requirements)
    requirements['objectiveOrder'].insert(0, 'workload_economy')
    assert not programming_policy_errors(requirements)
    assert settled_dose_goal_stages(requirements)


@pytest.mark.parametrize('metric', ['volume_target', 'source_balance', 'workload_economy',
    'coverage:push', 'weekly_volume:chest', 'weekly_effective_sets:chest'])
def test_post_workload_tiers_cannot_select_weekly_doses(metric):
    requirements = {'objectiveOrder': ['workload_economy', 'goal_tier_0', 'volume_target', 'source_balance'],
        'requiredCoverage': [{'key': 'push'}],
        'auditTargets': {'weeklyEffectiveSets': {'chest': {'preferredMinimum': 1}}},
        'objectiveTiers': [[{'metric': metric, 'target': 0, 'scale': 1}]]}
    assert any('dose-selection' in error['message'] for error in programming_policy_errors(requirements))


def test_post_workload_tiers_require_a_standalone_workload_boundary():
    requirements = phased_policy()
    requirements['objectiveTiers'][0].append({'metric': 'workload_economy', 'target': 0, 'scale': 1})
    assert any('standalone workload_economy' in error['message']
        for error in programming_policy_errors(requirements))


def test_comparison_settles_workload_before_joint_arrangement_and_requires_matching_doses():
    requirements = phased_policy()
    requirements['requiredCoverage'] = [{'key': 'push'}]

    def plan(dose):
        return {'workouts': [{'timesCompletedInAWeek': 1,
            'exercises': [{'definition_id': 'PUSH', 'numWorkSets': 4}]}],
            'audit': {'errors': [], 'weeklyCoverageSets': {'push': dose}, 'weeklyWorkingSets': 4}}

    before = {'exercise_count': 0, 'workload_economy': 4, 'session_exercise_balance': 300,
        'session_set_balance': 1, 'setup_economy': 40, 'goal_tier_0_worst': 0,
        'goal_tier_0_total': 0, 'goal_tier_1_worst': 1, 'goal_tier_1_total': 3,
        'setup_economy_transitions': 0, 'setup_economy_resource_switches': 0}
    after = {**before, 'workload_economy': 5, 'goal_tier_1_worst': 0, 'goal_tier_1_total': 0}

    def assess(candidate, dose):
        return assess_audited_programming_tradeoff(plan(4), plan(dose), requirements=requirements,
            baseline_costs=before, candidate_costs=candidate,
            objective_names=requirements['objectiveOrder'], same_selected_work=False)

    assert assess(after, 5)['status'] == 'baseline_preferred'
    after['workload_economy'] = 4
    assert assess(after, 4)['status'] == 'candidate_preferred'
    different = assess(after, 5)
    assert different['status'] == 'equivalent'
    assert {row['objective'] for row in different['inapplicableObjectives']} == settled_dose_goal_stages(requirements)
    assert assess(after, None)['status'] == 'unknown'
    baseline, candidate = plan(4), plan(4)
    assert marked_arrangement_comparable(baseline, candidate, requirements)
    candidate['audit']['weeklyWorkingSets'] = 5
    assert marked_arrangement_comparable(baseline, candidate, requirements) is False
    candidate = plan(4)
    candidate['workouts'][0]['exercises'][0]['definition_id'] = 'OTHER_PUSH'
    assert marked_arrangement_comparable(baseline, candidate, requirements) is False
    candidate = plan(4)
    candidate['audit'].pop('weeklyWorkingSets')
    assert marked_arrangement_comparable(baseline, candidate, requirements) is None
