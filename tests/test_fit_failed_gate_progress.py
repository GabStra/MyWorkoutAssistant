"""Focused regressions for fail-closed fit progress on numeric failed gates."""
from __future__ import annotations

from copy import deepcopy

import pytest

from exercise_motion_pkg import controlled_motion as motion
from exercise_motion_pkg.rig_playback import (
    PLAYBACK_CONTACT_LIMIT_METERS,
    PLAYBACK_FLOOR_LIMIT_METERS,
)


def _passing_playback(**overrides):
    playback = {
        'passed': True,
        'velocityContinuous': True,
        'physicalReasons': [],
        'physicalEvents': [],
        'maximumSamplePoseMismatchMeters': 0.,
        'maximumContactErrorMeters': PLAYBACK_CONTACT_LIMIT_METERS * .5,
        'maximumStoredFrameContactErrorMeters': PLAYBACK_CONTACT_LIMIT_METERS * .5,
        'maximumHeelContactErrorMeters': PLAYBACK_CONTACT_LIMIT_METERS * .5,
        'maximumHeightOnlyContactErrorMeters': PLAYBACK_FLOOR_LIMIT_METERS * .5,
        'maximumStoredFrameHeightOnlyContactErrorMeters': (
            PLAYBACK_FLOOR_LIMIT_METERS * .5),
        'maximumFloorPenetrationMeters': PLAYBACK_FLOOR_LIMIT_METERS * .5,
        'equipment': {'passed': True},
        'bodySupport': {'passed': True},
        'supportContactReadiness': {'passed': True},
        'shoeOrientation': {'passed': True},
        'materialShoes': {
            'passed': True,
            'maximumSurfacePenetrationMeters': PLAYBACK_FLOOR_LIMIT_METERS * .5,
            'maximumFullSoleContactErrorMeters': PLAYBACK_CONTACT_LIMIT_METERS * .5,
        },
        'canonicalShoeCalibration': {'passed': True},
        'canonicalMaterialShoes': {
            'passed': True,
            'toleranceMeters': .003,
            'maximumReflectedVertexErrorMeters': .001,
        },
        'supportAlignment': {'passed': True},
        'mirroredArms': {'passed': True},
    }
    playback.update(overrides)
    return playback


def _failed_jerk_playback_report(jerk_ratio=1.05, toe_ratio=1.1):
    limit = 2.1e-4
    toe_tolerance = 5e-4
    return {
        'applied': False,
        'checks': {
            'jerk': False,
            'playback': False,
            'sourceKneeEnvelope': True,
        },
        'jerkAfter': limit * jerk_ratio,
        'jerkFailureEvidence': {
            'acceptanceLimitRms': limit,
            'globalOutputRms': limit * jerk_ratio,
        },
        'playback': _passing_playback(
            passed=False,
            canonicalExecutionPolicy={
                'required': True,
                'passed': False,
                'posePolicy': {'required': False, 'passed': True},
                'stationaryBilateralStance': {
                    'required': True,
                    'passed': False,
                    'fitContactMaskAvailable': True,
                    'bothToePivotsPinnedByFitPolicy': True,
                    'compatibility': {'passed': True},
                    'toePivots': {
                        'left': {
                            'toleranceMeters': toe_tolerance,
                            'maximumDriftMeters': toe_tolerance * .9,
                            'maximumToeFloorErrorMeters': (
                                toe_tolerance * toe_ratio),
                        },
                        'right': {
                            'toleranceMeters': toe_tolerance,
                            'maximumDriftMeters': toe_tolerance * .8,
                            'maximumToeFloorErrorMeters': toe_tolerance * .7,
                        },
                    },
                },
            },
        ),
    }


def test_source_support_near_miss_contract_is_preserved():
    previous = {
        'applied': False,
        'checks': {
            'sourceSupportTrajectory': False,
            'contacts': True,
            'playback': True,
        },
        'sourceSupportTrajectory': {
            'relativePathRmsBodyRatio': .123,
            'maximumRmsBodyRatio': .12,
            'minimumRelevantTravelRetentionRatio': .9,
            'minimumTravelRetentionRatio': .8,
        },
        'playback': {'passed': True},
    }
    improved = deepcopy(previous)
    improved['sourceSupportTrajectory']['relativePathRmsBodyRatio'] = .1201

    progress = motion.fit_report_acceptance_progress(previous, improved)
    assert progress['improved'] is True
    assert progress['reason'] == 'normalized_failed_gate_violation_reduced'
    assert progress['improvedChecks'] == ['sourceSupportTrajectory']
    assert progress['violationMetricsBefore']['sourceSupportTrajectory'] == {
        'relativePathRmsBodyRatio': .123 / .12 - 1.,
        'minimumTravelRetentionRatio': 0.,
    }
    assert not motion.fit_report_improves_acceptance(previous, previous)


def _failed_source_foot_heading_report(right_heading_degrees):
    tolerance = 15.
    return {
        'applied': False,
        'checks': {
            'sourceFootContactArticulation': False,
            'sourceKneeEnvelope': True,
        },
        'sourceFootContactArticulation': {
            'available': True,
            'cameraHeading': {
                'gateApplied': True,
                'headingToleranceDegrees': tolerance,
                'absoluteAngularResidualP95Degrees': right_heading_degrees,
                'bySide': {
                    'left': {
                        'available': True,
                        'observationCount': 6,
                        'degenerateObservationCount': 0,
                        'absoluteAngularResidualP95Degrees': 12.,
                    },
                    'right': {
                        'available': True,
                        'observationCount': 6,
                        'degenerateObservationCount': 0,
                        'absoluteAngularResidualP95Degrees': right_heading_degrees,
                    },
                },
            },
            'nativeHeelPhase': {'available': False, 'passed': True},
            'sourceFootDirection': {'available': False, 'passed': True},
            'materialHeelTrajectory': {'available': False, 'passed': True},
        },
    }


def test_source_foot_heading_progress_advances_but_passed_gate_regression_fails():
    before = _failed_source_foot_heading_report(35.)
    after = _failed_source_foot_heading_report(20.)

    progress = motion.fit_report_acceptance_progress(before, after)
    assert progress['improved'] is True
    assert progress['reason'] == 'normalized_failed_gate_violation_reduced'
    assert progress['improvedChecks'] == ['sourceFootContactArticulation']
    assert progress['violationMetricsAfter']['sourceFootContactArticulation'][
        'cameraHeadingP95_right'] < progress['violationMetricsBefore'][
            'sourceFootContactArticulation']['cameraHeadingP95_right']

    regressed = deepcopy(after)
    regressed['checks']['sourceKneeEnvelope'] = False
    rejected = motion.fit_report_acceptance_progress(before, regressed)
    assert rejected['improved'] is False
    assert rejected['reason'] == 'previously_passed_gate_regressed'


def test_source_foot_progress_fails_closed_for_unmeasured_failed_subgate():
    before = _failed_source_foot_heading_report(35.)
    after = _failed_source_foot_heading_report(20.)
    after['sourceFootContactArticulation']['sourceFootDirection'] = {
        'available': False,
        'passed': False,
    }

    progress = motion.fit_report_acceptance_progress(before, after)
    assert progress['improved'] is False
    assert progress['reason'] == 'unmeasured_failed_gate_preservation'
    assert 'sourceFootContactArticulation' not in progress['violationMetricsAfter']


def test_jerk_and_playback_progress_uses_producer_stored_limits():
    before = _failed_jerk_playback_report(jerk_ratio=1.12, toe_ratio=1.2)
    after = _failed_jerk_playback_report(jerk_ratio=1.05, toe_ratio=1.1)
    assert set(motion.failed_check_names(after['checks'])) == {
        'jerk', 'playback'}

    metrics = motion.fit_report_check_violation_metrics(after)
    assert metrics['jerk']['jerkAfterRms'] == pytest.approx(1.05 - 1.)
    assert metrics['playback'][
        'canonicalStanceLeftMaximumToeFloorErrorMeters'] == pytest.approx(
            after['playback']['canonicalExecutionPolicy'][
                'stationaryBilateralStance']['toePivots']['left'][
                    'maximumToeFloorErrorMeters'] / 5e-4 - 1.)

    progress = motion.fit_report_acceptance_progress(before, after)
    assert progress['improved'] is True
    assert progress['reason'] == 'normalized_failed_gate_violation_reduced'
    assert progress['improvedChecks'] == ['jerk', 'playback']
    assert after['applied'] is False


@pytest.mark.parametrize('mutation', ['nested_passed', 'unknown_continuous',
                                      'physical_events'])
def test_hidden_playback_subfailure_blocks_numeric_progress(mutation):
    before = _failed_jerk_playback_report(jerk_ratio=1.12, toe_ratio=1.2)
    after = _failed_jerk_playback_report(jerk_ratio=1.05, toe_ratio=1.1)
    assert motion.fit_report_acceptance_progress(before, after)['improved']

    hidden = deepcopy(after)
    if mutation == 'nested_passed':
        hidden['playback']['newNestedGate'] = {'passed': False}
    elif mutation == 'unknown_continuous':
        hidden['playback']['newVelocityContinuous'] = False
    else:
        hidden['playback']['physicalEvents'] = [{'reason': 'new_contact_event'}]

    progress = motion.fit_report_acceptance_progress(before, hidden)
    assert progress['improved'] is False
    expected_reasons = {'unmeasured_failed_gate_preservation'}
    if mutation == 'physical_events':
        # A previously-empty physical event list is itself a passed subcheck.
        expected_reasons.add('previously_passed_gate_regressed')
    assert progress['reason'] in expected_reasons
    assert 'playback' not in progress['violationMetricsAfter']


def test_cleared_gate_does_not_hide_unmeasured_remaining_playback_failure():
    before = _failed_jerk_playback_report(jerk_ratio=1.12, toe_ratio=1.2)
    after = deepcopy(before)
    after['checks']['jerk'] = True
    after['playback']['newNestedGate'] = {'passed': False}
    progress = motion.fit_report_acceptance_progress(before, after)
    assert progress['improved'] is False
    assert progress['reason'] == 'unmeasured_failed_gate_preservation'
    assert progress['improvedChecks'] == []


def test_cleared_gate_progress_preserves_measured_remaining_gate():
    before = _failed_jerk_playback_report(jerk_ratio=1.12, toe_ratio=1.2)
    after = deepcopy(before)
    after['checks']['jerk'] = True
    progress = motion.fit_report_acceptance_progress(before, after)
    assert progress['improved'] is True
    assert progress['reason'] == 'failed_gate_cleared'
    assert progress['improvedChecks'] == ['jerk']


def test_unmeasured_simultaneous_failure_does_not_advance_progress():
    before = _failed_jerk_playback_report(jerk_ratio=1.12, toe_ratio=1.2)
    after = _failed_jerk_playback_report(jerk_ratio=1.05, toe_ratio=1.1)
    execution = after['playback']['canonicalExecutionPolicy']
    execution['reason'] = 'unrepresented_boolean_gate'

    progress = motion.fit_report_acceptance_progress(before, after)
    assert progress['improved'] is False
    assert progress['reason'] == 'unmeasured_failed_gate_preservation'
    assert 'playback' not in progress['violationMetricsAfter']


def test_passing_gate_regression_stays_rejected():
    previous = _failed_jerk_playback_report()
    regressed = deepcopy(previous)
    regressed['checks']['sourceKneeEnvelope'] = False
    regressed['jerkAfter'] *= .9
    regressed['jerkFailureEvidence']['globalOutputRms'] = regressed['jerkAfter']

    progress = motion.fit_report_acceptance_progress(previous, regressed)
    assert progress['improved'] is False
    assert progress['reason'] == 'previously_passed_gate_regressed'

    passing = copy_with_all_checks_passing(previous)
    passing['checks']['sourceKneeEnvelope'] = False
    progress = motion.fit_report_acceptance_progress(previous, passing)
    assert progress['improved'] is False
    assert progress['reason'] == 'previously_passed_gate_regressed'


def copy_with_all_checks_passing(report):
    candidate = deepcopy(report)
    candidate['checks'] = {name: True for name in candidate['checks']}
    candidate['applied'] = False
    candidate['playback']['passed'] = True
    candidate['playback']['canonicalExecutionPolicy']['passed'] = True
    candidate['playback']['canonicalExecutionPolicy'][
        'stationaryBilateralStance']['passed'] = True
    return candidate
