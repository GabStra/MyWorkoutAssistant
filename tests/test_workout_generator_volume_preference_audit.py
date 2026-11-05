import copy
import json
import math

import pytest

from workout_generator_pkg import generation_audit as audit
from workout_generator_pkg.plan_contract import ContractValidationError


def _bounds(**overrides):
    return {'minimum': 0, 'maximum': None, 'preferredMinimum': 10,
        'preferredMaximum': 15, **overrides}


def _package(count, frequency=1):
    return {'workouts': [{'name': 'Day', 'timesCompletedInAWeek': frequency,
        'workoutComponents': [{'id': 'press', 'libraryDefinitionId': 'definition-press',
            'type': 'Exercise', 'name': 'Press', 'exerciseType': 'WEIGHT',
            'muscleGroups': ['FRONT_CHEST'], 'secondaryMuscleGroups': [],
            'sets': [{'type': 'WeightSet', 'reps': 8, 'subCategory': 'WorkSet'}
                for _ in range(count)]}]}]}


@pytest.mark.parametrize(('count', 'status', 'shortfall', 'excess'), [
    (0, 'below_preferred', 10, 0), (12, 'within_preferred', 0, 0),
    (20, 'above_preferred', 0, 5),
])
def test_preferred_range_reports_deviation_without_hard_audit_failure(count, status, shortfall, excess):
    targets = {'weeklyEffectiveSets': {'chest': _bounds()}}
    before = copy.deepcopy(targets)

    report = audit.audit_workout_package(_package(count), targets)

    assert report['errors'] == []
    assert report['volumePreferenceEvidence']['weekly'] == [{'muscle': 'chest',
        'preferredMinimum': 10, 'preferredMaximum': 15, 'actual': count,
        'shortfall': shortfall, 'excess': excess, 'status': status}]
    assert report['muscleCreditReliance']['weeklyTargets'] == []
    assert audit.volume_preference_deviation(count, _bounds()) == shortfall + excess
    text = audit.render_plan_disclosures(report, ['chest'])
    assert 'soft goals; deviations do not fail the hard audit' in text
    assert f'actual {count}; shortfall {shortfall}; excess {excess}' in text
    assert 'minimum' not in text
    assert targets == before
    json.dumps(report, allow_nan=False)


def test_preferred_audit_uses_weekly_frequency_and_keeps_hard_floor_and_cap():
    targets = {'weeklyEffectiveSets': {'chest': _bounds(minimum=8, maximum=18)},
        'perSessionEffectiveSets': {'chest': _bounds(preferredMinimum=4, preferredMaximum=None)}}

    report = audit.audit_workout_package(_package(3, frequency=2), targets)

    assert [(item['code'], item['actual'], item['minimum']) for item in report['errors']] == [
        ('volume_below_target', 6, 8)]
    assert report['volumePreferenceEvidence']['weekly'][0]['actual'] == 6
    assert report['volumePreferenceEvidence']['weekly'][0]['shortfall'] == 4
    assert report['volumePreferenceEvidence']['perSession'][0] == {'muscle': 'chest',
        'preferredMinimum': 4, 'preferredMaximum': None, 'actual': 3, 'shortfall': 1,
        'excess': 0, 'status': 'below_preferred', 'session': 'Day', 'sessionIndex': 0}
    assert audit.volume_target_bounds(targets['weeklyEffectiveSets']['chest']) == (8, 18)
    assert audit.preferred_volume_target_bounds(targets['perSessionEffectiveSets']['chest']) == (4, math.inf)
    capped = audit.audit_workout_package(_package(20), targets)
    assert 'volume_above_target' in {issue['code'] for issue in capped['errors']}
    assert audit.volume_preference_deviation(100, _bounds(preferredMaximum=None)) == 0
    assert audit.preferred_volume_target_bounds({'minimum': 3, 'maximum': 5}) is None
    assert audit.volume_preference_deviation(0, {'minimum': 3, 'maximum': 5}) == 0


@pytest.mark.parametrize('overrides', [
    {'preferredMinimum': None}, {'preferredMinimum': True}, {'preferredMinimum': -1},
    {'preferredMinimum': math.nan}, {'preferredMinimum': math.inf},
    {'preferredMaximum': True}, {'preferredMaximum': 9}, {'preferredMaximum': 101},
    {'preferredMaximum': math.nan}, {'preferredMaximum': math.inf},
    {'minimum': 11}, {'maximum': 14}, {'maximum': 20, 'preferredMaximum': None},
])
def test_preferred_ranges_reject_invalid_or_contradictory_values(overrides):
    with pytest.raises(ContractValidationError, match='preferred range'):
        audit.validate_audit_targets({'weeklyEffectiveSets': {'chest': _bounds(**overrides)}})


@pytest.mark.parametrize('missing', ['preferredMinimum', 'preferredMaximum'])
def test_preferred_range_requires_both_keys(missing):
    bounds = _bounds()
    del bounds[missing]
    with pytest.raises(ContractValidationError, match='preferred range'):
        audit.validate_audit_targets({'perSessionEffectiveSets': {'chest': bounds}})


def test_soft_regional_goal_preserves_unknown_evidence_without_hard_failure():
    targets = {'weeklyEffectiveSets': {'pectoralis_clavicular': _bounds()}}

    report = audit.audit_workout_package(_package(3), targets)

    assert report['errors'] == []
    preference = report['volumePreferenceEvidence']['weekly'][0]
    assert preference['status'] == 'unknown'
    assert preference['actual'] is None and preference['shortfall'] is None and preference['excess'] is None
    assert 'actual unknown because regional credit evidence is incomplete' in audit.render_plan_disclosures(report)
    targets['weeklyEffectiveSets']['pectoralis_clavicular']['minimum'] = 1
    hard_report = audit.audit_workout_package(_package(3), targets)
    assert 'regional_target_evidence_unknown' in {issue['code'] for issue in hard_report['errors']}
    legacy_report = audit.audit_workout_package(_package(3), {
        'weeklyEffectiveSets': {'pectoralis_clavicular': {'minimum': 0, 'maximum': None}}})
    assert 'regional_target_evidence_unknown' in {issue['code'] for issue in legacy_report['errors']}


def test_programming_preferences_use_selected_canonical_exercises_and_audited_time():
    from test_workout_generator_planning_tools import planning_case
    from workout_generator_pkg.allocation import _audit_raw

    equipment, requirements, _, draft = planning_case()
    requirements['preferredSessionSeconds'] = 400
    requirements['exerciseSelection'] = {'preferredMinimum': 2, 'preferredMaximum': 3,
        'muscles': ['chest', 'triceps']}
    day = draft['workouts'][0]
    day['timesCompletedInAWeek'] = 2
    plan, report = _audit_raw(draft, equipment, requirements, None, True)
    # Definitions not selected in the executable workout must not inflate variety.
    plan['exercises'].append({**plan['exercises'][0], 'id': 'unused', 'libraryDefinitionId': 'unused'})
    audit.audit_programming_preferences(report, plan, requirements)
    evidence = report['exerciseSelectionEvidence']
    assert evidence['chest']['count'] == evidence['triceps']['count'] == 1
    assert evidence['chest']['primaryExerciseIds'] == ['press']
    assert evidence['triceps']['secondaryExerciseIds'] == ['press']
    assert evidence['chest']['shortfall'] == 1
    actual = report['workouts'][0]['estimatedSeconds']
    assert report['sessionTimeBudgetEvidence']['totalWeeklyExcessSeconds'] == max(0, actual - 400) * 2
    text = audit.render_plan_disclosures(report)
    assert 'Preferred session-time budget' in text
    assert 'Count alone does not establish complementary ROM' in text


def test_decimal_timing_is_exact_at_public_boundary_without_rounding_inputs():
    package = _package(3)
    exercise = package['workouts'][0]['workoutComponents'][0]
    exercise['sets'] = [{'type': 'WeightSet', 'reps': 3, 'subCategory': 'WorkSet'}] * 3
    exercise['repDurationSeconds'] = 0.1
    exercise['setupSeconds'] = 0
    report = audit.audit_workout_package(package, {'weeklyEffectiveSets': {},
        'perSessionEffectiveSets': {}, 'maximumSessionSeconds': None})
    assert report['workouts'][0]['timing']['workSeconds'] == 0.9
    assert report['workouts'][0]['estimatedSeconds'] == 300.9
    json.dumps(report, allow_nan=False)
