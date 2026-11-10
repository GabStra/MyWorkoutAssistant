import pytest

from workout_generator_pkg.programming_policy import (
    relative_exposure_costs, goal_programming_costs, role_concentration_keys,
    same_weekly_training_doses, arrangement_objectives, programming_policy_errors, muscle_distribution_scope,
)
from workout_generator_pkg.muscle_roles import MUSCLE_LABELS


def exposure(counts, frequencies=None):
    frequencies = frequencies or [1] * len(counts)
    workouts = [{'timesCompletedInAWeek': value} for value in frequencies]
    audit = {'workouts': [{'coverageSets': {'horizontal_push': value},
        'volume': {**{muscle: {'effective': 0} for muscle in MUSCLE_LABELS},
            'chest': {'effective': value}}} for value in counts]}
    requirements = {'sessionsPerWeek': sum(frequencies),
        'requiredCoverage': [{'key': 'horizontal_push', 'scope': 'eachSession', 'intent': 'development'}],
        'auditTargets': {'weeklyEffectiveSets': {'chest': {'preferredMinimum': 10, 'preferredMaximum': 15}}}}
    return workouts, audit, requirements


@pytest.mark.parametrize('counts,frequencies,concentration,distribution', [
    ([0, 2, 2], [1, 1, 1], .25, .5),
    ([1, 4], [2, 1], .5, .5),
    ([2, 2, 2], [1, 1, 1], 0, 0),
    ([4], [1], 0, 0),
])
def test_relative_exposure_preserves_proportions_and_frequency(counts, frequencies,
        concentration, distribution):
    before = relative_exposure_costs(*exposure(counts, frequencies))
    after = relative_exposure_costs(*exposure([1.5 * value for value in counts], frequencies))
    assert before == after
    assert before['relative_role_concentration'] == concentration
    assert before['relative_distribution'] == pytest.approx(distribution / len(MUSCLE_LABELS))
    assert before['relative_distribution_worst'] == distribution


def test_same_dose_redistribution_improves_both_structural_measures():
    concentrated = relative_exposure_costs(*exposure([0, 3, 3]))
    distributed = relative_exposure_costs(*exposure([2, 2, 2]))
    assert distributed['relative_role_concentration'] < concentrated['relative_role_concentration']
    assert distributed['relative_distribution'] < concentrated['relative_distribution']


def test_untargeted_shoulders_participate_without_becoming_a_conserved_dose():
    import copy

    workouts, audit, requirements = exposure([2, 2, 2])
    for day, value in zip(audit['workouts'], [6, 5, 6.5]):
        day['volume']['shoulders']['effective'] = value
    changed = copy.deepcopy(audit)
    for day, value in zip(changed['workouts'], [5, 5, 7.5]):
        day['volume']['shoulders']['effective'] = value
    before = relative_exposure_costs(workouts, audit, requirements)
    after = relative_exposure_costs(workouts, changed, requirements)
    assert after['relative_distribution'] > before['relative_distribution'] > 0
    assert after['relative_distribution_worst'] > before['relative_distribution_worst'] > 0
    for value in (audit, changed):
        value.update(weeklyVolume={'chest': {'effective': 6}},
            weeklyCoverageSets={'horizontal_push': 6})
    changed['weeklyVolume']['shoulders'] = {'effective': 18}
    assert same_weekly_training_doses({'workouts': workouts, 'audit': audit},
        {'workouts': workouts, 'audit': changed}, requirements) is True


def test_explicit_regions_replace_their_parent_only_in_distribution_scope():
    _, _, requirements = exposure([2, 2, 2])
    requirements['auditTargets']['weeklyEffectiveSets'].update({
        'deltoid_lateral': {'minimum': 0}, 'deltoid_posterior': {'minimum': 0}})
    muscles = muscle_distribution_scope(requirements)
    assert set(muscles) == (set(MUSCLE_LABELS) - {'shoulders'}) | {
        'deltoid_lateral', 'deltoid_posterior'}
    assert 'chest' in muscles


@pytest.mark.parametrize('counts', [[0], [0, 0, 0]])
def test_absent_dose_is_not_adequacy_and_missing_evidence_is_not_zero(counts):
    workouts, audit, requirements = exposure(counts)
    structural = relative_exposure_costs(workouts, audit, requirements)
    assert structural['relative_distribution'] == 0
    requirements['objectiveTiers'] = [[{'metric': 'weekly_volume:chest', 'target': 0, 'scale': 10}]]
    assert goal_programming_costs(requirements, {'weekly_volume:chest': 10}, {})['goal_tier_0_worst'] == 1
    audit['workouts'][0]['volume'] = {}
    assert relative_exposure_costs(workouts, audit, requirements)['relative_distribution'] is None
    workouts, audit, requirements = exposure(counts)
    region = 'pectoralis_clavicular'
    requirements['auditTargets']['weeklyEffectiveSets'] = {region: {'preferredMinimum': 10}}
    for day in audit['workouts']:
        day['volume'] = {region: {'effective': 0}}
    audit['regionalTargetEvidence'] = {region: {'status': 'unknown_selected_aggregate_contributions'}}
    costs = relative_exposure_costs(workouts, audit, requirements)
    assert costs['relative_distribution'] is costs['relative_distribution_worst'] is None


def test_weekly_intent_does_not_create_daily_concentration_but_explicit_shared_goals_are_supported():
    from jsonschema import validate
    from workout_generator_pkg.programming_policy import OBJECTIVE_TIERS_SCHEMA

    _, _, requirements = exposure([3, 3, 4])
    role = requirements['requiredCoverage'][0]
    role['scope'] = 'weekly'
    assert not role_concentration_keys(requirements)
    role['minimumSessions'] = 2
    assert not role_concentration_keys(requirements)
    role['minimumSessions'] = 3
    assert role_concentration_keys(requirements) == ['horizontal_push']
    for metric in arrangement_objectives[:2]:
        requirements['objectiveOrder'] = [metric]
        requirements['objectiveTiers'] = [[{'metric': metric, 'target': 0, 'scale': 1}]]
        validate(requirements['objectiveTiers'], OBJECTIVE_TIERS_SCHEMA)
        assert not programming_policy_errors(requirements)


def test_arrangement_compares_same_weekly_dose_without_adding_sets_for_symmetry():
    import copy

    workouts, _, requirements = exposure([3, 3, 4])
    def candidate(counts):
        return {'workouts': copy.deepcopy(workouts), 'audit': {
            'weeklyVolume': {'chest': {'effective': sum(counts)}},
            'weeklyCoverageSets': {'horizontal_push': sum(counts)}}}
    baseline = candidate([3, 3, 4])
    assert same_weekly_training_doses(baseline, candidate([2, 4, 4]), requirements)
    assert not same_weekly_training_doses(baseline, candidate([4, 4, 4]), requirements)
    unknown = candidate([3, 3, 4])
    unknown['audit']['volumePreferenceEvidence'] = {'weekly': [{'muscle': 'chest', 'status': 'unknown'}]}
    assert same_weekly_training_doses(baseline, unknown, requirements) is None
    missing = candidate([3, 3, 4])
    missing['audit']['weeklyCoverageSets'] = {}
    assert same_weekly_training_doses(baseline, missing, requirements) is None
    different_frequency = candidate([3, 3, 4])
    different_frequency['workouts'][0]['timesCompletedInAWeek'] = 2
    assert not same_weekly_training_doses(baseline, different_frequency, requirements)


@pytest.mark.parametrize('metric', arrangement_objectives[:2])
def test_arrangement_requires_workload_to_settle_dose_first(metric):
    requirements = {'objectiveOrder': [metric]}
    error = programming_policy_errors(requirements)
    assert len(error) == 1 and error[0]['path'] == '/objectiveOrder'
    assert 'workload_economy earlier' in error[0]['message']
    requirements['objectiveOrder'] = [metric, 'workload_economy']
    assert programming_policy_errors(requirements) == error
    requirements['objectiveOrder'] = ['workload_economy', metric]
    assert not programming_policy_errors(requirements)
