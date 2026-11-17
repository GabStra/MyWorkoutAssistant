"""Focused regressions for the v95 anatomy_torso_bend coupled-repair admission."""
import sys
from copy import deepcopy
from pathlib import Path

import pytest



from exercise_motion_pkg.controlled_motion import (  # noqa: E402
    anatomy_torso_bend_only_repair_eligible,
    contact_tangent_temporal_repair_eligible,
    temporal_repair_trial_retainable,
)

REASON = 'anatomy_torso_bend'


@pytest.mark.parametrize('field', [
    'trial_merit', 'merit_before',
    'accepted_dense_torso_excess', 'trial_dense_torso_excess',
])
def test_intermediate_repair_rejects_nonfinite_metrics(field):
    metrics = dict(trial_merit=.1, merit_before=.2,
                   accepted_dense_torso_excess=.001,
                   trial_dense_torso_excess=.0005,
                   require_dense_torso_preservation=True)
    metrics[field] = float('nan')
    retained, _ = temporal_repair_trial_retainable(report(), report(), **metrics)
    assert not retained


def test_intermediate_repair_requires_actual_trial_checks():
    retained, _ = temporal_repair_trial_retainable(
        report(), {'applied': True}, trial_merit=.1, merit_before=.2,
        accepted_dense_torso_excess=.001, trial_dense_torso_excess=.0005)
    assert not retained


def playback(*, physical_reasons=(REASON,), passed=False, **overrides):
    result = {
        'passed': passed,
        'maximumSamplePoseMismatchMeters': 1e-16,
        'maximumContactErrorMeters': 2.1e-5,
        'maximumStoredFrameContactErrorMeters': 6e-6,
        'maximumHeelContactErrorMeters': 0.,
        'maximumHeightOnlyContactErrorMeters': 0.,
        'maximumStoredFrameHeightOnlyContactErrorMeters': 0.,
        'maximumFloorPenetrationMeters': 0.,
        'maximumBoneLengthVariationMeters': 1e-16,
        'velocityContinuous': True,
        'seamContinuous': True,
        'physicalReasons': list(physical_reasons),
        'physicalEvents': [{'reason': reason} for reason in physical_reasons],
    }
    for name in (
            'equipment', 'bodySupport', 'supportContactReadiness',
            'shoeOrientation', 'materialShoes', 'canonicalShoeCalibration',
            'canonicalMaterialShoes', 'supportAlignment', 'mirroredArms',
            'canonicalExecutionPolicy'):
        result[name] = {'passed': True}
    result.update(overrides)
    return result


def report(*, failed=('anatomy', 'jerk', 'playback'), physical_reasons=(REASON,),
           playback_override=None):
    checks = {
        'anatomy': 'anatomy' not in failed,
        'contacts': True,
        'jerk': 'jerk' not in failed,
        'playback': 'playback' not in failed,
        'loopSeam': True,
        'sourceArticulation': True,
        'bodySupport': True,
    }
    for name in failed:
        checks[name] = False
    return {
        'checks': checks,
        'physicalReasons': list(physical_reasons),
        'physicalEvents': [{'reason': reason} for reason in physical_reasons],
        'playback': playback_override or playback(
            passed='playback' not in failed, physical_reasons=physical_reasons),
        'relativeMotionQuality': {'introducedSpikes': {'severe': False}},
        'sourceFootContactArticulation': {
            'nativeHeelPhase': {'passed': True},
            'sourceFootDirection': {'passed': True},
            'materialHeelTrajectory': {'passed': True},
        },
    }


def test_torso_bend_only_eligibility_accepts_complete_provenance():
    assert anatomy_torso_bend_only_repair_eligible(report())
    assert contact_tangent_temporal_repair_eligible(report())


def test_canonical_pose_repair_requires_opt_in_and_preserves_other_playback_gates():
    candidate = report()
    candidate['playback']['canonicalExecutionPolicy'] = {
        'required': True, 'passed': False,
        'posePolicy': {'required': True, 'passed': False,
                       'maximumResidualMeters': .0008, 'toleranceMeters': .0005},
        'stationaryBilateralStance': {'passed': True},
    }
    assert not contact_tangent_temporal_repair_eligible(candidate)
    assert contact_tangent_temporal_repair_eligible(candidate, allow_canonical_pose_repair=True)
    assert candidate['playback']['canonicalExecutionPolicy']['passed'] is False
    candidate['playback']['shoeOrientation']['passed'] = False
    assert not contact_tangent_temporal_repair_eligible(candidate, allow_canonical_pose_repair=True)


def test_extra_physical_reason_blocks_torso_scope():
    trial = report(physical_reasons=(REASON, 'anatomy_chest_attachment'))
    trial['playback'] = playback(
        physical_reasons=(REASON, 'anatomy_chest_attachment'))
    assert not anatomy_torso_bend_only_repair_eligible(trial)
    assert not contact_tangent_temporal_repair_eligible(trial)


def test_truncated_events_cannot_hide_extra_producer_reason():
    trial = report(physical_reasons=(REASON, 'anatomy_spine_fold'))
    # The diagnostic event excerpt is allowed to be truncated, but the
    # producer-owned complete reason set must still be authoritative.
    trial['physicalEvents'] = [{'reason': REASON}]
    trial['playback'] = playback(passed=True, physical_reasons=())
    assert not anatomy_torso_bend_only_repair_eligible(trial)


def test_unrelated_playback_subcheck_blocks_traversal():
    trial = report(playback_override=playback(
        bodySupport={'passed': False}))
    assert not anatomy_torso_bend_only_repair_eligible(trial)
    assert not contact_tangent_temporal_repair_eligible(trial)


@pytest.mark.parametrize('override', [
    {'velocityContinuous': False},
    {'seamContinuous': False},
    {'maximumSamplePoseMismatchMeters': 1e-3},
    {'maximumContactErrorMeters': .01},
    {'maximumStoredFrameContactErrorMeters': .01},
    {'maximumFloorPenetrationMeters': .01},
])
def test_playback_limit_regressions_block_traversal(override):
    trial = report(playback_override=playback(**override))
    assert not anatomy_torso_bend_only_repair_eligible(trial)


def test_original_temporal_scope_is_preserved():
    temporal = report(failed=('jerk',), physical_reasons=())
    temporal['playback'] = playback(passed=True, physical_reasons=())
    assert contact_tangent_temporal_repair_eligible(temporal)


def test_intermediate_acceptance_requires_bounded_progress():
    accepted = report()
    trial = report()
    retained, reason = temporal_repair_trial_retainable(
        accepted, trial, trial_merit=.06, merit_before=.08,
        accepted_dense_torso_excess=.001, trial_dense_torso_excess=.0009,
        require_dense_torso_preservation=True)
    assert retained and reason == 'bounded_coupled_progress'


def test_intermediate_acceptance_rejects_new_failure_identity():
    accepted = report()
    trial = report(failed=('anatomy', 'jerk', 'playback', 'sourceArticulation'))
    retained, reason = temporal_repair_trial_retainable(
        accepted, trial, trial_merit=.06, merit_before=.08,
        accepted_dense_torso_excess=.001, trial_dense_torso_excess=.0009)
    assert not retained and reason == 'new_failure_identity'


def test_intermediate_acceptance_rejects_scope_escape():
    accepted = report()
    trial = report(physical_reasons=(REASON, 'anatomy_spine_fold'))
    trial['playback'] = playback(
        physical_reasons=(REASON, 'anatomy_spine_fold'))
    retained, reason = temporal_repair_trial_retainable(
        accepted, trial, trial_merit=.06, merit_before=.08,
        accepted_dense_torso_excess=.001, trial_dense_torso_excess=.0009)
    assert not retained and reason == 'outside_repair_scope'


def test_intermediate_acceptance_rejects_dense_torso_regression_and_missing_measurement():
    accepted = report()
    trial = report()
    retained, reason = temporal_repair_trial_retainable(
        accepted, trial, trial_merit=.06, merit_before=.08,
        accepted_dense_torso_excess=.001, trial_dense_torso_excess=.0011,
        require_dense_torso_preservation=True)
    assert not retained and reason == 'dense_torso_regression'
    retained, reason = temporal_repair_trial_retainable(
        accepted, trial, trial_merit=.06, merit_before=.08,
        accepted_dense_torso_excess=None, trial_dense_torso_excess=.0009,
        require_dense_torso_preservation=True)
    assert not retained and reason == 'dense_torso_measurement_unavailable'


def test_original_temporal_attempts_keep_their_dense_policy():
    accepted = report(failed=('jerk',), physical_reasons=())
    accepted['playback'] = playback(passed=True, physical_reasons=())
    trial = report(failed=('jerk',), physical_reasons=())
    trial['playback'] = playback(passed=True, physical_reasons=())
    retained, reason = temporal_repair_trial_retainable(
        accepted, trial, trial_merit=.06, merit_before=.08,
        accepted_dense_torso_excess=.001, trial_dense_torso_excess=.002)
    assert retained and reason == 'bounded_coupled_progress'


def test_intermediate_acceptance_rejects_non_improving_merit():
    accepted = report()
    trial = report()
    retained, reason = temporal_repair_trial_retainable(
        accepted, trial, trial_merit=.08, merit_before=.08,
        accepted_dense_torso_excess=.001, trial_dense_torso_excess=.0009)
    assert not retained and reason == 'no_strict_merit_improvement'


def test_applied_trial_remains_authoritative():
    accepted = report()
    trial = report(failed=(), physical_reasons=())
    trial['applied'] = True
    trial['playback'] = playback(passed=True, physical_reasons=())
    retained, reason = temporal_repair_trial_retainable(
        accepted, trial, trial_merit=0., merit_before=.08,
        accepted_dense_torso_excess=.001, trial_dense_torso_excess=None)
    assert retained and reason == 'applied'
