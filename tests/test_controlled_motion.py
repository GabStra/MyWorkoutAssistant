import json
from pathlib import Path

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from exercise_motion_pkg.controlled_motion import FixedRig, body_relative_points, controlled_target, fit_controlled_motion


def test_hybrid_jacobian_defaults_on_and_supports_explicit_fallback(monkeypatch):
    from exercise_motion_pkg import controlled_motion as motion

    monkeypatch.delenv('EXERCISE_MOTION_HYBRID_JACOBIAN', raising=False)
    assert motion._hybrid_jacobian_enabled()
    monkeypatch.setenv('EXERCISE_MOTION_HYBRID_JACOBIAN', '0')
    assert not motion._hybrid_jacobian_enabled()
    monkeypatch.setenv('EXERCISE_MOTION_HYBRID_JACOBIAN', '1')
    assert motion._hybrid_jacobian_enabled()


def test_bounded_anatomy_projection_allows_temporal_near_misses_only():
    from exercise_motion_pkg import controlled_motion as motion

    structural_gates = {
        'contacts', 'heightOnlyContacts', 'sourceArticulation', 'trajectoryFit',
        'rootTravel', 'jointRange', 'fixedRig', 'bodySupport', 'supportAlignment',
        'rootContinuity', 'equipment', 'bodyRotation',
    }
    checks = {name: True for name in structural_gates}
    checks.update({
        'anatomy': False,
        'motionDiscontinuity': False,
        'playback': False,
    })

    assert motion.bounded_anatomy_projection_eligible(
        {'anatomy', 'motionDiscontinuity', 'playback'},
        checks,
        repairable_anatomy=True,
        cyclic=False,
    )
    assert not motion.bounded_anatomy_projection_eligible(
        {'anatomy', 'motionDiscontinuity', 'playback'},
        {**checks, 'sourceArticulation': False},
        repairable_anatomy=True,
        cyclic=False,
    )
    assert not motion.bounded_anatomy_projection_eligible(
        {'anatomy', 'motionDiscontinuity', 'playback'},
        checks,
        repairable_anatomy=False,
        cyclic=False,
    )
    assert not motion.bounded_anatomy_projection_eligible(
        {'anatomy', 'motionDiscontinuity', 'playback'},
        checks,
        repairable_anatomy=True,
        cyclic=True,
    )
    cyclic_near_miss = {
        **checks,
        'loopSeam': False,
    }
    assert motion.bounded_anatomy_projection_eligible(
        {'anatomy', 'motionDiscontinuity', 'playback', 'loopSeam'},
        cyclic_near_miss,
        repairable_anatomy=True,
        cyclic=True,
    )
    assert not motion.bounded_anatomy_projection_eligible(
        {'anatomy', 'motionDiscontinuity', 'playback', 'loopSeam'},
        {**cyclic_near_miss, 'bodySupport': False},
        repairable_anatomy=True,
        cyclic=True,
    )
    assert motion.bounded_anatomy_projection_eligible(
        {'anatomy', 'motionDiscontinuity', 'playback'},
        {**checks, 'loopSeam': True},
        repairable_anatomy=True,
        cyclic=True,
    )


def test_fit_continuation_must_strictly_improve_failed_checks():
    from exercise_motion_pkg import controlled_motion as motion

    previous = {'applied': False, 'checks': {
        'anatomy': True, 'contacts': True, 'playback': False,
        'motionDiscontinuity': False,
    }}
    assert not motion.fit_report_improves_acceptance(previous, {
        'applied': False, 'checks': dict(previous['checks']),
    })
    assert not motion.fit_report_improves_acceptance(previous, {
        'applied': False, 'checks': {
            'anatomy': True, 'contacts': False, 'playback': True,
            'motionDiscontinuity': False,
        },
    })
    assert motion.fit_report_improves_acceptance(previous, {
        'applied': False, 'checks': {
            'anatomy': True, 'contacts': True, 'playback': True,
            'motionDiscontinuity': False,
        },
    })
    assert motion.fit_report_improves_acceptance(previous, {
        'applied': True, 'checks': {name: True for name in previous['checks']},
    })


def test_swapped_materialized_sole_support_reaches_fit_without_mutating_source(monkeypatch):
    from copy import deepcopy

    from exercise_motion_pkg import controlled_motion as motion
    from exercise_motion_pkg.contact_constraints import motion_space_support_evidence
    from exercise_motion_pkg.support_geometry import support_evidence

    names = [
        'pelvis', 'left_hip', 'right_hip', 'left_shoulder', 'right_shoulder',
        'left_knee', 'right_knee', 'left_ankle', 'right_ankle', 'left_foot', 'right_foot',
    ]
    joints = {
        'pelvis': [0., .8, 0.],
        'left_hip': [-.15, .8, 0.],
        'right_hip': [.15, .8, 0.],
        'left_shoulder': [-.2, 1.2, 0.],
        'right_shoulder': [.2, 1.2, 0.],
        'left_knee': [-.15, .4, 0.],
        'right_knee': [.15, .4, 0.],
        'left_ankle': [-.15, .1, 0.],
        'right_ankle': [.15, .1, 0.],
        'left_foot': [-.15, .05, .08],
        'right_foot': [.15, .05, .08],
    }
    source_evidence = {
        'bodySupportObservation': {
            'status': 'observed',
            'observation': {
                'leftFoot': 'stationary_full_sole',
                'leftFootSurface': 'ground',
            },
        },
        'supportContacts': [{
            'jointName': 'left_foot',
            'contactState': 'full_sole',
            'contactMotion': 'stationary',
            'startRatio': 0.,
            'endRatio': 1.,
        }],
    }
    payload = {
        'jointNames': names,
        'frames': [
            {'timeSec': frame_index / 30., 'joints': deepcopy(joints)}
            for frame_index in range(9)
        ],
        'renderFloorY': 0.,
        'sourceFootSupportEvidence': deepcopy(source_evidence),
        'sourcePoseCameraReference': {'camera': {'bilateralAssignment': 'swapped'}},
    }
    cached_motion_evidence = deepcopy(motion_space_support_evidence(payload))
    consumed = {}

    def capture_fit_inputs(fit_payload, **_kwargs):
        mapped = motion_space_support_evidence(fit_payload)
        consumed['supportEvidence'] = support_evidence(fit_payload)
        consumed['pinned'] = motion.contact_mask(fit_payload, names, len(fit_payload['frames']))
        consumed['sourceEvidenceDigest'] = motion.controlled_motion_fit_source_evidence_digest(
            fit_payload
        )
        assert mapped['supportContacts'][0]['jointName'] == 'right_foot'
        return fit_payload, {'applied': True, 'strategy': motion.CONTROLLED_MOTION_STRATEGY}

    monkeypatch.setattr(motion, '_fit_controlled_motion_impl', capture_fit_inputs)
    result, report = motion._fit_controlled_motion(payload, timeout_seconds=30.)

    assert consumed['supportEvidence']['status'] == 'confirmed'
    assert consumed['supportEvidence']['soleContacts'][0]['joints'] == [
        'right_knee', 'right_ankle', 'right_foot',
    ]
    assert consumed['pinned'][:, names.index('right_foot')].all()
    assert report['fitSourceEvidenceDigest'] == consumed['sourceEvidenceDigest']
    assert report['fitSourceEvidenceDigest'] == (
        motion.controlled_motion_fit_source_evidence_digest(result)
    )
    assert result['sourceFootSupportEvidence'] == source_evidence
    assert payload['sourceFootSupportEvidence'] == source_evidence
    assert payload['motionSpaceSupportEvidence'] == cached_motion_evidence
    assert motion_space_support_evidence(payload) == cached_motion_evidence


def test_fit_source_evidence_is_stable_when_cycle_selection_moves_to_artifact_lineage():
    from copy import deepcopy

    from exercise_motion_pkg.controlled_motion import (
        controlled_motion_fit_source_evidence,
        controlled_motion_fit_source_evidence_digest,
    )

    fps = 30.0
    source_frames = [12, 13, 14]
    frames = [
        {
            'timeSec': index / fps,
            'sourceFrameIndex': source_frame,
            'sourceTimeSec': source_frame / fps,
            'cycleSourceFrameIndex': source_frame,
            'cycleSourceTimeSec': source_frame / fps,
            'joints': {},
        }
        for index, source_frame in enumerate(source_frames)
    ]
    loop = {
        'enabled': True,
        'sourceStartFrame': 12,
        'sourceEndFrame': 14,
        'sourceStartTimeSec': 12 / fps,
        'sourceEndTimeSec': 14 / fps,
    }
    legacy_payload = {
        'fps': fps,
        'frames': deepcopy(frames),
        'loop': deepcopy(loop),
        'loopCycleSelection': {
            'startFrame': 12,
            'stopFrameExclusive': 15,
            'inputFrameCount': 100,
            'sourceStartTimeSec': 12 / fps,
            'sourceStopTimeSec': 15 / fps,
        },
    }
    artifact_payload = {
        'fps': fps,
        'frames': deepcopy(frames),
        'loop': deepcopy(loop),
        'artifactState': {
            'selectionEvidence': {
                'cycleSelection': {
                    'selectionId': 'cycle-selection-id',
                    'interval': {
                        'startFrame': 12,
                        'endFrame': 14,
                        'startTimeSec': 12 / fps,
                        'endTimeSec': 14 / fps,
                    },
                },
            },
        },
    }

    assert controlled_motion_fit_source_evidence(legacy_payload)[
        'selectedSourceInterval'
    ] == controlled_motion_fit_source_evidence(artifact_payload)[
        'selectedSourceInterval'
    ]
    assert controlled_motion_fit_source_evidence_digest(
        legacy_payload
    ) == controlled_motion_fit_source_evidence_digest(artifact_payload)

    changed_selection = deepcopy(artifact_payload)
    changed_selection['artifactState']['selectionEvidence']['cycleSelection'][
        'interval'
    ]['endTimeSec'] += 1 / fps
    assert controlled_motion_fit_source_evidence_digest(
        changed_selection
    ) != controlled_motion_fit_source_evidence_digest(artifact_payload)

    retained_full_clip = {
        'fps': fps,
        'loop': {
            'enabled': True,
            'sourceStartFrame': 0,
            'sourceEndFrame': 119,
            'sourceStartTimeSec': 0.0,
            'sourceEndTimeSec': 119 / fps,
        },
        'sourceCyclePreflight': [{
            'passed': True,
            'selection': {'startFrame': 17, 'stopFrameExclusive': 100},
        }],
        'frames': [
            {
                'timeSec': index / fps,
                'sourceFrameIndex': index,
                'sourceTimeSec': index / fps,
                'joints': {},
            }
            for index in range(120)
        ],
    }
    fit_digest_before_lineage = controlled_motion_fit_source_evidence_digest(
        retained_full_clip
    )
    retained_full_clip['artifactState'] = {
        'selectionEvidence': {
            'fullClipBake': {'frameCount': 120},
            'cycleSelection': {
                'selectionId': 'retained-full-clip-selection',
                'interval': {
                    'startFrame': 0,
                    'endFrame': 119,
                    'startTimeSec': 0.0,
                    'endTimeSec': 119 / fps,
                },
            },
        },
    }
    assert controlled_motion_fit_source_evidence_digest(
        retained_full_clip
    ) == fit_digest_before_lineage
    assert controlled_motion_fit_source_evidence(
        retained_full_clip
    )['selectedSourceInterval'] == {
        'available': True,
        'kind': 'cycle',
        'startFrame': 0,
        'endFrame': 119,
        'startTimeSec': 0.0,
        'endTimeSec': 119 / fps,
    }


def test_cyclic_frame_probe_colors_are_unique_across_wrapped_three_frame_stencils():
    from exercise_motion_pkg.controlled_motion import _cyclic_frame_probe_colors

    for frame_count in range(3, 40):
        colors, color_count = _cyclic_frame_probe_colors(frame_count)
        assert set(colors) == set(range(color_count))
        for start in range(frame_count):
            stencil = [colors[(start + offset) % frame_count] for offset in range(3)]
            assert len(set(stencil)) == 3

    colors, color_count = _cyclic_frame_probe_colors(201)
    assert color_count == 3
    np.testing.assert_array_equal(colors, np.arange(201) % 3)


def test_root_rotation_smoothing_encodes_contact_compensation_in_fit_coordinates():
    from exercise_motion_pkg.controlled_motion import _smooth_root_rotation_candidate

    class RootAndFootRig:
        @staticmethod
        def decode(coordinates):
            points = np.zeros((len(coordinates), 2, 3))
            points[:, 0] = coordinates[:, :3]
            points[:, 1] = coordinates[:, :3]
            points[:, 1, 0] += coordinates[:, 3]
            return points

    coordinates = np.zeros((7, 6))
    coordinates[:, 3] = [0., .1, .3, .6, .3, .1, 0.]
    original = RootAndFootRig.decode(coordinates)

    smoothed_coordinates, smoothed_pose = _smooth_root_rotation_candidate(
        RootAndFootRig(), coordinates, original, [1], sigma=1.0)

    np.testing.assert_allclose(smoothed_pose, RootAndFootRig.decode(smoothed_coordinates))
    np.testing.assert_allclose(smoothed_pose[:, 1], original[:, 1], atol=1e-12)


def test_observed_cycle_fits_run_before_retained_open_seam_fallback(monkeypatch):
    from exercise_motion_pkg import controlled_motion as motion, loop_cycles

    proposals = [
        {'id': 'cycle-a'},
        {'id': 'cycle-b'},
        {'id': 'cycle-c'},
    ]
    current = {'loop': {'enabled': True}, 'frames': [{}] * 200,
               'observedCycleProposals': proposals}
    calls = []
    fake_time = [0.]

    monkeypatch.setattr(motion, 'monotonic', lambda: fake_time[0])
    monkeypatch.setattr(
        loop_cycles,
        'slice_loop_cycle',
        lambda payload, selection: {**payload, 'cycleSelection': selection},
    )

    def reject_fit(fit_payload, *, max_evaluations, timeout_seconds, shared_support):
        selection = fit_payload.get('cycleSelection')
        calls.append((selection or {'kind': 'retained_interval'}, timeout_seconds,
                      fit_payload['loop']['enabled']))
        fake_time[0] += timeout_seconds
        return fit_payload, {
            'applied': False,
            'reason': 'fit_validation_failed',
            'checks': {'trajectoryFit': False},
            'elapsedSeconds': timeout_seconds,
        }

    monkeypatch.setattr(motion, '_fit_controlled_motion', reject_fit)

    _, report = motion._fit_observed_cycles(current)

    assert [call[0] for call in calls] == [*proposals[:2], {'kind': 'retained_interval'}]
    assert [call[1] for call in calls] == [120., 120., 120.]
    assert [call[2] for call in calls] == [True, True, False]
    assert report['cycleSelectionAttempts'][-1]['selection'] == {'kind': 'retained_interval'}
    retained_attempt = report['cycleSelectionAttempts'][-1]
    assert retained_attempt['reason'] == 'fit_validation_failed'
    assert retained_attempt['fitReport']['elapsedSeconds'] == 120.


def test_observed_cycle_scheduler_skips_retained_fit_without_validation_budget(monkeypatch):
    from exercise_motion_pkg import controlled_motion as motion, loop_cycles

    proposals = [{'id': f'cycle-{index}'} for index in range(3)]
    current = {'loop': {'enabled': True}, 'frames': [{}] * 80,
               'observedCycleProposals': proposals}
    calls = []
    fake_time = [0.]

    monkeypatch.setattr(motion, 'monotonic', lambda: fake_time[0])
    monkeypatch.setattr(
        loop_cycles,
        'slice_loop_cycle',
        lambda payload, selection: {**payload, 'cycleSelection': selection},
    )

    def reject_fit(fit_payload, *, max_evaluations, timeout_seconds, shared_support):
        selection = fit_payload.get('cycleSelection') or {'kind': 'retained_interval'}
        calls.append((selection, timeout_seconds, fit_payload['loop']['enabled']))
        fake_time[0] += timeout_seconds
        return fit_payload, {
            'applied': False,
            'reason': 'fit_validation_failed',
            'checks': {'trajectoryFit': False},
            'elapsedSeconds': timeout_seconds,
        }

    monkeypatch.setattr(motion, '_fit_controlled_motion', reject_fit)

    _, report = motion._fit_observed_cycles(current, timeout_seconds=180.)

    assert [call[0] for call in calls] == [proposals[0], {'kind': 'retained_interval'}]
    assert [call[1] for call in calls] == [60., 120.]
    retained_attempt = report['cycleSelectionAttempts'][-1]
    assert retained_attempt['selection'] == {'kind': 'retained_interval'}
    assert retained_attempt['reason'] == 'fit_validation_failed'
    assert retained_attempt['fitReport']['elapsedSeconds'] == 120.


def test_observed_cycle_scheduler_runs_retained_fit_with_validation_budget(monkeypatch):
    from exercise_motion_pkg import controlled_motion as motion, loop_cycles

    choice = {'id': 'cycle-a'}
    current = {'loop': {'enabled': True}, 'frames': [{}] * 80,
               'observedCycleProposals': [choice]}
    calls = []
    fake_time = [0.]

    monkeypatch.setattr(motion, 'monotonic', lambda: fake_time[0])
    monkeypatch.setattr(
        loop_cycles,
        'slice_loop_cycle',
        lambda payload, selection: {**payload, 'cycleSelection': selection},
    )

    def reject_fit(fit_payload, *, max_evaluations, timeout_seconds, shared_support):
        selection = fit_payload.get('cycleSelection') or {'kind': 'retained_interval'}
        calls.append((selection, timeout_seconds))
        fake_time[0] += timeout_seconds
        return fit_payload, {
            'applied': False,
            'reason': 'fit_validation_failed',
            'checks': {'trajectoryFit': False},
            'elapsedSeconds': timeout_seconds,
        }

    monkeypatch.setattr(motion, '_fit_controlled_motion', reject_fit)

    _, report = motion._fit_observed_cycles(current, timeout_seconds=240.)

    assert [call[0] for call in calls] == [choice, {'kind': 'retained_interval'}]
    assert [call[1] for call in calls] == [120., 120.]
    assert report['cycleSelectionAttempts'][-1]['reason'] == 'fit_validation_failed'


def test_cycle_attempt_wall_timing_includes_early_fit_phases(monkeypatch):
    from exercise_motion_pkg import controlled_motion as motion, loop_cycles

    proposal = {'id': 'cycle-a'}
    current = {'loop': {'enabled': True}, 'frames': [{}] * 80,
               'observedCycleProposals': [proposal]}
    fake_time = [0.]

    monkeypatch.setattr(motion, 'monotonic', lambda: fake_time[0])
    monkeypatch.setattr(
        loop_cycles,
        'slice_loop_cycle',
        lambda payload, selection: {**payload, 'cycleSelection': selection},
    )

    def early_support_reject(fit_payload, **kwargs):
        fake_time[0] += 17.
        return fit_payload, {
            'applied': False,
            'reason': 'fit_validation_failed',
            'checks': {'supportReferenceGeometry': False},
            'supportInitializationSeconds': 17.,
        }

    monkeypatch.setattr(motion, '_fit_controlled_motion', early_support_reject)

    _, report = motion._fit_observed_cycles(current, timeout_seconds=180.)

    cycle_attempt = report['cycleSelectionAttempts'][0]
    assert cycle_attempt['elapsedSeconds'] == 17.
    assert cycle_attempt['reportedFitElapsedSeconds'] is None
    assert cycle_attempt['fitReport']['supportInitializationSeconds'] == 17.


def test_repeated_unreachable_core_cycle_failures_skip_retained_fit(monkeypatch):
    from exercise_motion_pkg import controlled_motion as motion, loop_cycles

    proposals = [{'id': 'cycle-a'}, {'id': 'cycle-b'}]
    current = {'loop': {'enabled': True}, 'frames': [{}] * 80,
               'observedCycleProposals': proposals}
    calls = []

    monkeypatch.setattr(
        loop_cycles,
        'slice_loop_cycle',
        lambda payload, selection: {**payload, 'cycleSelection': selection},
    )

    def reject_unreachable_core(fit_payload, **kwargs):
        calls.append(fit_payload.get('cycleSelection'))
        return fit_payload, {
            'applied': False,
            'reason': 'fit_validation_failed',
            'termination': 'unreachable_conflict',
            'checks': {'contacts': False, 'trajectoryFit': False},
            'elapsedSeconds': 12.,
        }

    monkeypatch.setattr(motion, '_fit_controlled_motion', reject_unreachable_core)

    _, report = motion._fit_observed_cycles(current, timeout_seconds=360.)

    assert calls == proposals
    assert report['cycleSelectionAttempts'][-1]['selection'] == {'kind': 'retained_interval'}
    assert report['cycleSelectionAttempts'][-1]['reason'] == (
        'retained_interval_skipped_after_unreachable_core_cycle_failure'
    )
    assert report['cycleSelectionAttempts'][-1]['fitReport']['skipReason'] == (
        'unreachable_core_cycle_failure'
    )
    assert report['retainedIntervalFit'] is False


def test_single_unreachable_core_cycle_keeps_open_retained_fallback(monkeypatch):
    from exercise_motion_pkg import controlled_motion as motion, loop_cycles

    proposal = {'id': 'cycle-a'}
    current = {'loop': {'enabled': True}, 'frames': [{}] * 80,
               'observedCycleProposals': [proposal]}
    calls = []

    monkeypatch.setattr(
        loop_cycles,
        'slice_loop_cycle',
        lambda payload, selection: {**payload, 'cycleSelection': selection},
    )

    def fail_cycle_then_recover_open_fit(fit_payload, **_kwargs):
        selection = fit_payload.get('cycleSelection')
        calls.append(selection or {'kind': 'retained_interval'})
        if selection:
            return fit_payload, {
                'applied': False,
                'reason': 'fit_validation_failed',
                'termination': 'unreachable_conflict',
                'checks': {'contacts': False, 'trajectoryFit': False},
                'elapsedSeconds': 12.,
            }
        assert fit_payload['loop']['enabled'] is False
        return fit_payload, {
            'applied': True,
            'reason': 'validated_controlled_motion',
            'checks': {},
            'elapsedSeconds': 12.,
        }

    monkeypatch.setattr(motion, '_fit_controlled_motion', fail_cycle_then_recover_open_fit)

    _, report = motion._fit_observed_cycles(current, timeout_seconds=360.)

    assert calls == [proposal, {'kind': 'retained_interval'}]
    assert report['applied'] is True
    assert report['reason'] == 'validated_controlled_motion_open_seam'
    assert report['retainedIntervalFit'] is True


def test_unreachable_noncore_cycle_failure_keeps_retained_recovery(monkeypatch):
    from exercise_motion_pkg import controlled_motion as motion, loop_cycles

    proposal = {'id': 'cycle-a'}
    current = {'loop': {'enabled': True}, 'frames': [{}] * 80,
               'observedCycleProposals': [proposal]}
    calls = []

    monkeypatch.setattr(
        loop_cycles,
        'slice_loop_cycle',
        lambda payload, selection: {**payload, 'cycleSelection': selection},
    )

    def fit_cycle_then_retain(fit_payload, **kwargs):
        selection = fit_payload.get('cycleSelection')
        calls.append(selection or {'kind': 'retained_interval'})
        if selection:
            return fit_payload, {
                'applied': False,
                'reason': 'fit_validation_failed',
                'termination': 'unreachable_conflict',
                'checks': {'anatomy': False, 'playback': False, 'loopSeam': False},
                'elapsedSeconds': 12.,
            }
        return fit_payload, {
            'applied': True,
            'reason': 'validated_controlled_motion',
            'checks': {},
            'elapsedSeconds': 12.,
        }

    monkeypatch.setattr(motion, '_fit_controlled_motion', fit_cycle_then_retain)

    _, report = motion._fit_observed_cycles(current, timeout_seconds=360.)

    assert calls == [proposal, {'kind': 'retained_interval'}]
    assert report['applied'] is True
    assert report['reason'] == 'validated_controlled_motion_open_seam'


def test_source_spine_fold_ratio_counts_distinct_frames(monkeypatch):
    from exercise_motion_pkg import controlled_motion as motion

    residuals = np.zeros((5, 1))
    residuals[[1, 3], 0] = 0.1
    monkeypatch.setattr(
        motion,
        'anatomical_structure_residuals',
        lambda _points, _names: (residuals, ['anatomy_spine_fold:spine2']),
    )
    payload = {
        'jointNames': ['pelvis'],
        'frames': [{'joints': {'pelvis': [0., float(i), 0.]}} for i in range(5)],
    }

    assert motion.source_spine_fold_frame_ratio(payload) == 0.4


def test_persistent_source_spine_fold_skips_only_retained_fallback(monkeypatch):
    from exercise_motion_pkg import controlled_motion as motion, loop_cycles

    proposal = {'id': 'cycle-a'}
    current = {'loop': {'enabled': True}, 'frames': [{}] * 80,
               'observedCycleProposals': [proposal]}
    calls = []
    fake_time = [0.]
    monkeypatch.setattr(motion, 'monotonic', lambda: fake_time[0])
    monkeypatch.setattr(motion, 'source_spine_fold_frame_ratio', lambda _payload: 0.32)
    monkeypatch.setattr(
        loop_cycles,
        'slice_loop_cycle',
        lambda payload, selection: {**payload, 'cycleSelection': selection},
    )

    def fail_cycle_anatomy(fit_payload, **kwargs):
        calls.append(fit_payload.get('cycleSelection'))
        fake_time[0] += 12.
        return fit_payload, {
            'applied': False,
            'reason': 'fit_validation_failed',
            'termination': 'unreachable_conflict',
            'checks': {'anatomy': False, 'playback': False, 'loopSeam': False},
            'physicalReasons': ['anatomy_spine_fold'],
            'elapsedSeconds': 12.,
        }

    monkeypatch.setattr(motion, '_fit_controlled_motion', fail_cycle_anatomy)

    _, report = motion._fit_observed_cycles(current, timeout_seconds=360.)

    assert calls == [proposal]
    skipped = report['cycleSelectionAttempts'][-1]
    assert skipped['selection'] == {'kind': 'retained_interval'}
    assert skipped['reason'] == 'retained_interval_skipped_after_persistent_source_spine_fold'
    assert skipped['fitReport']['sourceSpineFoldFrameRatio'] == 0.32
    assert report['reason'] == 'retained_interval_skipped_after_persistent_source_spine_fold'
    assert report['cycleRetryStopReason'] == (
        'persistent_source_spine_fold_after_cycle_anatomy_failure'
    )
    assert report['retainedIntervalFit'] is False


def test_repaired_source_spine_fold_keeps_retained_fit_fallback(monkeypatch):
    from exercise_motion_pkg import controlled_motion as motion, loop_cycles

    proposal = {'id': 'cycle-a'}
    current = {'loop': {'enabled': True}, 'frames': [{}] * 80,
               'observedCycleProposals': [proposal]}
    calls = []
    fake_time = [0.]
    monkeypatch.setattr(motion, 'monotonic', lambda: fake_time[0])
    monkeypatch.setattr(motion, 'source_spine_fold_frame_ratio', lambda _payload: 0.32)
    monkeypatch.setattr(
        loop_cycles,
        'slice_loop_cycle',
        lambda payload, selection: {**payload, 'cycleSelection': selection},
    )

    def fit_cycle_then_recover_source_fold(fit_payload, **_kwargs):
        fake_time[0] += 12.
        if fit_payload.get('cycleSelection'):
            calls.append(fit_payload['cycleSelection'])
            return fit_payload, {
                'applied': False,
                'reason': 'fit_validation_failed',
                'termination': 'unreachable_conflict',
                'checks': {'anatomy': False, 'playback': False, 'loopSeam': False},
                'physicalReasons': ['anatomy_spine_fold'],
                'anatomicalInitialization': {
                    'applied': True,
                    'passed': True,
                    'sourceViolations': ['anatomy_spine_fold:spine1'],
                    'remainingViolations': [],
                },
                'elapsedSeconds': 12.,
            }
        calls.append({'kind': 'retained_interval'})
        assert fit_payload['loop']['enabled'] is False
        return fit_payload, {
            'applied': True,
            'reason': 'validated_controlled_motion',
            'checks': {},
            'elapsedSeconds': 12.,
        }

    monkeypatch.setattr(motion, '_fit_controlled_motion', fit_cycle_then_recover_source_fold)

    _, report = motion._fit_observed_cycles(current, timeout_seconds=360.)

    assert calls == [proposal, {'kind': 'retained_interval'}]
    assert report['applied'] is True
    assert report['reason'] == 'validated_controlled_motion_open_seam'
    assert report['cycleSelectionAttempts'][-1]['selection'] == {'kind': 'retained_interval'}


def test_source_spine_fold_cutoff_preserves_lower_fold_retained_recovery(monkeypatch):
    from exercise_motion_pkg import controlled_motion as motion, loop_cycles

    proposal = {'id': 'cycle-a'}
    current = {'loop': {'enabled': True}, 'frames': [{}] * 80,
               'observedCycleProposals': [proposal]}
    calls = []
    fake_time = [0.]
    monkeypatch.setattr(motion, 'monotonic', lambda: fake_time[0])
    monkeypatch.setattr(motion, 'source_spine_fold_frame_ratio', lambda _payload: 0.1875)
    monkeypatch.setattr(
        loop_cycles,
        'slice_loop_cycle',
        lambda payload, selection: {**payload, 'cycleSelection': selection},
    )

    def fail_cycle_then_recover(fit_payload, **kwargs):
        selection = fit_payload.get('cycleSelection')
        calls.append(selection or {'kind': 'retained_interval'})
        fake_time[0] += 12.
        if selection:
            return fit_payload, {
                'applied': False,
                'reason': 'fit_validation_failed',
                'termination': 'unreachable_conflict',
                'checks': {'anatomy': False, 'playback': False, 'loopSeam': False},
                'physicalReasons': ['anatomy_spine_fold'],
                'elapsedSeconds': 12.,
            }
        return fit_payload, {
            'applied': True,
            'reason': 'validated_controlled_motion',
            'checks': {},
            'elapsedSeconds': 12.,
        }

    monkeypatch.setattr(motion, '_fit_controlled_motion', fail_cycle_then_recover)

    _, report = motion._fit_observed_cycles(current, timeout_seconds=360.)

    assert calls == [proposal, {'kind': 'retained_interval'}]
    assert report['applied'] is True
    assert report['reason'] == 'validated_controlled_motion_open_seam'


def test_repeated_root_travel_failure_skips_only_overlapping_cycle_family(monkeypatch):
    from exercise_motion_pkg import controlled_motion as motion, loop_cycles

    proposals = [
        {'startFrame': 2, 'stopFrameExclusive': 83},
        {'startFrame': 5, 'stopFrameExclusive': 83},
        {'startFrame': 8, 'stopFrameExclusive': 83},
    ]
    current = {'loop': {'enabled': True}, 'frames': [{}] * 100,
               'observedCycleProposals': proposals}
    calls = []
    fake_time = [0.]
    fit_durations = iter((108., 161.))

    monkeypatch.setattr(motion, 'monotonic', lambda: fake_time[0])
    monkeypatch.setattr(
        loop_cycles,
        'slice_loop_cycle',
        lambda payload, selection: {**payload, 'cycleSelection': selection},
    )

    def reject_root_travel(fit_payload, *, max_evaluations, timeout_seconds, shared_support):
        selection = fit_payload['cycleSelection']
        elapsed = next(fit_durations)
        calls.append(selection)
        fake_time[0] += elapsed
        return fit_payload, {
            'applied': False,
            'reason': 'fit_validation_failed',
            'checks': {'trajectoryFit': True, 'rootTravel': False},
            'elapsedSeconds': elapsed,
        }

    monkeypatch.setattr(motion, '_fit_controlled_motion', reject_root_travel)

    _, report = motion._fit_observed_cycles(current, timeout_seconds=360.)

    assert calls == proposals[:2]
    assert report['cycleRetryStopReason'] == 'repeated_unreachable_root_travel'
    assert report['cycleSelectionAttempts'][-1]['selection'] == {'kind': 'retained_interval'}


def test_repeated_root_travel_failure_does_not_skip_distinct_cycle():
    from exercise_motion_pkg.controlled_motion import repeated_unreachable_root_travel

    attempts = [
        {
            'selection': {'startFrame': 2, 'stopFrameExclusive': 83},
            'checks': {'trajectoryFit': True, 'rootTravel': False},
        },
        {
            'selection': {'startFrame': 5, 'stopFrameExclusive': 83},
            'checks': {'trajectoryFit': True, 'rootTravel': False},
        },
    ]

    assert repeated_unreachable_root_travel(
        attempts,
        [{'startFrame': 8, 'stopFrameExclusive': 83}],
    ) is True
    assert repeated_unreachable_root_travel(
        attempts,
        [{'startFrame': 35, 'stopFrameExclusive': 83}],
    ) is False


def test_repeated_anatomical_cycle_failure_skips_near_duplicate_after_valid_fallback(
    monkeypatch,
):
    from exercise_motion_pkg import controlled_motion as motion, loop_cycles

    proposals = [
        {'startFrame': 9, 'stopFrameExclusive': 95},
        {'startFrame': 12, 'stopFrameExclusive': 95},
        {'startFrame': 17, 'stopFrameExclusive': 91},
    ]
    current = {'loop': {'enabled': True}, 'frames': [{}] * 100,
               'observedCycleProposals': proposals}
    calls = []
    monkeypatch.setattr(motion, 'monotonic', lambda: 0.)
    monkeypatch.setattr(motion, 'pose_digest', lambda _payload: 'retained-digest')
    monkeypatch.setattr(
        loop_cycles,
        'slice_loop_cycle',
        lambda payload, selection: {**payload, 'cycleSelection': selection},
    )

    def fit_repeated_anatomical_failure(fit_payload, **_kwargs):
        selection = fit_payload.get('cycleSelection')
        calls.append(selection or {'kind': 'retained_interval'})
        if selection is None:
            return fit_payload, {
                'applied': True,
                'reason': 'validated_controlled_motion',
                'checks': {'anatomy': True, 'trajectoryFit': True},
                'elapsedSeconds': 20.,
            }
        return fit_payload, {
            'applied': False,
            'reason': 'fit_validation_failed',
            'checks': {'anatomy': False, 'contacts': True, 'playback': False},
            'physicalReasons': ['anatomy_torso_bend'],
            'elapsedSeconds': 110.,
        }

    monkeypatch.setattr(motion, '_fit_controlled_motion', fit_repeated_anatomical_failure)

    _, report = motion._fit_observed_cycles(current, timeout_seconds=360.)

    assert calls == [proposals[0], proposals[1], {'kind': 'retained_interval'}]
    assert report['applied'] is True
    assert report['reason'] == 'validated_controlled_motion_open_seam'
    assert report['cycleRetryStopReason'] == 'repeated_anatomical_cycle_failure'


def test_repeated_anatomical_cycle_failure_keeps_distinct_later_cycle_available(
    monkeypatch,
):
    from exercise_motion_pkg import controlled_motion as motion, loop_cycles

    proposals = [
        {'startFrame': 2, 'stopFrameExclusive': 60},
        {'startFrame': 12, 'stopFrameExclusive': 59},
        {'startFrame': 5, 'stopFrameExclusive': 60},
    ]
    current = {'loop': {'enabled': True}, 'frames': [{}] * 80,
               'observedCycleProposals': proposals}
    calls = []
    monkeypatch.setattr(motion, 'monotonic', lambda: 0.)
    monkeypatch.setattr(motion, 'pose_digest', lambda _payload: 'open-cycle-digest')
    monkeypatch.setattr(
        loop_cycles,
        'slice_loop_cycle',
        lambda payload, selection: {**payload, 'cycleSelection': selection},
    )

    def later_cycle_passes(fit_payload, **_kwargs):
        selection = fit_payload.get('cycleSelection')
        calls.append(selection or {'kind': 'retained_interval'})
        if selection == proposals[2]:
            return fit_payload, {
                'applied': True,
                'reason': 'validated_controlled_motion_open_seam',
                'checks': {'anatomy': True, 'playback': True},
                'loopSeamOpen': True,
                'elapsedSeconds': 105.,
            }
        return fit_payload, {
            'applied': False,
            'reason': 'fit_validation_failed',
            'checks': {'anatomy': True, 'jerk': False, 'loopSeam': False},
            'physicalReasons': [],
            'elapsedSeconds': 100.,
        }

    monkeypatch.setattr(motion, '_fit_controlled_motion', later_cycle_passes)

    result, report = motion._fit_observed_cycles(current, timeout_seconds=360.)

    assert calls == [*proposals, {'kind': 'retained_interval'}]
    assert result['cycleSelection'] == proposals[2]
    assert report['reason'] == 'validated_controlled_motion_open_seam'
    assert report.get('cycleRetryStopReason') is None


def test_no_observed_cycle_fits_retained_interval_open_for_seam_repair(monkeypatch):
    from exercise_motion_pkg import controlled_motion as motion, loop_cycles

    current = {'loop': {'enabled': True}, 'frames': [{}] * 80,
               'observedCycleProposals': []}
    calls = []
    monkeypatch.setattr(motion, 'monotonic', lambda: 0.)
    monkeypatch.setattr(motion, 'pose_digest', lambda _payload: 'digest')
    monkeypatch.setattr(loop_cycles, 'slice_loop_cycle', lambda payload, selection: payload)

    def accept_open_fit(fit_payload, *, max_evaluations, timeout_seconds, shared_support):
        calls.append((fit_payload['loop']['enabled'], timeout_seconds))
        return fit_payload, {
            'applied': True,
            'reason': 'validated_controlled_motion',
            'checks': {'trajectoryFit': True},
            'elapsedSeconds': 120.,
        }

    monkeypatch.setattr(motion, '_fit_controlled_motion', accept_open_fit)

    result, report = motion._fit_observed_cycles(current, timeout_seconds=240.)

    assert calls == [(False, 240.)]
    assert result['loop']['enabled'] is True
    assert result['loop']['transition'] == 'requires_cycle_repair'
    assert report['loopSeamOpen'] is True
    assert report['reason'] == 'validated_controlled_motion_open_seam'


def test_rejected_source_cycle_preflight_skips_open_seam_fit(monkeypatch):
    from exercise_motion_pkg import controlled_motion as motion

    current = {
        'loop': {'enabled': True},
        'frames': [{}] * 80,
        'observedCycleProposals': [],
        'sourceCyclePreflight': [{
            'passed': False,
            'reason': 'no_feasible_observed_cycle',
            'proposalDiagnostics': {
                'counts': {
                    'completePhase': 10,
                    'rangePreserved': 0,
                    'wrapFeasible': 0,
                },
            },
        }],
    }

    def fail_if_fit_runs(*_args, **_kwargs):
        raise AssertionError('source-rejected loop must not enter optimizer fallback')

    monkeypatch.setattr(motion, 'monotonic', lambda: 0.)
    monkeypatch.setattr(motion, '_fit_controlled_motion', fail_if_fit_runs)

    result, report = motion._fit_observed_cycles(current, timeout_seconds=240.)

    assert result is current
    assert report['applied'] is False
    assert report['reason'] == 'source_cycle_preflight_rejected'
    assert report['retainedIntervalFit'] is False


def test_selected_artifact_cycle_with_failed_source_phase_skips_fitting(monkeypatch):
    from exercise_motion_pkg import controlled_motion as motion

    current = {
        'loop': {'enabled': True},
        'frames': [{}] * 80,
        'artifactState': {
            'selectionEvidence': {
                'cycleSelection': {
                    'interval': {'startFrame': 4, 'endFrame': 79},
                },
            },
        },
        'selectedIntervalSourcePhasePreflight': {
            'required': True,
            'passed': False,
            'sourcePhase': {'required': True, 'passed': False},
        },
    }

    def fail_if_fit_runs(*_args, **_kwargs):
        raise AssertionError('source-rejected selected cycle must skip fitting')

    monkeypatch.setattr(motion, 'monotonic', lambda: 0.)
    monkeypatch.setattr(motion, '_fit_controlled_motion', fail_if_fit_runs)

    result, report = motion._fit_observed_cycles(current, timeout_seconds=240.)

    assert result is current
    assert report['applied'] is False
    assert report['reason'] == 'selected_interval_source_phase_rejected'
    assert report['selectedIntervalSourcePhasePreflight'] == (
        current['selectedIntervalSourcePhasePreflight']
    )


def stance(count=45):
    fixture=json.loads((Path(__file__).parent/'fixtures/sequence_stabilization_stance.json').read_text())
    names=list(fixture['joints'])
    points=np.tile(np.array([fixture['joints'][n] for n in names]),(count,1,1))
    return names,points


def payload(names,points,fps=30.):
    return {'fps':fps,'jointNames':names,'frames':[{'timeSec':i/fps,'joints':dict(zip(names,p.tolist()))}
                                                for i,p in enumerate(points)]}


def test_velocity_repair_checks_grip_after_smoothing_and_skips_valid_projection(monkeypatch):
    from exercise_motion_pkg import controlled_motion as motion, rig_interpolation
    from exercise_motion_pkg.equipment_constraints import calibrated_grip_constraint, validate_grip
    names, points = stance(7)
    rig = FixedRig(points, names)
    original = rig.initial.copy()
    equipment = calibrated_grip_constraint({'equipmentConstraints': {'handRelationship': 'rigid_pair'}},
                                           rig.decode(original), names)
    changed = original.copy()
    slot = rig.slots[names.index('right_elbow')]
    changed[:, slot:slot+3] += [.8, .5, .4]
    assert not validate_grip(rig.decode(changed), names, equipment)['passed']
    calls = []
    monkeypatch.setattr(motion, 'project_playback_neck_clearance', lambda coords, *a, **k: coords)
    monkeypatch.setattr(motion, 'temporal_coordinate_smooth', lambda *a, **k: changed.copy())
    def restore(values, *args, **kwargs):
        calls.append('grip')
        return original.copy()
    monkeypatch.setattr(motion, 'project_rigid_pair_grip_coordinates', restore)
    monkeypatch.setattr(motion, 'project_playback_rigid_pair_grip', lambda coords, *a, **k: coords)
    jumps = iter([1., 0., 0.])
    monkeypatch.setattr(rig_interpolation, 'frame_boundary_velocity_jump', lambda *a: next(jumps))
    repaired = motion.repair_playback_velocity_continuity(original, rig, None, None,
                                                        names=names, equipment=equipment)
    assert calls == ['grip']
    assert validate_grip(rig.decode(repaired), names, equipment)['passed']
    monkeypatch.setattr(rig_interpolation, 'frame_boundary_velocity_jump', lambda *a: 0.)
    motion.repair_playback_velocity_continuity(original, rig, None, None, names=names, equipment=equipment)
    assert calls == ['grip']


def test_cyclic_fit_evaluates_all_seam_residuals_with_matching_dependencies(monkeypatch):
    from types import SimpleNamespace
    from exercise_motion_pkg import controlled_motion as motion
    names, points = stance(12)
    current = payload(names, points)
    current['loop'] = {'enabled': True}
    calls = []
    socket_errors = []
    original_structure = motion.anatomical_structure_residuals
    def record_structure(values, *args, **kwargs):
        errors, labels = original_structure(values, *args, **kwargs)
        socket_errors.append((len(values), float(np.max(
            errors[:, labels.index('anatomy_socket_alignment:neck')]))))
        return errors, labels
    monkeypatch.setattr(motion, 'anatomical_structure_residuals', record_structure)
    neck_slot = FixedRig(points, names).slots[names.index('neck')]
    def solve(residual, initial, pattern, max_evaluations):
        errors = residual(initial)
        assert pattern.shape == (len(errors), len(initial))
        assert np.isfinite(errors).all()
        probe = initial.reshape(len(points), -1).copy()
        probe[:, neck_slot:neck_slot + 3] = [0., 0., .3]
        socket_errors.clear()
        probe_errors = residual(probe.ravel())
        assert np.isfinite(probe_errors).all()
        # Both keyframes and interpolated samples must expose the underlying
        # socket violation, even though playback itself clamps that geometry.
        assert any(count == len(points) and error > .1 for count, error in socket_errors)
        assert any(count > len(points) and error > .1 for count, error in socket_errors)
        calls.append(True)
        return SimpleNamespace(x=initial, nfev=1, status=0)
    monkeypatch.setattr(motion, 'solve_trajectory', solve)
    motion.fit_controlled_motion(current, timeout_seconds=10.)
    assert calls


def test_source_projection_constraint_enters_the_production_fit_jacobian(monkeypatch):
    from types import SimpleNamespace
    from exercise_motion_pkg import controlled_motion as motion

    names, source_points = stance(12)
    points = source_points.copy()
    points[4, names.index('left_wrist'), 0] += .035
    current = payload(names, points)
    source_origin = 21.0
    current['loopCycleSelection'] = {
        'startFrame': 0,
        'stopFrameExclusive': len(points),
        'sourceStartTimeSec': source_origin,
        'sourceStopTimeSec': source_origin + len(points) / current['fps'],
    }
    source_frames = []
    for frame_index, source_frame in enumerate(current['frames']):
        source_timestamp = source_origin + source_frame['timeSec']
        source_frame['cycleSourceFrameIndex'] = frame_index
        source_frame['cycleSourceTimeSec'] = source_timestamp
        source_joints = {
            name: [float(point[0] * .4 + .5), float(point[1] * .4 + .5)]
            for name, point in zip(names, source_points[frame_index])
        }
        source_joints['left_wrist'][0] += frame_index * .01
        source_frames.append({
            'sourceTimeSec': source_timestamp,
            'joints': source_joints,
            'jointConfidence': {name: .64 for name in names},
        })
        source_frame['sourceTimeSec'] = source_timestamp
    current['sourcePoseCameraReference'] = {
        'sourcePose': {
            'coordinateSpace': 'normalized_image_xy',
            'imageWidth': 1000,
            'imageHeight': 1000,
            'sourceTimeOriginSec': source_origin,
            'frames': source_frames,
        },
        'camera': {
            'cameraRotation': np.eye(3).tolist(),
            'cameraImageTransform': [.4, 0., 0., 0., .5, .5],
            'bilateralAssignment': 'identity',
        },
    }

    captured = []

    def capture_solver(residual, initial, pattern, max_evaluations, *, local_jacobian=None):
        errors = residual(initial)
        jacobian = local_jacobian(initial)
        assert pattern.shape == jacobian.shape == (len(errors), len(initial))
        captured.append((residual, errors, jacobian, initial.copy()))
        return SimpleNamespace(x=initial, nfev=1, status=0)

    monkeypatch.setattr(motion, 'solve_trajectory', capture_solver)
    _, report = motion.fit_controlled_motion(current, max_evaluations=1, timeout_seconds=10.)

    constraint = report['sourceProjectionConstraint']
    assert constraint['available'] is True
    assert constraint['observationCount'] >= 6
    assert constraint['endpointPostureObservationCount'] >= 6
    assert constraint['endpointPostureCoverage']['start']['available'] is True
    assert constraint['endpointPostureCoverage']['end']['available'] is True
    assert np.isclose(constraint['endpointPostureCoverage']['start']['meanConfidenceWeight'], .8)
    constrained_joint_count = sum(
        constraint['endpointPostureCoverage'][role]['constrainedJointCount']
        for role in ('start', 'end')
    )
    assert constraint['endpointPostureObservationCount'] > constrained_joint_count
    assert captured
    residual, errors, jacobian, initial = captured[0]
    source_row_count = constraint['observationCount'] * 2
    endpoint_row_count = constraint['endpointPostureObservationCount'] * 2
    # Source projection and endpoint posture constraints follow the other fit
    # rows. Check their production residual/Jacobian ordering independently.
    epsilon = 1e-6
    moved = initial.copy()
    moved[0] += epsilon
    numeric = (residual(moved) - errors) / epsilon
    source_start = len(errors) - endpoint_row_count - source_row_count
    np.testing.assert_allclose(
        jacobian[source_start:source_start + source_row_count, 0].toarray().ravel(),
        numeric[source_start:source_start + source_row_count],
        rtol=1e-3,
        atol=1e-4,
    )
    endpoint_start = len(errors) - endpoint_row_count
    endpoint_jacobian = jacobian[endpoint_start:]
    endpoint_jacobian_coo = endpoint_jacobian.tocoo()
    largest = int(np.argmax(np.abs(endpoint_jacobian_coo.data)))
    endpoint_column = int(endpoint_jacobian_coo.col[largest])
    moved = initial.copy()
    moved[endpoint_column] += epsilon
    endpoint_numeric = (residual(moved) - errors)[endpoint_start:] / epsilon
    np.testing.assert_allclose(
        endpoint_jacobian[:, endpoint_column].toarray().ravel(),
        endpoint_numeric,
        rtol=2e-3,
        atol=2e-4,
    )


def test_selected_cycle_boundaries_get_stronger_source_projection_fit_rows():
    from exercise_motion_pkg import controlled_motion as motion

    names, points = stance(12)
    current = payload(names, points)
    source_origin = 3.0
    source_frames = []
    for frame_index, frame in enumerate(current['frames']):
        cycle_time = source_origin + frame['timeSec']
        frame['cycleSourceFrameIndex'] = frame_index
        frame['cycleSourceTimeSec'] = cycle_time
        source_frames.append({
            'sourceTimeSec': cycle_time,
            'joints': {
                name: [float(point[0] * .4 + .5), float(point[1] * .4 + .5)]
                for name, point in zip(names, points[frame_index])
            },
        })
    current['loopCycleSelection'] = {
        'startFrame': 0,
        'stopFrameExclusive': len(points),
        'sourceStartTimeSec': source_origin,
        'sourceStopTimeSec': source_origin + len(points) / current['fps'],
    }
    current['sourcePoseCameraReference'] = {
        'sourcePose': {
            'coordinateSpace': 'normalized_image_xy',
            'imageWidth': 1000,
            'imageHeight': 1000,
            'frames': source_frames,
        },
        'camera': {
            'cameraRotation': np.eye(3).tolist(),
            'cameraImageTransform': [.4, 0., 0., 0., .5, .5],
            'bilateralAssignment': 'identity',
        },
    }

    constraint = motion._prepare_source_projection_fit_constraints(
        current,
        current['frames'],
        names,
        points,
        np.zeros((len(points), len(names)), dtype=bool),
        motion.body_scale(points, names),
    )

    assert constraint['available']
    assert constraint['cycleBoundaryCoverage']['selectedCycle']
    assert constraint['cycleBoundaryCoverage']['start']['available']
    assert constraint['cycleBoundaryCoverage']['end']['available']
    observations = constraint['observations']
    start_index = next(
        index for index, row in enumerate(observations)
        if 'start' in row['cycleBoundaryRoles'] and row['jointIndex'] == names.index('pelvis')
    )
    middle_index = next(
        index for index, row in enumerate(observations)
        if not row['cycleBoundaryRoles'] and row['jointIndex'] == names.index('pelvis')
        and abs((row['leftFrame'] + row['alpha']
                 * (row['rightFrame'] - row['leftFrame'])) - len(points) / 2) < 1.0
    )
    assert np.isclose(
        observations[start_index]['fitConfidenceWeight'],
        2.0 * observations[start_index]['confidenceWeight'],
    )
    assert np.isclose(
        observations[middle_index]['fitConfidenceWeight'],
        observations[middle_index]['confidenceWeight'],
    )

    baseline = motion._source_projection_fit_rows(points, constraint)
    moved_start = points.copy()
    moved_start[0, names.index('pelvis'), 0] += .01
    moved_middle = points.copy()
    middle_observation = observations[middle_index]
    moved_middle[middle_observation['leftFrame'], names.index('pelvis'), 0] += .01
    moved_middle[middle_observation['rightFrame'], names.index('pelvis'), 0] += .01
    start_rows = slice(start_index * 2, start_index * 2 + 2)
    middle_rows = slice(middle_index * 2, middle_index * 2 + 2)
    start_delta = motion._source_projection_fit_rows(moved_start, constraint)[start_rows] - baseline[start_rows]
    middle_delta = motion._source_projection_fit_rows(moved_middle, constraint)[middle_rows] - baseline[middle_rows]
    assert np.isclose(np.linalg.norm(start_delta) / np.linalg.norm(middle_delta), 2.0)


def _artifact_state_source_fit_payload(selection_class):
    from exercise_motion_pkg import controlled_motion as motion

    names, points = stance(12)
    current = payload(names, points)
    source_origin = 3.0
    source_start_frame = 10
    source_end_frame = source_start_frame + len(points) - 1
    source_start_time = source_origin
    source_end_time = source_origin + current['frames'][-1]['timeSec']
    source_frames = []
    for frame_index, frame in enumerate(current['frames']):
        timestamp = source_origin + frame['timeSec']
        frame['sourceFrameIndex'] = source_start_frame + frame_index
        frame['sourceTimeSec'] = timestamp
        source_frames.append({
            'sourceTimeSec': timestamp,
            'joints': {
                name: [float(point[0] * .4 + .5), float(point[1] * .4 + .5)]
                for name, point in zip(names, points[frame_index])
            },
            'jointConfidence': {name: .81 for name in names},
        })
    interval = {
        'type': 'observed_cycle' if selection_class == 'cycleSelection'
        else 'exact_source_movement_instance',
        'startFrame': source_start_frame,
        'endFrame': source_end_frame,
        'startTimeSec': source_start_time,
        'endTimeSec': source_end_time,
        'durationSec': source_end_time - source_start_time,
    }
    current['loop'] = {
        'enabled': True,
        'sourceStartFrame': source_start_frame,
        'sourceEndFrame': source_end_frame,
        'sourceStartTimeSec': source_start_time,
        'sourceEndTimeSec': source_end_time,
    }
    current['artifactState'] = {
        'selectionEvidence': {selection_class: {'interval': interval}},
    }
    current['sourcePoseCameraReference'] = {
        'sourcePose': {
            'coordinateSpace': 'normalized_image_xy',
            'imageWidth': 1000,
            'imageHeight': 1000,
            'sourceTimeOriginSec': source_origin,
            'frames': source_frames,
        },
        'camera': {
            'cameraRotation': np.eye(3).tolist(),
            'cameraImageTransform': [.4, 0., 0., 0., .5, .5],
            'bilateralAssignment': 'identity',
        },
    }
    return current, names, points


def test_artifact_state_selected_intervals_feed_endpoint_fit_rows_and_cycle_only_boundary_weight():
    from exercise_motion_pkg import controlled_motion as motion

    for selection_key, expected_kind in (
        ('cycleSelection', 'cycle'),
        ('boundedMovementSelection', 'bounded_movement'),
    ):
        current, names, points = _artifact_state_source_fit_payload(selection_key)
        constraint = motion._prepare_source_projection_fit_constraints(
            current,
            current['frames'],
            names,
            points,
            np.zeros((len(points), len(names)), dtype=bool),
            motion.body_scale(points, names),
        )

        assert constraint['available'] is True
        assert constraint['selectedIntervalKind'] == expected_kind
        assert constraint['selectedIntervalEvidenceSource'] == f'artifactState.{selection_key}'
        assert constraint['endpointPostureCoverage']['selectedMovement'] is True
        assert constraint['endpointPostureCoverage']['start']['available'] is True
        assert constraint['endpointPostureCoverage']['end']['available'] is True
        assert constraint['endpointPostureObservationCount'] > 0

        endpoint_rows = motion._source_endpoint_posture_fit_rows(points, constraint)
        assert endpoint_rows.size == constraint['endpointPostureObservationCount'] * 2
        rig = FixedRig(points, names)
        endpoint_jacobian = motion._source_endpoint_posture_fit_jacobian(
            constraint,
            frame_count=len(points),
            joint_count=len(names),
            rig=rig,
            coordinates=rig.initial,
        )
        assert endpoint_jacobian.shape[0] == endpoint_rows.size
        assert endpoint_jacobian.nnz > 0

        observations = constraint['observations']
        start_rows = [row for row in observations if 'start' in row['cycleBoundaryRoles']]
        end_rows = [row for row in observations if 'end' in row['cycleBoundaryRoles']]
        if expected_kind == 'cycle':
            assert constraint['cycleBoundaryCoverage']['selectedCycle'] is True
            assert constraint['cycleBoundaryCoverage']['start']['available'] is True
            assert constraint['cycleBoundaryCoverage']['end']['available'] is True
            assert start_rows and end_rows
            assert np.isclose(
                start_rows[0]['fitConfidenceWeight'],
                constraint['cycleBoundaryFitMultiplier'] * start_rows[0]['confidenceWeight'],
            )
        else:
            assert constraint['cycleBoundaryCoverage']['selectedCycle'] is False
            assert constraint['cycleBoundaryCoverage']['selectedMovement'] is True
            assert not start_rows and not end_rows
            assert all(np.isclose(
                row['fitConfidenceWeight'], row['confidenceWeight'],
            ) for row in observations)


def test_artifact_state_selected_interval_fails_closed_when_loop_source_bounds_disagree():
    from exercise_motion_pkg import controlled_motion as motion

    current, names, points = _artifact_state_source_fit_payload('cycleSelection')
    current['loop']['sourceEndTimeSec'] += .1
    constraint = motion._prepare_source_projection_fit_constraints(
        current,
        current['frames'],
        names,
        points,
        np.zeros((len(points), len(names)), dtype=bool),
        motion.body_scale(points, names),
    )

    assert constraint['available'] is True
    assert constraint['selectedIntervalKind'] is None
    assert constraint['selectedIntervalReason'] == 'selected_source_interval_loop_bounds_mismatch'
    assert constraint['endpointPostureObservationCount'] == 0
    assert not any(row['cycleBoundaryRoles'] for row in constraint['observations'])


def test_legacy_cycle_selection_requires_matching_crop_frame_and_time_provenance():
    from exercise_motion_pkg import controlled_motion as motion

    names, points = stance(12)
    current = payload(names, points)
    source_origin = 7.5
    source_times = []
    for frame_index, frame in enumerate(current['frames']):
        source_time = source_origin + frame['timeSec']
        frame['cycleSourceFrameIndex'] = frame_index
        frame['cycleSourceTimeSec'] = source_time
        source_times.append(source_time)
    current['loopCycleSelection'] = {
        'startFrame': 0,
        'stopFrameExclusive': len(points),
        'inputFrameCount': len(points),
        'sourceStartTimeSec': source_times[0],
        'sourceStopTimeSec': source_times[-1] + 1. / current['fps'],
    }

    assert motion._fit_source_interval_selection(current)['available'] is True

    current['frames'][4]['cycleSourceFrameIndex'] += 1
    selection = motion._fit_source_interval_selection(current)
    assert selection['available'] is False
    assert selection['reason'] == 'selected_source_interval_legacy_frame_bounds_mismatch'

    current['frames'][4]['cycleSourceFrameIndex'] -= 1
    current['frames'][-1]['cycleSourceTimeSec'] += .01
    selection = motion._fit_source_interval_selection(current)
    assert selection['available'] is False
    assert selection['reason'] == 'selected_source_interval_legacy_time_bounds_mismatch'


def test_endpoint_posture_uses_the_same_pelvis_center_for_source_and_fit():
    from exercise_motion_pkg import controlled_motion as motion

    current, names, points = _artifact_state_source_fit_payload('boundedMovementSelection')
    constraint = motion._prepare_source_projection_fit_constraints(
        current,
        current['frames'],
        names,
        points,
        np.zeros((len(points), len(names)), dtype=bool),
        motion.body_scale(points, names),
    )

    assert constraint['endpointPostureCoverage']['start']['available'] is True
    assert constraint['endpointPostureCoverage']['end']['available'] is True
    pelvis_index = names.index('pelvis')
    hip_midpoint = (points[0, names.index('left_hip')]
                    + points[0, names.index('right_hip')]) * .5
    assert np.linalg.norm(points[0, pelvis_index] - hip_midpoint) > .05
    assert all(
        observation['centerJointIndices'] == (pelvis_index,)
        for observation in constraint['endpointPostureObservations']
    )
    endpoint_rows = motion._source_endpoint_posture_fit_rows(points, constraint)
    assert np.max(np.abs(endpoint_rows), initial=0.) < 1e-6


def test_endpoint_posture_coverage_requires_distinct_source_timestamps():
    from exercise_motion_pkg import controlled_motion as motion

    current, names, points = _artifact_state_source_fit_payload('cycleSelection')
    source_frames = current['sourcePoseCameraReference']['sourcePose']['frames']
    start_time = source_frames[0]['sourceTimeSec']
    source_frames[1]['sourceTimeSec'] = start_time
    source_frames[2]['sourceTimeSec'] = start_time
    source_frames[1]['joints'] = dict(source_frames[0]['joints'])
    source_frames[2]['joints'] = dict(source_frames[0]['joints'])
    constraint = motion._prepare_source_projection_fit_constraints(
        current,
        current['frames'],
        names,
        points,
        np.zeros((len(points), len(names)), dtype=bool),
        motion.body_scale(points, names),
    )

    assert constraint['available'] is True
    assert constraint['endpointPostureCoverage']['start']['available'] is False
    assert constraint['endpointPostureCoverage']['start']['sourceSampleCount'] == 1
    assert constraint['endpointPostureCoverage']['end']['available'] is True


def test_selected_cycle_uses_adjacent_parent_pose_within_boundary_tolerance_only():
    from exercise_motion_pkg import controlled_motion as motion

    names, points = stance(36)
    current = payload(names, points)
    source_start = 1. / 30.
    for frame_index, frame in enumerate(current['frames']):
        source_time = source_start + frame['timeSec']
        frame['sourceFrameIndex'] = frame_index
        frame['sourceTimeSec'] = source_time
        frame['cycleSourceFrameIndex'] = frame_index
        frame['cycleSourceTimeSec'] = source_time
    current['loopCycleSelection'] = {
        'startFrame': 0,
        'stopFrameExclusive': len(points),
        'inputFrameCount': len(points),
        'sourceStartTimeSec': source_start,
        'sourceStopTimeSec': current['frames'][-1]['sourceTimeSec'] + 1. / current['fps'],
    }
    source_frames = []
    for source_time in np.arange(0., 1.6, 4. / 30.):
        frame_index = min(
            len(points) - 1,
            max(0, round((float(source_time) - source_start) * current['fps'])),
        )
        source_frames.append({
            'sourceTimeSec': float(source_time),
            'joints': {
                name: [float(point[0] * .4 + .5), float(point[1] * .4 + .5)]
                for name, point in zip(names, points[frame_index])
            },
            'jointConfidence': {name: .81 for name in names},
        })
    # Duplicate pose observations can occur when retained source chunks overlap.
    # They must not collapse the cadence used to decide whether the nearest
    # parent observation is close enough to cover the cycle boundary.
    source_frames = [dict(frame) for frame in source_frames for _ in range(4)]
    current['sourcePoseCameraReference'] = {
        'sourcePose': {
            'coordinateSpace': 'normalized_image_xy',
            'imageWidth': 1000,
            'imageHeight': 1000,
            'sourceTimeOriginSec': 0.,
            'frames': source_frames,
        },
        'camera': {
            'cameraRotation': np.eye(3).tolist(),
            'cameraImageTransform': [.4, 0., 0., 0., .5, .5],
            'bilateralAssignment': 'identity',
        },
    }

    constraint = motion._prepare_source_projection_fit_constraints(
        current,
        current['frames'],
        names,
        points,
        np.zeros((len(points), len(names)), dtype=bool),
        motion.body_scale(points, names),
    )

    assert constraint['available'] is True
    assert constraint['cycleBoundaryCoverage']['start']['available'] is True
    assert np.isclose(
        constraint['cycleBoundaryCoverage']['start']['offsetSeconds'], 1. / 30.,
    )
    assert np.isclose(
        constraint['cycleBoundaryCoverage']['start']['toleranceSeconds'], 2. / 30.,
    )
    assert constraint['endpointPostureCoverage']['start']['available'] is True
    assert constraint['boundaryEvidenceFrameCount'] == 1
    np.testing.assert_allclose(constraint['boundaryEvidenceSourceTimesSec'], [0.])
    outside_rows = [row for row in constraint['observations'] if row['outsideSelectedInterval']]
    assert outside_rows
    assert all(np.isclose(row['sourceTime'], -1. / 30.) for row in outside_rows)
    assert all('start' in row['cycleBoundaryRoles'] for row in outside_rows)


def test_selected_cycle_fit_stops_when_source_endpoint_coverage_is_incomplete(monkeypatch):
    from exercise_motion_pkg import controlled_motion as motion

    current, _, _ = _artifact_state_source_fit_payload('cycleSelection')
    source_frames = current['sourcePoseCameraReference']['sourcePose']['frames']
    current['sourcePoseCameraReference']['sourcePose']['frames'] = source_frames[3:]
    current['loopCycleSelection'] = {
        'startFrame': 0,
        'stopFrameExclusive': len(current['frames']),
        'inputFrameCount': len(current['frames']),
        'sourceStartTimeSec': current['frames'][0]['sourceTimeSec'],
        'sourceStopTimeSec': current['frames'][-1]['sourceTimeSec'] + 1. / current['fps'],
    }
    for frame_index, frame in enumerate(current['frames']):
        frame['cycleSourceFrameIndex'] = frame_index
        frame['cycleSourceTimeSec'] = frame['sourceTimeSec']

    def unexpected_solver_call(*args, **kwargs):
        raise AssertionError('fit solver must not run without selected-cycle endpoint evidence')

    monkeypatch.setattr(motion, 'solve_trajectory', unexpected_solver_call)
    result, report = motion.fit_controlled_motion(
        current,
        max_evaluations=1,
        timeout_seconds=10.,
    )

    assert result is current
    assert report['applied'] is False
    assert report['reason'] == 'selected_source_interval_source_evidence_incomplete'
    assert report['sourceProjectionConstraint']['available'] is True
    assert report['sourceProjectionConstraint']['endpointPostureCoverage']['start']['available'] is False
    assert report['sourceProjectionConstraint']['endpointPostureCoverage']['end']['available'] is True
    assert report['sourceIntervalFitCoverageGaps'] == [
        'source_endpoint_posture_start_unavailable',
        'source_cycle_boundary_start_unavailable',
    ]
    assert not motion.controlled_fit_processing_incomplete(report)


def test_selected_cycle_fit_stops_when_effective_boundary_rows_are_incomplete():
    from exercise_motion_pkg import controlled_motion as motion

    current, names, points = _artifact_state_source_fit_payload('cycleSelection')
    pinned = np.zeros((len(points), len(names)), dtype=bool)
    pinned[0, :] = True

    constraint = motion._prepare_source_projection_fit_constraints(
        current,
        current['frames'],
        names,
        points,
        pinned,
        motion.body_scale(points, names),
    )
    assert constraint['available'] is True
    assert constraint['cycleBoundaryCoverage']['start']['available'] is True
    assert constraint['cycleBoundaryCoverage']['start']['jointObservationCount'] >= 3
    assert constraint['cycleBoundaryCoverage']['start']['effectiveObservationCount'] == 0
    assert constraint['cycleBoundaryCoverage']['start']['effectiveAvailable'] is False
    assert constraint['endpointPostureCoverage']['start']['available'] is True
    assert motion._selected_interval_source_fit_coverage_gaps(current, constraint) == [
        'source_cycle_boundary_start_unavailable',
    ]


def test_artifact_selected_cycle_preserves_boundary_evidence_rejection(monkeypatch):
    from exercise_motion_pkg import controlled_motion as motion

    current, _, _ = _artifact_state_source_fit_payload('cycleSelection')
    assert 'loopCycleSelection' not in current

    prepare_constraints = motion._prepare_source_projection_fit_constraints

    def prepare_with_pinned_start(payload, frames, names, points, pinned, scale):
        pinned = pinned.copy()
        pinned[0, :] = True
        return prepare_constraints(payload, frames, names, points, pinned, scale)

    monkeypatch.setattr(
        motion, '_prepare_source_projection_fit_constraints', prepare_with_pinned_start,
    )

    def unexpected_solver_call(*args, **kwargs):
        raise AssertionError('fit solver must not run without effective cycle-boundary rows')

    monkeypatch.setattr(motion, 'solve_trajectory', unexpected_solver_call)
    result, report = motion.fit_controlled_motion(
        current,
        max_evaluations=1,
        timeout_seconds=10.,
    )

    assert result is current
    assert report['applied'] is False
    assert report['reason'] == 'selected_source_interval_source_evidence_incomplete'
    assert report['sourceProjectionConstraint']['cycleBoundaryCoverage']['start']['available'] is True
    assert report['sourceProjectionConstraint']['cycleBoundaryCoverage']['start']['effectiveObservationCount'] == 0
    assert report['sourceProjectionConstraint']['cycleBoundaryCoverage']['start']['effectiveAvailable'] is False
    assert report['sourceIntervalFitCoverageGaps'] == ['source_cycle_boundary_start_unavailable']


def test_pinned_source_confirmed_foot_anchor_projects_with_low_trust_for_unknown_confidence():
    from exercise_motion_pkg import controlled_motion as motion

    names, points = stance(12)
    current = payload(names, points)
    source_origin = 21.0
    source_frames = []
    for frame_index, source_frame in enumerate(current['frames']):
        source_timestamp = source_origin + source_frame['timeSec']
        joints = {}
        for name, point in zip(names, points[frame_index]):
            image_x = float(point[0] * .4 + .5)
            if name == 'left_foot':
                image_x += .02
            joints[name] = [image_x, float(point[1] * .4 + .5)]
        source_frames.append({
            'sourceTimeSec': source_timestamp,
            'joints': joints,
            # The ankle entry is deliberately absent: missing confidence must
            # stay low-trust while an explicit source confidence remains usable.
            'jointConfidence': {'left_foot': 1.0},
        })
        source_frame['sourceTimeSec'] = source_timestamp
    current['sourceFootSupportEvidence'] = {'contacts': [{
        'jointName': 'left_foot',
        'contactState': 'full_sole',
        'contactMotion': 'stationary',
        'startRatio': 0.,
        'endRatio': 1.,
        'confidence': .8,
        'anchorGroupId': 'left:toe:1',
        'ankleAnchorGroupId': 'left:ankle:1',
    }]}
    current['sourcePoseCameraReference'] = {
        'sourcePose': {
            'coordinateSpace': 'normalized_image_xy',
            'imageWidth': 1000,
            'imageHeight': 1000,
            'sourceTimeOriginSec': source_origin,
            'frames': source_frames,
        },
        'camera': {
            'cameraRotation': np.eye(3).tolist(),
            'cameraImageTransform': [.4, 0., 0., 0., .5, .5],
            'bilateralAssignment': 'identity',
        },
    }

    pinned = motion.contact_mask(current, names, len(points))
    assert pinned[:, names.index('left_foot')].all()
    assert pinned[:, names.index('left_ankle')].all()
    constraint = motion._prepare_source_projection_fit_constraints(
        current, current['frames'], names, points, pinned, motion.body_scale(points, names),
    )
    assert constraint['available']
    anchor_rows = [row for row in constraint['observations']
                   if row['sharedAnchorGroup'] is not None]
    foot = next(row for row in anchor_rows
                if row['jointIndex'] == names.index('left_foot'))
    ankle = next(row for row in anchor_rows
                 if row['jointIndex'] == names.index('left_ankle'))
    assert len(anchor_rows) >= 2 * len(points)
    assert foot['confidenceWeight'] > ankle['confidenceWeight']
    assert np.isclose(ankle['confidenceWeight'], np.sqrt(.1))
    rig = FixedRig(points, names)
    fit_jacobian = motion._source_projection_fit_jacobian(
        constraint,
        frame_count=len(points),
        joint_count=len(names),
        rig=rig,
        coordinates=rig.initial,
    )
    foot_observation_index = next(
        index for index, row in enumerate(constraint['observations']) if row is foot)
    assert fit_jacobian[foot_observation_index * 2:(foot_observation_index + 1) * 2].nnz > 0

    corrected, adjustment = motion._align_shared_contact_anchors_to_source_projection(
        constraint, pinned, points.copy(),
    )
    assert adjustment['adjustedGroupCount'] == 1
    assert adjustment['maximumShiftMeters'] > 0.
    assert adjustment['maximumShiftMeters'] < .05
    foot_delta = corrected[:, names.index('left_foot')] - points[:, names.index('left_foot')]
    ankle_delta = corrected[:, names.index('left_ankle')] - points[:, names.index('left_ankle')]
    np.testing.assert_allclose(foot_delta, ankle_delta, atol=1e-10)
    np.testing.assert_allclose(foot_delta, np.broadcast_to(foot_delta[0], foot_delta.shape), atol=1e-10)
    camera_depth = np.linalg.svd(constraint['projection'])[2][-1]
    assert abs(float(np.dot(foot_delta[0], camera_depth))) < 1e-10


@pytest.mark.parametrize('joint_name', ['left_wrist', 'left_foot'])
@pytest.mark.parametrize('explicit_surface_geometry', [False, True])
def test_confirmed_pinned_body_support_source_camera_rows_follow_support_authority(
    joint_name, explicit_surface_geometry,
):
    from exercise_motion_pkg import controlled_motion as motion

    names, points = stance(12)
    current = payload(names, points)
    source_origin = 21.0
    source_frames = []
    for frame_index, frame in enumerate(current['frames']):
        source_timestamp = source_origin + frame['timeSec']
        frame['sourceTimeSec'] = source_timestamp
        frame['cycleSourceFrameIndex'] = frame_index
        frame['cycleSourceTimeSec'] = source_timestamp
        source_frames.append({
            'sourceTimeSec': source_timestamp,
            'joints': {
                name: [float(point[0] * .4 + .5), float(point[1] * .4 + .5)]
                for name, point in zip(names, points[frame_index])
            },
            'jointConfidence': {name: .81 for name in names},
        })
    current['loopCycleSelection'] = {
        'startFrame': 0,
        'stopFrameExclusive': len(points),
        'sourceStartTimeSec': source_origin,
        'sourceStopTimeSec': source_origin + len(points) / current['fps'],
    }
    current['sourceFootSupportEvidence'] = {
        'bodySupport': {
            'required': True,
            'status': 'confirmed',
            'stationaryJoints': [joint_name],
            'coplanarGroups': (
                [{
                    'joints': [joint_name],
                    'normal': [0., 1., 0.],
                    'planeOffsetMeters': float(points[0, names.index(joint_name), 1]),
                }]
                if explicit_surface_geometry else []
            ),
        },
    }
    current['sourcePoseCameraReference'] = {
        'sourcePose': {
            'coordinateSpace': 'normalized_image_xy',
            'imageWidth': 1000,
            'imageHeight': 1000,
            'sourceTimeOriginSec': source_origin,
            'frames': source_frames,
        },
        'camera': {
            'cameraRotation': np.eye(3).tolist(),
            'cameraImageTransform': [.4, 0., 0., 0., .5, .5],
            'bilateralAssignment': 'identity',
        },
    }

    pinned = np.zeros((len(points), len(names)), dtype=bool)
    support_joint_index = names.index(joint_name)
    pinned[:, support_joint_index] = True
    constraint = motion._prepare_source_projection_fit_constraints(
        current, current['frames'], names, points, pinned, motion.body_scale(points, names),
    )
    support_observations = [
        row for row in constraint['observations'] if row['jointIndex'] == support_joint_index
    ]
    assert constraint['available']
    if explicit_surface_geometry:
        assert constraint['supportAnchorObservationCount'] == 0
        assert constraint['supportAnchorProjectionOmittedCount'] == len(points)
        assert support_observations == []
    else:
        assert constraint['supportAnchorObservationCount'] == len(points)
        assert constraint['supportAnchorProjectionOmittedCount'] == 0
        assert len(support_observations) == len(points)
        assert all(row['sharedAnchorGroup'] is None for row in support_observations)

    if not explicit_surface_geometry:
        baseline = motion._source_projection_fit_rows(points, constraint)
        shifted = points.copy()
        shifted[:, support_joint_index, 0] += .01
        moved_rows = motion._source_projection_fit_rows(shifted, constraint)
        row_indexes = [
            index for index, row in enumerate(constraint['observations'])
            if row['jointIndex'] == support_joint_index
        ]
        selected_rows = np.ravel([[index * 2, index * 2 + 1] for index in row_indexes])
        assert np.linalg.norm(moved_rows[selected_rows] - baseline[selected_rows]) > 0.

        rig = FixedRig(points, names)
        jacobian = motion._source_projection_fit_jacobian(
            constraint,
            frame_count=len(points),
            joint_count=len(names),
            rig=rig,
            coordinates=rig.initial,
        )
        assert jacobian[selected_rows].nnz > 0

    current['sourceFootSupportEvidence']['bodySupport']['status'] = 'unknown'
    unconfirmed = motion._prepare_source_projection_fit_constraints(
        current, current['frames'], names, points, pinned, motion.body_scale(points, names),
    )
    assert unconfirmed['supportAnchorObservationCount'] == 0
    assert unconfirmed['supportAnchorProjectionOmittedCount'] == 0
    assert not any(row['jointIndex'] == support_joint_index for row in unconfirmed['observations'])


def test_slow_solver_block_hands_unused_budget_to_polish(monkeypatch):
    from types import SimpleNamespace
    from exercise_motion_pkg import controlled_motion as motion
    names, points = stance(12)
    current = payload(names, points)
    current['loop'] = {'enabled': True}
    now = [0.]
    calls = []
    monkeypatch.setattr(motion, 'monotonic', lambda: now[0])
    def slow_block(residual, initial, pattern, max_evaluations, **solver_options):
        calls.append(now[0])
        residual(initial)
        now[0] += 40.
        return SimpleNamespace(x=initial, nfev=5, status=0)
    monkeypatch.setattr(motion, 'solve_trajectory', slow_block)
    _, report = motion._fit_controlled_motion(current, timeout_seconds=60.)
    assert calls == [0.]
    deferred = report['deferredOptimizerBlock']
    assert deferred['minimumUpdateSeconds'] > deferred['remainingSolveSeconds']
    assert report['optimizerTermination'] == 'solve_phase_budget'
    assert 40. + report['polishReserveRemainingSeconds'] < report['polishUntilSeconds'] <= 60.


def test_hybrid_jacobian_stops_probes_at_solve_deadline(monkeypatch):
    import pytest
    from types import SimpleNamespace
    from exercise_motion_pkg import controlled_motion as motion

    names, points = stance(12)
    current = payload(names, points)
    current['loop'] = {'enabled': True}
    clock = [0.]
    monkeypatch.setenv('EXERCISE_MOTION_HYBRID_JACOBIAN', '1')
    monkeypatch.setattr(motion, 'monotonic', lambda: clock[0])
    observed_timeout = []

    def expire_during_probe(residual, initial, pattern, max_evaluations, **solver_options):
        residual(initial)
        clock[0] = 44.8  # A 12-frame cyclic fit gives soft LS a 45-second fence.

        def advance_clock():
            clock[0] += .05
            return clock[0]

        monkeypatch.setattr(motion, 'monotonic', advance_clock)
        with pytest.raises(TimeoutError):
            solver_options['local_jacobian'](initial)
        observed_timeout.append(clock[0])
        monkeypatch.setattr(motion, 'monotonic', lambda: 0.)
        return SimpleNamespace(x=initial, nfev=1, status=1)

    monkeypatch.setattr(motion, 'solve_trajectory', expire_during_probe)
    motion._fit_controlled_motion(current, timeout_seconds=60.)
    assert observed_timeout and observed_timeout[0] >= 45.


def test_temporal_reference_is_unchanged_by_preview_noise(monkeypatch):
    from types import SimpleNamespace
    from exercise_motion_pkg import controlled_motion as motion
    names, reference = stance(12)
    reference[:, names.index('head'), 0] += .0002*np.sin(np.arange(12))
    monkeypatch.setattr(motion, 'solve_trajectory', lambda residual, initial, pattern, max_evaluations, **solver_options:
                        SimpleNamespace(x=initial, nfev=1, status=0))
    reports = []
    for noise in (.0001, .002):
        points = reference.copy()
        points[:, names.index('head'), 0] += noise*(-1.)**np.arange(12)
        current = payload(names, points)
        for frame, source in zip(current['frames'], reference):
            frame['controlledArticulationReferenceJoints'] = dict(zip(names, source.tolist()))
        _, report = fit_controlled_motion(current, timeout_seconds=10.)
        assert report['temporalReference'] == 'source_articulation_before_repairs'
        assert report['settlingReference'] == 'source_articulation_before_repairs'
        reports.append(report)
    expected = float(np.sqrt(np.mean(np.diff(reference, n=3, axis=0)**2)))
    assert reports[0]['jerkBefore'] == reports[1]['jerkBefore'] == expected
    assert reports[0]['settlingSpeedBefore'] == reports[1]['settlingSpeedBefore']


def test_anatomical_repair_seed_transports_correction_without_freezing_motion():
    from scipy.spatial.transform import Rotation
    from exercise_motion_pkg.anatomical_repair import _transport_repair_rotation

    previous_observed = Rotation.from_euler('xyz', [0.2, -0.1, 0.05]).as_rotvec()
    source_step = Rotation.from_euler('xyz', [0.05, 0.12, -0.03])
    current_observed = (
        Rotation.from_rotvec(previous_observed) * source_step
    ).as_rotvec()
    repair_correction = Rotation.from_euler('xyz', [-0.08, 0.04, 0.02])
    previous_repaired = (
        repair_correction * Rotation.from_rotvec(previous_observed)
    ).as_rotvec()

    current_seed = Rotation.from_rotvec(_transport_repair_rotation(
        previous_observed, previous_repaired, current_observed))
    previous_fixed = Rotation.from_rotvec(previous_repaired)

    np.testing.assert_allclose(
        (previous_fixed.inv() * current_seed).as_rotvec(),
        (Rotation.from_rotvec(previous_observed).inv()
         * Rotation.from_rotvec(current_observed)).as_rotvec(),
        atol=1e-12,
    )
    assert not np.allclose(previous_fixed.as_rotvec(), current_seed.as_rotvec())


def test_fit_commits_guarded_initializer_pose_before_optimizing(monkeypatch):
    import pytest
    from exercise_motion_pkg import anatomical_repair, controlled_motion as motion

    names, points = stance(12)
    verification_rig = FixedRig(points, names)
    guarded_poses = []
    def initialize(rig, observed, **kwargs):
        slot = rig.slots[names.index('neck')]
        rig.initial[:, slot + 2] += .8
        guarded = rig.decode(rig.initial)
        assert np.max(np.abs(guarded - rig.decode(rig.initial, project_socket=False))) > .01
        guarded_poses.append(guarded)
        return guarded, {'passed': True, 'applied': True, 'sourceViolations': []}
    monkeypatch.setattr(anatomical_repair, 'repair_rig_anatomy', initialize)
    class Captured(Exception):
        pass
    def inspect_initial(residual, initial, pattern, max_evaluations):
        coordinates = initial.reshape(len(points), -1)
        guarded = verification_rig.decode(coordinates)
        unguarded = verification_rig.decode(coordinates, project_socket=False)
        np.testing.assert_allclose(unguarded, guarded, atol=1e-12)
        # Root placement may change, but canonicalization preserves articulation.
        np.testing.assert_allclose(guarded - guarded[:, :1],
                                   guarded_poses[0] - guarded_poses[0][:, :1], atol=1e-12)
        raise Captured()
    monkeypatch.setattr(motion, 'solve_trajectory', inspect_initial)
    with pytest.raises(Captured):
        motion._fit_controlled_motion(payload(names, points), timeout_seconds=10.)


def test_supported_settling_baseline_uses_supported_reference_not_source():
    from exercise_motion_pkg.controlled_motion import (
        controlled_target, settling_hold_basis, weighted_settling_speed,
    )
    names, source = stance(24)
    supported = source.copy()
    # Intentional support rewrite with extra hold-interval motion.
    supported[:, :, 1] += .04
    t = np.linspace(0., 1., 24)
    quiet = (t > .3) & (t < .7)
    supported[quiet, names.index('left_wrist'), 0] += .015 * np.sin(np.linspace(0., np.pi, quiet.sum()))
    assert settling_hold_basis(source, supported, {'required': True}) is supported
    assert settling_hold_basis(source, supported, {}) is source
    assert float(np.sqrt(np.mean(np.diff(supported, n=3, axis=0)**2))) >= float(
        np.sqrt(np.mean(np.diff(source, n=3, axis=0)**2)))
    source_holds = controlled_target(source, names, 30.)[1]
    supported_holds = controlled_target(supported, names, 30.)[1]
    source_weights = np.minimum(source_holds[1:], source_holds[:-1])[:, :, None]
    supported_weights = np.minimum(supported_holds[1:], supported_holds[:-1])[:, :, None]
    source_limit = max(weighted_settling_speed(source, names, 30., source_weights) * 1.1, .003)
    supported_speed = weighted_settling_speed(supported, names, 30., supported_weights)
    mismatched = weighted_settling_speed(supported, names, 30., source_weights)
    # Pre-support quiet holds + post-support motion is the unreachable baseline.
    assert mismatched > source_limit
    assert supported_speed <= max(supported_speed * 1.1, .003)


def test_supported_joint_range_uses_articulation_metric_and_fit_residual(monkeypatch):
    from types import SimpleNamespace
    from exercise_motion_pkg import controlled_motion as motion
    from exercise_motion_pkg.controlled_motion import support_joint_range_preserved
    from exercise_motion_pkg.support_geometry import moving_support_articulations
    # Bench Dips signature: positional head under-range with articulations still OK.
    assert support_joint_range_preserved({'left_shoulder': 0.878})
    assert not support_joint_range_preserved({'left_elbow': 0.80, 'right_elbow': 0.819})
    names, points = stance(12)
    # Free-arm angular excursion that survives feet-only support constraints.
    theta = np.deg2rad(np.linspace(-40., 50., 12))
    for side in ('left', 'right'):
        elbow = names.index(f'{side}_elbow')
        wrist = names.index(f'{side}_wrist')
        shoulder = names.index(f'{side}_shoulder')
        points[:, elbow] = points[:, shoulder] + np.c_[np.cos(theta), np.sin(theta), np.zeros(12)] * .28
        points[:, wrist] = points[:, elbow] + [0., -.22, 0.]
    rig = FixedRig(points, names)
    points = rig.decode(rig.initial)
    feet = [f'{side}_{part}' for side in ('left', 'right') for part in ('ankle', 'foot')]
    floor = float(points[0, names.index('left_foot'), 1])
    current = payload(names, points)
    current['sourceFootSupportEvidence'] = {
        'bodySupport': {
            'required': True, 'status': 'confirmed', 'stationaryJoints': feet,
            'coplanarGroups': [{'joints': feet, 'normal': [0., 1., 0.],
                               'planeOffsetMeters': floor}],
        }}
    tracks = moving_support_articulations(
        points, names, current['sourceFootSupportEvidence']['bodySupport'])
    assert tracks, 'fixture needs moving free-chain articulations'
    residual_widths = []

    def solve(residual, initial, pattern, max_evaluations):
        errors = residual(initial)
        assert pattern.shape == (len(errors), len(initial))
        assert np.isfinite(errors).all()
        residual_widths.append(len(errors))
        n_tracks = len(tracks)
        assert len(errors) >= n_tracks
        # Soft floor is .92 of source excursion; identity must clear it with margin.
        assert np.all(errors[-n_tracks:] < 1.), errors[-n_tracks:]
        return SimpleNamespace(x=initial, nfev=1, status=0)

    monkeypatch.setattr(motion, 'solve_trajectory', solve)
    _, report = motion.fit_controlled_motion(current, timeout_seconds=45.)
    assert residual_widths and residual_widths[0] > 0
    assert 'supportArticulationRangeRatios' in report, report
    assert len(report['supportArticulationRangeRatios']) == len(tracks)
    assert report['checks']['jointRange'], report


def test_project_contact_root_translation_clears_uniform_plant_offset():
    from exercise_motion_pkg.controlled_motion import (
        FixedRig, project_contact_root_translation)
    names, points = stance(8)
    rig = FixedRig(points, names)
    coords = rig.initial.copy()
    foot = names.index('left_foot')
    pinned = np.zeros((len(points), len(names)), dtype=bool)
    pinned[:, foot] = True
    targets = points.copy()
    # Decode offset: shift world targets up so contacts need +2mm root Y.
    targets[:, foot, 1] += 0.002
    projected = project_contact_root_translation(coords, rig, pinned, targets)
    result = FixedRig(points, names)
    result.initial[:] = projected
    decoded = result.decode(projected)
    err = float(np.max(np.linalg.norm((decoded - targets)[pinned], axis=-1)))
    assert err < 1e-6, err


def test_supported_geometry_ready_skips_when_plants_and_grip_hold():
    from exercise_motion_pkg.controlled_motion import (
        supported_geometry_ready_for_skip_soft_solve)
    names, points = stance(8)
    equipment = {'handRelationship': 'none'}
    payload = {'sourceFootSupportEvidence': {'bodySupport': {'required': False}}}
    assert supported_geometry_ready_for_skip_soft_solve(
        anchored=True, playback_anchored=False, floor_clear=True,
        points=points, names=names, equipment=equipment, payload=payload,
        support_strategy='plant_projection')
    assert not supported_geometry_ready_for_skip_soft_solve(
        anchored=True, playback_anchored=True, floor_clear=True,
        points=points, names=names, equipment=equipment, payload=payload,
        support_strategy='supported_motion_ls')
    assert not supported_geometry_ready_for_skip_soft_solve(
        anchored=False, playback_anchored=True, floor_clear=True,
        points=points, names=names, equipment=equipment, payload=payload,
        support_strategy='plant_projection')
    supported_payload = {'sourceFootSupportEvidence': {'bodySupport': {
        'required': True, 'status': 'confirmed', 'stationaryJoints': ['pelvis']}}}
    assert not supported_geometry_ready_for_skip_soft_solve(
        anchored=True, playback_anchored=True, floor_clear=True,
        points=points, names=names, equipment=equipment, payload=supported_payload,
        support_strategy='plant_projection', playback_support_geometry_passed=False)
    payload.update(fps=30., loop={'enabled': True})
    stationary = np.repeat(points[:1], len(points), axis=0)
    assert supported_geometry_ready_for_skip_soft_solve(
        anchored=True, playback_anchored=True, floor_clear=True,
        points=stationary, names=names, equipment=equipment, payload=payload,
        support_strategy='plant_projection')
    stationary[-1, names.index('left_hand'), 0] += .03
    assert not supported_geometry_ready_for_skip_soft_solve(
        anchored=True, playback_anchored=True, floor_clear=True,
        points=stationary, names=names, equipment=equipment, payload=payload,
        support_strategy='plant_projection')


def test_temporal_free_smooth_leaves_plant_chain_rotations():
    from exercise_motion_pkg.controlled_motion import (
        FixedRig, temporal_free_coordinate_smooth, _plant_chain_slots)
    names, points = stance(16)
    points = points.copy()
    # High-frequency free-chain noise on the chest slot.
    rig = FixedRig(points, names)
    coords = rig.initial.copy()
    chest = names.index('chest') if 'chest' in names else names.index('spine3')
    hand = names.index('left_hand')
    coords[:, rig.slots[chest]:rig.slots[chest] + 3] += (
        0.02 * np.sin(np.linspace(0, 12 * np.pi, len(coords)))[:, None])
    coords[:, rig.slots[hand]:rig.slots[hand] + 3] += (
        0.03 * np.sin(np.linspace(0, 18 * np.pi, len(coords)))[:, None])
    pinned = np.zeros((len(coords), len(names)), dtype=bool)
    for foot in ('left_foot', 'right_foot'):
        pinned[:, names.index(foot)] = True
    before = coords.copy()
    after = temporal_free_coordinate_smooth(
        coords, rig, pinned, cyclic=True, sigma=1.5)
    plant_chain = set(_plant_chain_slots(rig, pinned))
    for joint in plant_chain:
        start = rig.slots[joint]
        assert np.allclose(after[:, start:start + 3], before[:, start:start + 3])
    assert not np.allclose(
        after[:, rig.slots[hand]:rig.slots[hand] + 3],
        before[:, rig.slots[hand]:rig.slots[hand] + 3])


def test_polish_free_temporal_restores_physical_after_torso_smooth():
    from exercise_motion_pkg.controlled_motion import (
        FixedRig, polish_free_temporal_preserving_anatomy)
    from exercise_motion_pkg.physical_validation import validate_physical_motion
    names, points = stance(24)
    points = points.copy()
    # Inject high-frequency spine noise that free-smooth would otherwise leave
    # as anatomy_torso_bend until repair runs.
    spine = names.index('spine1')
    points[:, spine] += (
        0.01 * np.sin(np.linspace(0, 20 * np.pi, len(points)))[:, None]
        * np.array([1., 0., 0.]))
    rig = FixedRig(points, names)
    pinned = np.zeros((len(points), len(names)), dtype=bool)
    for foot in ('left_foot', 'right_foot'):
        if foot in names:
            pinned[:, names.index(foot)] = True
    targets = rig.decode(rig.initial)
    polished = polish_free_temporal_preserving_anatomy(
        rig.initial, rig, pinned, targets, cyclic=True, sigma=1.25)
    world = rig.decode(polished)
    assert validate_physical_motion(world, names, fps=30.)['passed']


def test_temporal_anatomy_polish_preserves_caller_deadline(monkeypatch):
    from exercise_motion_pkg import controlled_motion as motion
    from exercise_motion_pkg import anatomical_repair

    names, points = stance(4)
    rig = motion.FixedRig(points, names)
    pinned = np.ones((len(points), len(names)), dtype=bool)
    targets = rig.decode(rig.initial)
    deadlines = []
    monkeypatch.setattr(motion, 'monotonic', lambda: 10.)
    monkeypatch.setattr(motion, 'temporal_free_coordinate_smooth',
                        lambda coordinates, *args, **kwargs: coordinates + 0.001)
    monkeypatch.setattr(anatomical_repair, 'repair_rig_anatomy',
                        lambda *args, **kwargs: (None, {'passed': True}))
    monkeypatch.setattr(motion, '_playback_contact_sample_error',
                        lambda *args, **kwargs: 1.)
    monkeypatch.setattr(motion, '_playback_failing_intervals',
                        lambda *args, **kwargs: [0])

    def capture_deadline(coordinates, *args, deadline=None, **kwargs):
        deadlines.append((deadline, kwargs))
        return coordinates

    for name in ('project_contact_plant_coordinates',
                 'project_interval_playback_plants',
                 'repair_playback_velocity_continuity'):
        monkeypatch.setattr(motion, name, capture_deadline)
    motion.polish_free_temporal_preserving_anatomy(
        rig.initial, rig, pinned, targets, cyclic=True, sigma=1., deadline=9.,
        spike_reference=points, fps=60.)
    assert [deadline for deadline, _ in deadlines] == [9., 9., 9.]
    assert all(kwargs['spike_reference'] is points for _, kwargs in deadlines[1:])
    assert deadlines[2][1]['fps'] == 60.


def test_rigid_pair_grip_projection_collapses_spacing_variance():
    from exercise_motion_pkg.controlled_motion import (
        FixedRig, project_rigid_pair_grip_coordinates)
    from exercise_motion_pkg.equipment_constraints import validate_grip
    names, points = stance(12)
    # Stretch one hand outward so rigid_pair fails, then project back.
    left, right = names.index('left_hand'), names.index('right_hand')
    points = points.copy()
    points[3:8, left] += [0.12, 0.0, 0.0]
    points[3:8, right] -= [0.08, 0.0, 0.0]
    rig = FixedRig(points, names)
    decoded = rig.decode(rig.initial)
    spacing = np.linalg.norm(decoded[:, left] - decoded[:, right], axis=-1)
    equipment = {
        'handRelationship': 'rigid_pair', 'available': True,
        'endpointPair': ['left_hand', 'right_hand'],
        'distanceMeters': float(np.median(spacing)),
        'distanceSource': 'robust_reconstruction_estimate',
        'toleranceMeters': max(0.005, 0.02 * float(np.median(spacing))),
    }
    before = validate_grip(decoded, names, equipment)
    assert not before['passed'], before
    shoulder_slots = [
        rig.slots[names.index(name)]
        for name in ('left_shoulder', 'right_shoulder')
        if names.index(name) in rig.slots
    ]
    projected = project_rigid_pair_grip_coordinates(
        rig.initial, rig, names, equipment, max_nfev=30)
    after = validate_grip(rig.decode(projected), names, equipment)
    assert after['passed'], (before, after)
    assert after['maximumSpacingErrorMeters'] < before['maximumSpacingErrorMeters']
    for slot in shoulder_slots:
        np.testing.assert_allclose(projected[:, slot:slot + 3], rig.initial[:, slot:slot + 3])


def test_playback_rigid_pair_grip_closes_mid_sample_spacing_bow():
    """Keyframe grip can pass while hermite mids miss rigid_pair tolerance."""
    from exercise_motion_pkg.controlled_motion import (
        FixedRig, project_rigid_pair_grip_coordinates, project_playback_rigid_pair_grip,
        _playback_grip_sample_error)
    from exercise_motion_pkg.equipment_constraints import validate_grip
    names, points = stance(24)
    left, right = names.index('left_hand'), names.index('right_hand')
    wrist = names.index('left_wrist')
    points = points.copy()
    points[1:-1, left] += [0.18, 0.0, 0.04]
    points[1:-1, right] -= [0.12, 0.0, 0.04]
    rig = FixedRig(points, names)
    # After FK encode, twist mid-frame wrists so hermite mids bow even once
    # keyframe spacing is projected back onto the rigid_pair target.
    shifted = rig.initial.copy()
    slot = rig.slots[wrist]
    shifted[1:-1, slot:slot + 3] += [0.35, 0.15, 0.08]
    decoded = rig.decode(shifted)
    spacing = np.linalg.norm(decoded[:, left] - decoded[:, right], axis=-1)
    equipment = {
        'handRelationship': 'rigid_pair', 'available': True,
        'endpointPair': ['left_hand', 'right_hand'],
        'distanceMeters': float(np.median(spacing[[0, -1]])),
        'distanceSource': 'robust_reconstruction_estimate',
        'toleranceMeters': 0.008,
    }
    keyed = project_rigid_pair_grip_coordinates(
        shifted, rig, names, equipment, max_nfev=40)
    assert validate_grip(rig.decode(keyed), names, equipment)['passed']
    before = _playback_grip_sample_error(keyed, rig, names, equipment, cyclic=False)
    assert before > equipment['toleranceMeters'], before
    planted = project_playback_rigid_pair_grip(
        keyed, rig, names, equipment, cyclic=False, max_nfev=24)
    after = _playback_grip_sample_error(planted, rig, names, equipment, cyclic=False)
    assert after <= equipment['toleranceMeters'], (before, after)
    assert validate_grip(rig.decode(planted), names, equipment)['passed']


def test_playback_grip_repair_skips_plant_projection_when_contacts_pass(monkeypatch):
    from exercise_motion_pkg import controlled_motion as motion

    class IdentityRig:
        @staticmethod
        def decode(coordinates):
            return np.asarray(coordinates, dtype=float)

    rig = IdentityRig()
    coordinates = np.zeros((4, 2, 3), dtype=float)
    targets = np.zeros_like(coordinates)
    pinned = np.ones((4, 2), dtype=bool)
    monkeypatch.setattr(
        motion, '_playback_contact_sample_error',
        lambda *_args, **_kwargs: 0.000863,
    )

    # The stored contact gate is 0.5mm and production playback allows 3mm.
    # A valid grip correction must not trigger a plant solve that can disturb
    # already-valid support geometry.
    assert not motion.playback_contact_repair_needed(
        coordinates, rig, pinned, targets, cyclic=False)

    targets[2, 1, 0] = motion.SUPPORT_REFERENCE_CONTACT_LIMIT_METERS * 1.1
    assert motion.playback_contact_repair_needed(
        coordinates, rig, pinned, targets, cyclic=False)

    targets.fill(0.)
    monkeypatch.setattr(
        motion, '_playback_contact_sample_error',
        lambda *_args, **_kwargs: motion.PLAYBACK_CONTACT_LIMIT_METERS,
    )
    assert motion.playback_contact_repair_needed(
        coordinates, rig, pinned, targets, cyclic=False)


def test_velocity_continuity_repair_replants_under_playback_gate(monkeypatch):
    """Smooth clears C1 jumps but lifts plants; repair must restore the 0.5 mm gate.

    When the jump already clears, repair must not smooth (that would reopen plants).
    """
    from exercise_motion_pkg import rig_interpolation as ri
    from exercise_motion_pkg.controlled_motion import (
        FixedRig, project_contact_plant_coordinates, project_interval_playback_plants,
        repair_playback_velocity_continuity, _playback_contact_sample_error,
        _sampling_payload)
    from exercise_motion_pkg.physical_validation import body_scale
    from exercise_motion_pkg.rig_playback import (
        PLAYBACK_CONTACT_LIMIT_METERS, rig_contact_targets, sample_rig)
    names, points = stance(32)
    points = points.copy()
    # Bow mid-frame ankle DOFs so keyframe plants hold while hermite mids miss.
    rig = FixedRig(points, names)
    ankle = rig.slots[names.index('left_ankle')]
    feet = [names.index('left_foot'), names.index('right_foot')]
    pinned = np.zeros((len(points), len(names)), dtype=bool)
    pinned[:, feet] = True
    targets, _ = rig_contact_targets(rig.decode(rig.initial), names, pinned, rig.offsets)
    bowed = rig.initial.copy()
    bowed[1:-1, ankle:ankle + 3] += [0.15, 0.0, 0.05]
    keyed = project_contact_plant_coordinates(
        bowed, rig, pinned, targets, max_nfev=40, freeze_root=True)
    mid = project_interval_playback_plants(
        keyed, rig, pinned, targets, cyclic=False, max_nfev=20, spike_reference=points)
    play_mid = _playback_contact_sample_error(mid, rig, pinned, targets, cyclic=False)
    assert play_mid < PLAYBACK_CONTACT_LIMIT_METERS, play_mid

    # Already continuous: must keep plants (no destructive smooth).
    kept = repair_playback_velocity_continuity(
        mid, rig, pinned, targets, cyclic=False, sigma=0.85, spike_reference=points)
    assert np.allclose(kept, mid)
    assert _playback_contact_sample_error(
        kept, rig, pinned, targets, cyclic=False) < PLAYBACK_CONTACT_LIMIT_METERS

    # Force the smooth path once; replant must recover under the playback gate.
    real_jump = ri.frame_boundary_velocity_jump
    state = {'forced': True}

    def jump_with_force(sampler, knots, fps):
        value = real_jump(sampler, knots, fps)
        if state['forced']:
            state['forced'] = False
            return max(value, 1.0)
        return value

    monkeypatch.setattr(ri, 'frame_boundary_velocity_jump', jump_with_force)
    repaired = repair_playback_velocity_continuity(
        mid, rig, pinned, targets, cyclic=False, sigma=0.85, spike_reference=points)
    assert not np.allclose(repaired, mid)
    play = _playback_contact_sample_error(repaired, rig, pinned, targets, cyclic=False)
    assert play < PLAYBACK_CONTACT_LIMIT_METERS, play
    payload = _sampling_payload(rig, repaired)
    knots = np.arange(1, len(repaired) - 1)
    jump = real_jump(lambda cursors: sample_rig(payload, cursors, wrap=False), knots, 30.)
    assert jump <= 0.001 * body_scale(rig.decode(repaired), names) * 1.05
    from exercise_motion_pkg.controlled_motion import relative_motion_quality
    repaired_points = rig.decode(repaired)
    assert not relative_motion_quality(
        repaired_points, points, names, 30., spike_reference=points)['introducedSpikes']['severe']


def test_normal_fit_routes_velocity_only_playback_miss_to_bounded_path_repair():
    from exercise_motion_pkg import controlled_motion as motion

    report = {
        'applied': False,
        'checks': {'jerk': False, 'playback': False},
        'maximumContactErrorMeters': 0.000072,
        'playback': {
            'passed': False,
            'maximumContactErrorMeters': 0.000186,
            'velocityContinuous': False,
            'equipment': {'required': True, 'passed': True},
            'physicalReasons': [],
        },
    }
    assert motion.playback_path_repair_eligible(report, skip_hard_only=False)

    report['playback']['physicalReasons'] = ['floor_penetration']
    assert not motion.playback_path_repair_eligible(report, skip_hard_only=False)
    assert motion.playback_path_repair_eligible(report, skip_hard_only=True)

    report['playback']['physicalReasons'] = []
    report['maximumContactErrorMeters'] = 0.0006
    assert not motion.playback_path_repair_eligible(report, skip_hard_only=False)


def test_normal_fit_runs_velocity_path_repair_after_soft_solve(monkeypatch):
    from types import SimpleNamespace

    from exercise_motion_pkg import controlled_motion as motion, rig_playback

    names, points = stance(12)
    current = payload(names, points)
    current['loop'] = {'enabled': True}
    monkeypatch.setattr(
        motion, 'supported_geometry_ready_for_skip_soft_solve', lambda **_kwargs: False)
    monkeypatch.setattr(
        motion, 'solve_trajectory',
        lambda residual, initial, pattern, max_evaluations, **_kwargs:
            SimpleNamespace(x=initial, nfev=1, status=1),
    )
    repair_state = {'called': False}
    real_playback_validation = rig_playback.validate_rig_playback

    def playback_with_velocity_near_miss(candidate):
        report = real_playback_validation(candidate)
        if not repair_state['called']:
            report = dict(report, passed=False, velocityContinuous=False)
        return report

    def clear_velocity_near_miss(coordinates, *_args, **_kwargs):
        repair_state['called'] = True
        return coordinates.copy()

    monkeypatch.setattr(
        rig_playback, 'validate_rig_playback', playback_with_velocity_near_miss)
    monkeypatch.setattr(
        motion, 'repair_playback_velocity_continuity', clear_velocity_near_miss)

    result, report = motion._fit_controlled_motion(
        current, timeout_seconds=10.)

    assert repair_state['called'], {
        'failedChecks': motion.failed_check_names(report.get('checks')),
        'reason': report.get('reason'),
        'termination': report.get('termination'),
        'refinement': report.get('boundedRefinement'),
        'skippedSoftSolve': report.get('skippedSoftSolve'),
        'playback': report.get('playback'),
    }
    assert report['applied'], report
    assert report['boundedRefinement']['playbackPathRepair'] is True
    assert report['boundedRefinement']['playbackPathRepairKept'] is True
    assert report['boundedRefinement']['playbackPathRepairAttempts'][-1]['retained'] is True
    assert result.get('fixedRig')


def test_smooth_root_translation_reduces_second_difference():
    from exercise_motion_pkg.controlled_motion import (
        smooth_root_translation_coordinates, project_root_continuity_coordinates)
    from exercise_motion_pkg.motion_placement import root_motion_quality
    coords = np.zeros((20, 6), dtype=float)
    coords[:, 0] = np.linspace(0, 0.2, 20)
    coords[10, 0] += 0.08  # spike
    before = root_motion_quality(coords[:, :3], 30., 0.8)
    assert not before['passed']
    smoothed = smooth_root_translation_coordinates(coords, 30., scale=0.8)
    after = root_motion_quality(smoothed[:, :3], 30., 0.8)
    assert after['maximumSecondDifferenceMetersAt30Hz'] < before['maximumSecondDifferenceMetersAt30Hz']
    assert after['passed']
    projected = project_root_continuity_coordinates(coords, 30., 0.8)
    assert root_motion_quality(projected[:, :3], 30., 0.8)['passed']


def test_polish_stages_order_contact_before_temporal_before_seam():
    from exercise_motion_pkg.controlled_motion import (
        polish_stage_for_failures, polishable_near_miss,
        prioritize_fit_before_broad_temporal_smoothing,
        stage_fit_refinement_budget, timed_out_stage_c_fit_is_stalled)
    assert polish_stage_for_failures(['equipment', 'loopSeam']) == 'A'
    assert polish_stage_for_failures(['loopSeam', 'jerk']) == 'C'
    assert polish_stage_for_failures(['jerk', 'jointShake']) == 'C'
    assert polish_stage_for_failures(['rootContinuity', 'loopSeam']) == 'C'
    assert polish_stage_for_failures(['motionDiscontinuity']) == 'C'
    assert polish_stage_for_failures(['loopSeam']) == 'B'
    assert polish_stage_for_failures(['playback']) == 'C'
    assert polishable_near_miss(['contacts', 'equipment'])
    assert polishable_near_miss(['loopSeam'])
    assert polishable_near_miss(['rootContinuity', 'settling'])
    assert not polishable_near_miss(['anatomy', 'contacts'])
    assert prioritize_fit_before_broad_temporal_smoothing(
        ['jerk'], playback_passed=True, contact_error_meters=0.0002)
    assert not prioritize_fit_before_broad_temporal_smoothing(
        ['jerk', 'settling'], playback_passed=True, contact_error_meters=0.0002)
    assert not prioritize_fit_before_broad_temporal_smoothing(
        ['jerk'], playback_passed=False, contact_error_meters=0.0002)
    assert not prioritize_fit_before_broad_temporal_smoothing(
        ['jerk'], playback_passed=True, contact_error_meters=0.0005)
    assert prioritize_fit_before_broad_temporal_smoothing(
        ['jerk', 'playback'], playback_passed=False,
        contact_error_meters=0.0002, playback_path_repair_attempted=True)
    assert not prioritize_fit_before_broad_temporal_smoothing(
        ['jerk', 'playback'], playback_passed=False,
        contact_error_meters=0.0002, playback_path_repair_attempted=False)
    assert not prioritize_fit_before_broad_temporal_smoothing(
        ['jerk', 'playback'], playback_passed=False,
        contact_error_meters=0.0005, playback_path_repair_attempted=True)
    assert stage_fit_refinement_budget(
        20., stage='C', minimum_update_seconds=10.8, prioritize_fit=True) is None
    assert stage_fit_refinement_budget(
        30., stage='C', minimum_update_seconds=10.8, prioritize_fit=True) == 22.1
    assert stage_fit_refinement_budget(
        10., stage='C', minimum_update_seconds=10.8, prioritize_fit=True) is None
    assert stage_fit_refinement_budget(
        20., stage='B', minimum_update_seconds=10.8, prioritize_fit=True) == 7.0
    assert not timed_out_stage_c_fit_is_stalled({'jerk', 'loopSeam'}, True)
    assert not timed_out_stage_c_fit_is_stalled({'rootContinuity'}, True)
    assert timed_out_stage_c_fit_is_stalled({'jointShake', 'settling'}, True)
    assert not timed_out_stage_c_fit_is_stalled({'jointShake'}, False)


def test_repair_motion_discontinuity_clears_swing_foot_velocity_spike():
    from exercise_motion_pkg.controlled_motion import (
        FixedRig, polish_worsened_jerk, repair_motion_discontinuity_coordinates,
        smooth_extremity_coordinates)
    from exercise_motion_pkg.temporal_quality import track_discontinuity_metrics
    names, points = stance(48)
    # Smooth swing of the free right leg, then a one-frame world snap matching
    # retained reverse-lunge ~0.2 body-ratio extremity events.
    foot = names.index('right_foot')
    ankle = names.index('right_ankle')
    knee = names.index('right_knee')
    phase = np.linspace(0., np.pi, len(points))
    points[:, foot, 2] += 0.12 * np.sin(phase)
    points[:, ankle, 2] += 0.10 * np.sin(phase)
    points[:, knee, 2] += 0.05 * np.sin(phase)
    points[24, foot] += (0., 0., 0.35)
    points[24, ankle] += (0., 0., 0.30)
    points[24, knee] += (0., 0., 0.15)
    rig = FixedRig(points, names)
    coords = rig.initial.copy()
    decoded = rig.decode(coords)
    before = track_discontinuity_metrics(
        {name: decoded[:, j].tolist() for j, name in enumerate(names)},
        root_joint='pelvis', fps=30.)
    assert before['severe'], before
    mild = smooth_extremity_coordinates(coords, rig, names, cyclic=False, sigma=1.5)
    mild_points = rig.decode(mild)
    mild_metrics = track_discontinuity_metrics(
        {name: mild_points[:, j].tolist() for j, name in enumerate(names)},
        root_joint='pelvis', fps=30.)
    assert mild_metrics['severe'], mild_metrics
    repaired = repair_motion_discontinuity_coordinates(
        coords, rig, names, cyclic=False, fps=30., scale=0.8)
    after_points = rig.decode(repaired)
    after = track_discontinuity_metrics(
        {name: after_points[:, j].tolist() for j, name in enumerate(names)},
        root_joint='pelvis', fps=30.)
    assert not after['severe'], (mild_metrics, after)
    assert polish_worsened_jerk({'jerkAfter': 0.004}, 0.0008)
    assert not polish_worsened_jerk({'jerkAfter': 0.00081}, 0.0008)


def test_polish_reserve_scales_and_protects_stage_deadlines(monkeypatch):
    from exercise_motion_pkg import controlled_motion as motion
    assert motion.polish_reserve_seconds(120., cyclic=True) >= 12.
    assert motion.polish_reserve_seconds(120., cyclic=True) <= 15.
    assert motion.polish_reserve_seconds(10., cyclic=True) <= 4. + 1e-9
    assert motion.polish_reserve_seconds(120., cyclic=False) <= motion.polish_reserve_seconds(120., cyclic=True)
    now = [1000.]
    monkeypatch.setattr(motion, 'monotonic', lambda: now[0])
    # Pre-solve stages still use full outer mins; polish is carved at solve time.
    anatomy = motion._stage_deadline(1000., 120., fraction=0.35, minimum_seconds=75.)
    assert anatomy == 1000. + 75.
    now[0] = anatomy
    support = motion._stage_deadline(1000., 120., fraction=0.3, minimum_seconds=60.)
    # Capped by outer fit deadline (1000+120), not anatomy+60.
    assert support == 1000. + 120.


def test_fit_validation_reserve_leaves_time_for_repair_inside_outer_deadline():
    from exercise_motion_pkg import controlled_motion as motion
    assert motion.fit_validation_reserve_seconds(123, 120.) == 24.6
    assert motion.fit_validation_reserve_seconds(123, 10.) == 2.5
    assert motion.fit_validation_reserve_seconds(2000, 360.) == 25.
    assert motion.fit_validation_reserve_seconds(0, 120.) == 0.

    solve_deadline, solve_budget = motion.fit_soft_solve_deadline(
        fit_started=100., timeout_seconds=120., now=112.,
        nominal_solve_seconds=150., validation_reserve_seconds=24.6,
        post_validation_polish_seconds=15.,
    )
    assert solve_budget == 68.4
    assert solve_deadline == 180.4
    validation_deadline = min(solve_deadline + 24.6, 220. - 15.)
    post_validation_deadline = min(220., validation_deadline + 15.)
    assert validation_deadline <= 205.
    assert post_validation_deadline == 220.


def test_support_init_minimum_scales_past_flat_ninety_for_long_cycles():
    from exercise_motion_pkg.controlled_motion import (
        SUPPORT_INIT_COLD_EVALUATIONS,
        SUPPORT_INIT_MIN_SECONDS,
        SUPPORT_INIT_SECONDS_PER_FRAME_EVAL,
        SUPPORT_INIT_SOLVE_RESERVE_FRACTION,
        SUPPORT_INIT_SOLVE_RESERVE_MIN_SECONDS,
        _stage_deadline,
    )
    frames = 129
    timeout = 240.
    support_cost = (SUPPORT_INIT_SECONDS_PER_FRAME_EVAL
                    * float(frames) * float(SUPPORT_INIT_COLD_EVALUATIONS))
    solve_reserve = max(
        SUPPORT_INIT_SOLVE_RESERVE_MIN_SECONDS,
        SUPPORT_INIT_SOLVE_RESERVE_FRACTION * timeout,
    )
    support_min = max(SUPPORT_INIT_MIN_SECONDS, support_cost)
    support_min = min(
        support_min,
        max(SUPPORT_INIT_MIN_SECONDS, timeout - solve_reserve),
    )
    # Retained GM-length cold init (~146s) must not be clipped by a flat 90s cap.
    assert support_cost > 90.
    assert support_min > 90.
    assert support_min <= timeout - solve_reserve
    deadline = _stage_deadline(0., timeout, fraction=0.3, minimum_seconds=support_min)
    assert deadline >= support_min


def test_seam_nudges_preserve_planted_descendants_without_freezing_free_limbs():
    from exercise_motion_pkg.controlled_motion import (
        FixedRig, seam_boundary_coordinate_nudge, seam_velocity_neighbor_nudge)

    names, points = stance(12)
    rig = FixedRig(points, names)
    coordinates = rig.initial.copy()
    for name in ('pelvis', 'left_knee', 'left_shoulder'):
        slot = rig.slots[names.index(name)]
        coordinates[-1, slot] += .15
    pinned = np.zeros(points.shape[:2], dtype=bool)
    for name in ('left_ankle', 'right_ankle', 'left_foot', 'right_foot'):
        pinned[:, names.index(name)] = True
    baseline = rig.decode(coordinates)
    shoulder_slot = rig.slots[names.index('left_shoulder')]
    for nudge in (seam_boundary_coordinate_nudge, seam_velocity_neighbor_nudge):
        changed = nudge(coordinates, rig, pinned, strength=.8)
        np.testing.assert_allclose(rig.decode(changed)[pinned], baseline[pinned], atol=1e-12)
        assert not np.array_equal(
            changed[:, shoulder_slot:shoulder_slot + 3],
            coordinates[:, shoulder_slot:shoulder_slot + 3])


def test_seam_boundary_nudge_reduces_first_last_root_gap():
    from exercise_motion_pkg.controlled_motion import (
        FixedRig, seam_boundary_coordinate_nudge, close_loop_seam_coordinates,
        seam_velocity_neighbor_nudge, seam_playback_over_limit_score,
        project_loop_seam_coordinates, body_scale)
    from exercise_motion_pkg.loop_seam import seam_errors
    names, points = stance(12)
    points[-1, names.index('pelvis'), 0] += 0.04
    points[0, names.index('pelvis'), 0] -= 0.01
    # Asymmetric neighbors create a wrap velocity hitch.
    points[1, names.index('pelvis'), 0] += 0.02
    points[-2, names.index('pelvis'), 0] -= 0.02
    rig = FixedRig(points, names)
    pinned = np.zeros((12, len(names)), dtype=bool)
    scale = body_scale(points, names)
    before = seam_errors(rig.decode(rig.initial))[0]
    before_gap = float(np.linalg.norm(before[names.index('pelvis')]))
    before_score = seam_playback_over_limit_score(rig.decode(rig.initial), scale=scale, fps=30.)
    nudged = seam_boundary_coordinate_nudge(rig.initial, rig, pinned, strength=0.8)
    after = seam_errors(rig.decode(nudged))[0]
    after_gap = float(np.linalg.norm(after[names.index('pelvis')]))
    assert after_gap < before_gap
    velocity = seam_velocity_neighbor_nudge(nudged, rig, pinned, strength=0.8)
    velocity_score = seam_playback_over_limit_score(rig.decode(velocity), scale=scale, fps=30.)
    assert velocity_score <= before_score
    closed = close_loop_seam_coordinates(
        rig.initial, rig, pinned, scale=scale, fps=30., passes=6)
    closed_gap = float(np.linalg.norm(seam_errors(rig.decode(closed))[0][names.index('pelvis')]))
    closed_score = seam_playback_over_limit_score(rig.decode(closed), scale=scale, fps=30.)
    assert closed_gap < before_gap
    assert closed_score < before_score
    projected = project_loop_seam_coordinates(
        closed, rig, pinned, scale=scale, fps=30., max_nfev=40)
    projected_score = seam_playback_over_limit_score(
        rig.decode(projected), scale=scale, fps=30.)
    assert projected_score <= closed_score + 1e-9


def test_boundary_source_constraints_preserve_interpolation_and_fixed_endpoint_context():
    from exercise_motion_pkg import controlled_motion as motion

    points = np.arange(8 * 3 * 3, dtype=float).reshape(8, 3, 3) / 100.
    active = {'leftFrame': 0, 'rightFrame': 3, 'alpha': .3,
              'jointIndex': 0, 'sourcePoint': np.array([.1, .2]), 'confidenceWeight': .8}
    fixed = {**active, 'leftFrame': 3, 'rightFrame': 4, 'alpha': .4}
    constraint = {'available': True, 'projection': np.array([[1., 0., 0.], [0., 1., 0.]]),
                  'offset': np.array([.1, -.2]), 'normalization': 1., 'weight': 10.,
                  'observations': [active, fixed], 'endpointPostureObservations': [{
                      'jointIndex': 0, 'centerJointIndices': [1, 2],
                      'sourceDelta': np.array([.2, .4]), 'confidenceWeight': .7,
                      'fitLinks': [{**active, 'weight': .25}, {**fixed, 'weight': .75}]}]}
    compact, context = motion._boundary_source_fit_constraints(
        constraint, (0, 1, 6, 7), (0, 1, 6, 7))
    assert context == [0, 1, 3, 4, 6, 7]
    assert len(compact['observations']) == 1
    assert len(compact['endpointPostureObservations'][0]['fitLinks']) == 2
    for change in (0., .2):
        candidate = points.copy()
        candidate[0, 0] += change
        np.testing.assert_allclose(
            motion._source_projection_fit_rows(candidate[context], compact),
            motion._source_projection_fit_rows(candidate, constraint)[:2])
        np.testing.assert_allclose(
            motion._source_endpoint_posture_fit_rows(candidate[context], compact),
            motion._source_endpoint_posture_fit_rows(candidate, constraint))
    assert active['rightFrame'] == 3
    assert constraint['endpointPostureObservations'][0]['fitLinks'][1]['rightFrame'] == 4


def test_seam_projection_scores_grip_and_rejects_breaking_a_valid_pair(monkeypatch):
    from types import SimpleNamespace
    from exercise_motion_pkg import controlled_motion as motion
    from exercise_motion_pkg.equipment_constraints import calibrated_grip_constraint, validate_grip

    names, points = stance(4)
    rig = FixedRig(points, names)
    original = rig.initial.copy()
    equipment = calibrated_grip_constraint(
        {'equipmentConstraints': {'handRelationship': 'rigid_pair'}},
        rig.decode(original), names)
    pinned = np.zeros(points.shape[:2], dtype=bool)
    hand = names.index('left_hand')
    projection = np.array([[1., 0., 0.], [0., 0., 1.]])
    source = {'available': True, 'projection': projection, 'offset': np.zeros(2),
              'normalization': 1., 'weight': 10., 'observations': [{
                  'leftFrame': 0, 'rightFrame': 2, 'alpha': .5, 'jointIndex': hand,
                  'sourcePoint': projection @ rig.decode(original)[0, hand],
                  'confidenceWeight': 1.}]}

    def solve(residual, initial, *, jac, **kwargs):
        baseline = residual(initial)
        probe = initial.reshape(4, rig.width).copy()
        probe[:, rig.slots[names.index('left_wrist')]] += .6
        assert not validate_grip(rig.decode(probe), names, equipment)['passed']
        errors = residual(probe.ravel())
        np.testing.assert_allclose(baseline[-2:], 0., atol=1e-12)
        assert np.linalg.norm(errors[-2:]) > .01
        assert errors @ errors > baseline @ baseline
        return SimpleNamespace(x=probe.ravel())

    monkeypatch.setattr(motion, 'least_squares', solve)
    projected = motion.project_loop_seam_coordinates(
        original, rig, pinned, scale=motion.body_scale(points, names), fps=30.,
        equipment=equipment, source_projection_constraint=source)
    np.testing.assert_array_equal(projected, original)


def test_seam_projection_scores_anatomy_hidden_by_socket_guard(monkeypatch):
    from types import SimpleNamespace
    from exercise_motion_pkg import controlled_motion as motion
    names, points = stance(4)
    rig = FixedRig(points, names)
    pinned = np.zeros((4, len(names)), dtype=bool)
    original_structure = motion.anatomical_structure_residuals
    socket_errors = []
    def structure(candidate, *args, **kwargs):
        errors, labels = original_structure(candidate, *args, **kwargs)
        socket_errors.append(float(np.max(errors[:, labels.index('anatomy_socket_alignment:neck')])))
        return errors, labels
    monkeypatch.setattr(motion, 'anatomical_structure_residuals', structure)
    def solve(residual, initial, *, jac, **kwargs):
        baseline = residual(initial)
        assert jac(initial).shape == (len(baseline), len(initial))
        probe = initial.reshape(4, rig.width).copy()
        slot = rig.slots[names.index('neck')]
        probe[:, slot:slot + 3] = [0., 0., .3]
        socket_errors.clear()
        errors = residual(probe.ravel())
        assert socket_errors and max(socket_errors) > .1
        assert np.max(np.abs(errors)) > 1000.
        return SimpleNamespace(x=initial)
    monkeypatch.setattr(motion, 'least_squares', solve)
    motion.project_loop_seam_coordinates(
        rig.initial, rig, pinned, scale=motion.body_scale(points, names), fps=30.)


def test_open_seam_is_applied_when_only_loop_wrap_fails():
    """Seam-only leftovers ship the fitted body with an honest open wrap label."""
    from exercise_motion_pkg import controlled_motion as motion
    checks = {name: True for name in motion.REQUIRED_FIT_CHECKS}
    checks['loopSeam'] = False
    checks['playback'] = True
    failed = {name for name, passed in checks.items() if not passed}
    assert failed == {'loopSeam'}
    assert failed <= {'loopSeam', 'playback'}


def test_seam_only_fit_reaches_bounded_projection(monkeypatch):
    import pytest
    from exercise_motion_pkg import controlled_motion as motion, rig_playback
    names, points = stance(12)
    current = payload(names, points)
    current['loop'] = {'enabled': True}
    original = rig_playback.validate_rig_playback

    def open_wrap(candidate, **kwargs):
        result = original(candidate, **kwargs)
        if candidate.get('loop', {}).get('enabled'):
            result.update(seamContinuous=False, seamVelocityMismatchMetersPerSecond=.3)
        return result

    class ProjectionReached(Exception):
        pass

    def project(*args, **kwargs):
        assert kwargs['deadline'] <= motion.monotonic() + 10.
        raise ProjectionReached()

    monkeypatch.setattr(rig_playback, 'validate_rig_playback', open_wrap)
    monkeypatch.setattr(motion, 'project_loop_seam_coordinates', project)
    with pytest.raises(ProjectionReached):
        motion._fit_controlled_motion(current, timeout_seconds=20.)


def test_seam_projection_continues_within_budget_only_when_body_valid_and_improving(monkeypatch):
    from exercise_motion_pkg import controlled_motion as motion, rig_playback
    names, points = stance(12)
    current = payload(names, points)
    current['loop'] = {'enabled': True}
    original = rig_playback.validate_rig_playback
    state = {'calls': 0, 'improving': True}

    def playback(candidate, **kwargs):
        result = original(candidate, **kwargs)
        if candidate.get('loop', {}).get('enabled'):
            closed = state['improving'] and state['calls'] >= 3
            result.update(seamContinuous=closed,
                seamVelocityMismatchMetersPerSecond=0. if closed else
                    (.9 * .5 ** state['calls'] if state['improving'] else .9))
        return result

    def project(coords, *args, **kwargs):
        state['calls'] += 1
        assert kwargs['deadline'] <= motion.monotonic() + 10.
        return coords.copy()

    monkeypatch.setattr(rig_playback, 'validate_rig_playback', playback)
    monkeypatch.setattr(motion, 'project_loop_seam_coordinates', project)
    _, report = motion._fit_controlled_motion(current, timeout_seconds=30.)
    assert state['calls'] == 3
    assert report['checks']['loopSeam'] is True
    state.update(calls=0, improving=False)
    _, report = motion._fit_controlled_motion(current, timeout_seconds=30.)
    assert state['calls'] == 1
    assert report['checks']['loopSeam'] is False


def test_open_seam_can_reuse_and_passes_physical_gate():
    """Applied open-seam must not be rejected again by reuse/physical policy."""
    from copy import deepcopy
    from exercise_motion_pkg.controlled_motion import (
        can_reuse_controlled_motion, intentional_open_loop_seam)
    from exercise_motion_pkg.physical_validation import physical_metrics_from_payload
    from test_controlled_motion_pipeline import accepted_payload

    payload = accepted_payload()
    payload['loop'] = {
        'enabled': True,
        'transition': 'requires_cycle_repair',
        'restartFadeMillis': 0,
    }
    report = payload['controlledMotionFit']
    report['reason'] = 'validated_controlled_motion_open_seam'
    report['loopSeamOpen'] = True
    report['checks'] = {**report['checks'], 'loopSeam': False}
    report['outputPoseDigest'] = __import__(
        'exercise_motion_pkg.sequence_stabilization', fromlist=['pose_digest']
    ).pose_digest(payload)

    assert intentional_open_loop_seam(payload)
    assert can_reuse_controlled_motion(payload)

    # Playback false is also waived when the fit labeled an open seam.
    both = deepcopy(payload)
    both['controlledMotionFit']['checks']['playback'] = False
    both['controlledMotionFit']['outputPoseDigest'] = __import__(
        'exercise_motion_pkg.sequence_stabilization', fromlist=['pose_digest']
    ).pose_digest(both)
    assert can_reuse_controlled_motion(both)

    physical = physical_metrics_from_payload(payload)
    assert physical['passed'], physical.get('reasons')
    assert 'unsafe_loop_transition' not in physical.get('reasons', [])
    assert (physical.get('rigPlayback') or {}).get('openLoopSeam') is True


def test_attaching_selected_source_bounds_keeps_valid_fit_reusable():
    from copy import deepcopy
    from exercise_motion_pkg.artifact_state import CYCLE_SELECTION
    from exercise_motion_pkg.bake_and_rank import attach_materialized_source_interval
    from exercise_motion_pkg.controlled_motion import can_reuse_controlled_motion
    from test_controlled_motion_pipeline import accepted_payload

    payload = accepted_payload()
    for index, frame in enumerate(payload['frames']):
        frame['sourceFrameIndex'] = index + 10
        frame['sourceTimeSec'] = (index + 10) / 10.0
    payload['loop'] = {'enabled': True, 'startFrame': 0, 'endFrame': 6}
    payload['controlledMotionFit']['checks']['loopSeam'] = True
    payload['controlledMotionFit']['outputPoseDigest'] = __import__(
        'exercise_motion_pkg.sequence_stabilization', fromlist=['pose_digest']
    ).pose_digest(payload)
    selection = {
        'cycleSelection': {
            'interval': {
                'startFrame': 10,
                'endFrame': 16,
                'startTimeSec': 1.0,
                'endTimeSec': 1.6,
            }
        }
    }

    assert can_reuse_controlled_motion(payload)
    assert attach_materialized_source_interval(
        payload,
        selection,
        selection_class=CYCLE_SELECTION,
    )
    assert payload['loop']['sourceStartFrame'] == 10
    assert can_reuse_controlled_motion(payload)

    stale_fit = deepcopy(payload)
    stale_fit['controlledMotionFit']['outputPoseDigest'] = __import__(
        'exercise_motion_pkg.sequence_stabilization', fromlist=['pose_digest']
    ).pose_digest(stale_fit)
    stale_fit['frames'][0]['joints']['pelvis'][0] += 0.01
    stale_digest = stale_fit['controlledMotionFit']['outputPoseDigest']
    assert not can_reuse_controlled_motion(stale_fit)
    assert attach_materialized_source_interval(
        stale_fit,
        selection,
        selection_class=CYCLE_SELECTION,
    )
    assert stale_fit['controlledMotionFit']['outputPoseDigest'] == stale_digest
    assert not can_reuse_controlled_motion(stale_fit)


def test_open_seam_requires_body_playback_without_wrap():
    from test_controlled_motion_pipeline import accepted_payload
    from exercise_motion_pkg.controlled_motion import loop_disabled_playback_passed

    payload = accepted_payload()
    assert loop_disabled_playback_passed(payload)
    payload['loop'] = {'enabled': True, 'transition': 'requires_cycle_repair'}
    assert loop_disabled_playback_passed(payload)
    payload.pop('fixedRig')
    assert not loop_disabled_playback_passed(payload)


def test_evidence_terminations_are_decisive_not_incomplete():
    from exercise_motion_pkg import controlled_motion as motion
    assert motion.unreachable_without_polish({
        'checks': {'trajectoryFit': False, 'rootTravel': False}})
    assert motion.unreachable_without_polish({
        'checks': {'anatomy': False, 'sourceArticulation': False, 'contacts': True},
        'physicalReasons': ['repair_articulation_distortion']})
    assert not motion.unreachable_without_polish({
        'checks': {'loopSeam': False, 'playback': False}})
    for stop in motion.EVIDENCE_TERMINATIONS:
        report = {
            'applied': False,
            'reason': 'fit_timeout',
            'termination': stop,
            'checks': {'loopSeam': False},
            'optimizerTermination': 'time_budget',
        }
        assert not motion.controlled_fit_processing_incomplete(report), stop
        report = {
            'applied': False,
            'reason': 'fit_timeout',
            'boundedRefinement': {'stopReason': stop},
            'checks': {'jerk': False},
        }
        assert not motion.controlled_fit_processing_incomplete(report), stop
    # Validated reject mislabeled as fit_timeout must still be decisive.
    assert not motion.controlled_fit_processing_incomplete({
        'applied': False,
        'reason': 'fit_timeout',
        'optimizerTermination': 'time_budget',
        'checks': {'loopSeam': False, 'playback': False},
    })
    assert motion.controlled_fit_processing_incomplete({
        'applied': False,
        'reason': 'fit_timeout',
        'optimizerTermination': 'time_budget',
    })


def test_default_fit_refines_failed_cycle_without_exceeding_explicit_iteration_cap(monkeypatch):
    from types import SimpleNamespace
    from exercise_motion_pkg import controlled_motion as motion
    names, points = stance(12)
    current = payload(names, points)
    current['loop'] = {'enabled': True}
    calls = []
    clean = []
    stalled = [False]

    def solve(residual, initial, pattern, limit):
        calls.append(limit)
        # First chunk always breaks the seam so validation has something to polish.
        if len(calls) == 1:
            clean.append(initial.copy())
            bad = initial.copy().reshape(12, -1)
            bad[-1, 0] += .01  # A broken restart in an otherwise stationary rig.
            return SimpleNamespace(x=bad.ravel(), nfev=limit, status=0)
        if stalled[0]:
            return SimpleNamespace(x=initial.copy(), nfev=1, status=1)
        # Two more flat bad chunks trip main-solve objective_stalled.
        if len(calls) <= 3:
            bad = clean[0].copy().reshape(12, -1)
            bad[-1, 0] += .01
            return SimpleNamespace(x=bad.ravel(), nfev=limit, status=0)
        if len(calls) == 4:
            improving = clean[0].copy().reshape(12, -1)
            improving[-1, 0] += .005
            return SimpleNamespace(x=improving.ravel(), nfev=limit, status=0)
        return SimpleNamespace(x=clean[0].copy(), nfev=1, status=1)

    monkeypatch.setattr(motion, 'solve_trajectory', solve)
    _, refined = motion.fit_controlled_motion(current, timeout_seconds=10.)
    assert refined['applied'], refined
    # Main solve is chunked (5-eval blocks) until cost stalls / converges; polish
    # then uses short blocks. Explicit max_evaluations still caps total work.
    assert calls[0] == 5 and all(size <= 5 for size in calls), calls
    assert sum(calls) <= 25 + 5 + 5, calls
    assert refined['boundedRefinement']['initialFailedChecks']
    assert len([block for block in refined['boundedRefinement']['blocks']
                if block.get('method') != 'temporal_smooth']) == 2
    calls.clear()
    stalled[0] = True
    _, stopped = motion.fit_controlled_motion(current, timeout_seconds=10.)
    assert not stopped['applied']
    assert stopped['boundedRefinement']['stopReason'] in {
        'objective_stalled', 'acceptance_stalled', 'polish_stalled',
        'seam_playback_only'}, stopped
    assert stopped.get('termination') in motion.EVIDENCE_TERMINATIONS, stopped
    assert stopped['reason'] == 'fit_validation_failed', stopped
    assert not motion.controlled_fit_processing_incomplete(stopped), stopped
    assert calls and calls[0] == 5 and all(size <= 5 for size in calls), calls
    calls.clear()
    _, capped = motion.fit_controlled_motion(current, max_evaluations=25, timeout_seconds=10.)
    assert not capped['applied']
    assert calls and sum(calls) <= 25 and all(size <= 5 for size in calls), calls


def test_sample_rig_projects_interpolated_neck_socket_alignment():
    from exercise_motion_pkg.physical_validation import (
        SOCKET_ALIGNMENT_MAX_LATERAL_RATIO, anatomical_structure_residuals)
    from exercise_motion_pkg.controlled_motion import (
        ANATOMY_FIT_MARGIN, align_vectors, project_neck_attachment_values)
    from exercise_motion_pkg.rig_playback import sample_rig, _decode_rig_matrices
    rig_names, points = stance(2)
    rig = FixedRig(points, rig_names)
    names = rig.names
    left, right, neck = [names.index(n) for n in ('left_collar', 'right_collar', 'neck')]
    span = rig.decode(rig.initial)[0, right] - rig.decode(rig.initial)[0, left]
    neck_slot = rig.slots[neck]
    # Opposite keyframe neck pushes so the interpolated midpoint leaves the socket.
    for frame, sign in ((0, 1.), (1, -1.)):
        points = rig.decode(rig.initial)
        center = (points[frame, left] + points[frame, right]) * .5
        target = center + sign * (SOCKET_ALIGNMENT_MAX_LATERAL_RATIO - ANATOMY_FIT_MARGIN) * span
        parent = points[frame, rig.parents[neck]]
        desired = target - parent
        desired = desired / np.linalg.norm(desired) * np.linalg.norm(rig.offsets[neck])
        old = Rotation.from_rotvec(rig.initial[frame, neck_slot:neck_slot + 3])
        world = old.apply(rig.offsets[neck])
        rig.initial[frame, neck_slot:neck_slot + 3] = (
            Rotation.from_rotvec(align_vectors(world[None], desired[None])) * old).as_rotvec()[0]
    limit = SOCKET_ALIGNMENT_MAX_LATERAL_RATIO - ANATOMY_FIT_MARGIN
    coordinates = project_neck_attachment_values(
        rig.initial, rig.offsets, names, rig.active, limit)
    payload = {
        'jointNames': names, 'parents': rig.parents, 'order': rig.order,
        'offsets': rig.offsets.tolist(),
        'rotationJointNames': [names[j] for j in rig.active],
        'coordinates': coordinates.tolist(),
        'interpolation': 'linear_slerp',
    }
    values = np.asarray(payload['coordinates'], dtype=float)
    quats = Rotation.from_rotvec(values[:, 3:].reshape(-1, 3)).as_quat().reshape(2, -1, 4)
    right_q = np.where(np.sum(quats[0] * quats[1], axis=-1, keepdims=True) < 0., -quats[1], quats[1])
    mid_quat = .5 * quats[0] + .5 * right_q
    mid_quat /= np.linalg.norm(mid_quat, axis=-1, keepdims=True)
    unprojected = _decode_rig_matrices(
        payload, (values[0, :3] + values[1, :3]) * .5,
        Rotation.from_quat(mid_quat.reshape(-1, 4)).as_matrix().reshape(1, -1, 3, 3))
    labels = anatomical_structure_residuals(unprojected, names, pose_only=True)[1]
    socket = labels.index('anatomy_socket_alignment:neck')
    unprojected_err = anatomical_structure_residuals(unprojected, names, pose_only=True)[0][0, socket]
    projected_err = anatomical_structure_residuals(
        sample_rig(payload, [.5]), names, pose_only=True)[0][0, socket]
    assert unprojected_err > 0.
    assert projected_err <= 1e-9


def test_rig_has_constant_bones_and_fixed_sockets_under_arbitrary_rotation():
    names,points=stance()
    rig=FixedRig(points,names)
    values=rig.initial.copy()
    values+=np.random.default_rng(31).normal(0,.1,values.shape)
    result=rig.decode(values)
    for j in rig.order[1:]:
        np.testing.assert_allclose(np.linalg.norm(result[:,j]-result[:,rig.parents[j]],axis=1),
                                   np.linalg.norm(rig.offsets[j]),atol=1e-12)
    for a,b in [('left_hip','right_hip'),('left_collar','right_collar')]:
        distances=np.linalg.norm(result[:,names.index(a)]-result[:,names.index(b)],axis=1)
        assert np.ptp(distances)<1e-12


def test_solver_can_leave_an_inactive_stiff_constraint_toward_a_better_fit():
    from scipy.sparse import csr_matrix
    from exercise_motion_pkg.controlled_motion import solve_trajectory
    def residual(values):
        x = values[0]
        return np.array([x-.09, 1e8*max(x-.10000005, 0.)])
    solved = solve_trajectory(residual, np.array([.1]), csr_matrix(np.ones((2, 1))), 25)
    assert abs(solved.x[0]-.09) < 1e-7


def test_anatomy_fit_margin_has_consistent_derivatives_at_socket_boundary():
    from exercise_motion_pkg.physical_validation import anatomical_structure_residuals, SOCKET_ALIGNMENT_MAX_LATERAL_RATIO
    names, points = stance(1)
    left, right, neck = [names.index(n) for n in ('left_collar', 'right_collar', 'neck')]
    span = points[0, right]-points[0, left]
    center = (points[0, right]+points[0, left])*.5
    current = np.dot(points[0, neck]-center, span)/np.dot(span, span)
    margin = 1e-4
    points[0, neck] += (SOCKET_ALIGNMENT_MAX_LATERAL_RATIO-margin-current)*span
    def evaluate(offset, fitting_margin):
        moved = points.copy()
        moved[0, neck] += offset*span
        values, labels = anatomical_structure_residuals(moved, names, pose_only=True, margin=fitting_margin)
        return values[0, labels.index('anatomy_socket_alignment:neck')]
    step = 1e-8
    midpoint = evaluate(0., margin)
    left_derivative = (midpoint-evaluate(-step, margin))/step
    right_derivative = (evaluate(step, margin)-midpoint)/step
    assert abs(left_derivative-right_derivative) < 1e-3
    assert midpoint > 0.
    assert evaluate(0., 0.) == 0.


def test_positive_kernel_does_not_rebound_at_a_stop():
    names,points=stance(120)
    travel=np.minimum(np.arange(120)/60.,1.)*.5
    points[:,:,0]+=travel[:,None]
    target,_,_=controlled_target(points,names,30.)
    root=names.index('pelvis')
    assert np.all(np.diff(target[:,root,0])>=-1e-10)
    assert target[:,root,0].max()<=points[:,root,0].max()+1e-10
    assert target[:,root,0].min()>=points[:,root,0].min()-1e-10


def test_sideways_travel_and_asymmetry_are_preserved_and_rotation_equivariant():
    names,points=stance(90)
    points[:,:,0]+=np.arange(90)[:,None]*.005
    points[:,names.index('left_wrist'),2]+=.1
    target,_,_=controlled_target(points,names,30.)
    root=names.index('pelvis')
    assert np.ptp(target[:,root,0])>.95*np.ptp(points[:,root,0])
    rotation=Rotation.from_euler('xyz',[.2,.6,-.3]).as_matrix()
    rotated,_,_=controlled_target(points@rotation,names,30.)
    np.testing.assert_allclose(rotated,target@rotation,atol=1e-9)
    np.testing.assert_allclose(target[:,names.index('left_wrist')]-target[:,root],
                               points[:,names.index('left_wrist')]-points[:,root],atol=1e-10)


def test_small_subordinate_deviations_reduce_without_a_world_axis_lock():
    names,points=stance(120)
    t=np.arange(120)/30.
    points[:,:,1]+=(.15*np.sin(2*np.pi*.5*t))[:,None]
    points[:,:,0]+=(.008*np.sin(2*np.pi*2.5*t))[:,None]
    target,_,evidence=controlled_target(points,names,30.)
    root=names.index('pelvis')
    assert np.std(target[20:-20,root,0])<np.std(points[20:-20,root,0])*.7
    assert np.ptp(target[:,root,1])>.9*np.ptp(points[:,root,1])
    assert evidence['maximumMinorDeviationCorrectionMeters']>0


def test_fit_preserves_contact_and_rig_and_is_reusable():
    # A short stationary clip covers denoising, contact, rig and cache reuse;
    # longer trajectories have separate motion and loop regression coverage.
    names,points=stance(12)
    rng=np.random.default_rng(13)
    head=names.index('head')
    points[:,head,0]+=rng.normal(0,.002,len(points))
    p=payload(names,points)
    p['sourceFootSupportEvidence']={'contacts':[{'jointName':s+'_foot','contactState':'full_sole',
                                               'contactMotion':'stationary','startRatio':0.,'endRatio':1.}
                                              for s in ('left','right')]}
    result,report=fit_controlled_motion(p,max_evaluations=25,timeout_seconds=60.)
    assert report['applied'],report
    assert report['maximumBoneLengthVariationMeters']<1e-10
    assert report['maximumContactErrorMeters']<.0005
    assert report['jerkAfter']<report['jerkBefore']
    assert report['settlingPreserved']
    assert all(report['checks'].values())
    result['controlledMotionFit']=report
    again,audit=fit_controlled_motion(result)
    assert again is result and audit['reused']


def test_height_only_contact_uses_a_normal_residual_in_the_fit(monkeypatch):
    from types import SimpleNamespace

    from exercise_motion_pkg import controlled_motion as motion

    names, points = stance(12)
    p = payload(names, points)
    foot_y = float(points[0, names.index('left_foot'), 1])
    p['sourceFootSupportEvidence'] = {
        'sharedSupportPlaneY': foot_y + .004,
        'contacts': [{
            'jointName': 'left_foot',
            'supportKind': 'observed_foot_patch',
            'surfaceKind': 'ground',
            'contactState': 'toe_only',
            'contactMotion': 'stationary',
            'verticalOnly': True,
            'startFrame': 2,
            'endFrame': 9,
        }],
    }
    monkeypatch.setattr(
        motion,
        'register_contact_placement',
        lambda values, *args, **kwargs: (
            values.copy(), {'observedGroundEpisodes': [{'joint': 'left_foot'}]},
        ),
    )
    captured = {}

    def capture_solver(residual, initial, pattern, max_evaluations, **kwargs):
        captured['residual'] = residual(initial)
        captured['pattern'] = pattern
        return SimpleNamespace(x=initial, nfev=1, status=1)

    monkeypatch.setattr(motion, 'solve_trajectory', capture_solver)
    result, report = fit_controlled_motion(p, max_evaluations=1, timeout_seconds=20.)

    assert report['heightOnlyContactConstraint']['available']
    assert report['heightOnlyContactConstraint']['axis'] == 'floor_normal_y'
    assert captured['residual'].shape[0] == captured['pattern'].shape[0]
    assert report['checks']['heightOnlyContacts'] is False
    assert result is p


def test_timeout_and_irregular_sampling_return_original():
    names,points=stance(10)
    p=payload(names,points)
    result,report=fit_controlled_motion(p,timeout_seconds=0.)
    # A zero watchdog still validates the initialized rig instead of discarding it.
    assert report.get('validatedInitializedCoordinatesOnTimeout')
    assert report['applied'] and result.get('fixedRig')
    p['frames'][3]['timeSec']+=.01
    result,report=fit_controlled_motion(p)
    assert result is p and report['reason']=='irregular_sampling'


def test_playback_contact_repair_stops_if_deadline_expires_before_or_during_scan(monkeypatch):
    from exercise_motion_pkg import controlled_motion as motion

    names, points = stance(12)
    rig = FixedRig(points, names)
    coordinates = rig.initial.copy()
    pinned = np.ones(points.shape[:2], dtype=bool)
    now = [10.]
    scans = []

    def scan(*args, **kwargs):
        scans.append(True)
        now[0] = 10.
        return [0]

    def unexpected_decode(*args, **kwargs):
        raise AssertionError('Expired repair must not start FK or mutate the pose')

    monkeypatch.setattr(motion, 'monotonic', lambda: now[0])
    monkeypatch.setattr(motion, '_playback_failing_intervals', scan)
    monkeypatch.setattr(rig, 'decode', unexpected_decode)
    for start, expected_scans in [(10., 0), (9., 1)]:
        now[0] = start
        result = motion.project_interval_playback_plants(
            coordinates, rig, pinned, points, deadline=10.)
        np.testing.assert_array_equal(result, coordinates)
        assert len(scans) == expected_scans


def test_initial_validation_preserves_polish_reserve_within_outer_budget(monkeypatch):
    from exercise_motion_pkg import controlled_motion as motion, rig_playback
    real_clock = motion.monotonic
    real_validation = rig_playback.validate_rig_playback
    delay = [0.]
    validation_cost = [20.]

    def expensive_validation(candidate):
        result = real_validation(candidate)
        delay[0] += validation_cost[0]
        return result

    monkeypatch.setattr(motion, 'monotonic', lambda: real_clock() + delay[0])
    monkeypatch.setattr(rig_playback, 'validate_rig_playback', expensive_validation)
    names, points = stance(12)
    _, report = motion.fit_controlled_motion(payload(names, points), timeout_seconds=60.)
    assert report['applied']
    assert report['initialValidationSeconds'] >= 20.
    assert abs(report['validationReserveSeconds'] - 2.4) < 1e-9
    assert report['polishUntilSeconds'] <= 60.
    assert report['polishUntilSeconds'] <= (
        report['initialValidationRepairDeadlineSeconds']
        + report['postValidationPolishReserveSeconds']
        + report['conditionalPlantPolishSeconds']
    )
    # Validation can finish after its allowance, but cannot extend the fit deadline.
    validation_cost[0] = 80.
    _, report = motion.fit_controlled_motion(payload(names, points), timeout_seconds=60.)
    assert report['initialValidationSeconds'] >= 80.
    assert report['polishUntilSeconds'] <= 60.


def test_time_budget_validates_saved_progress_before_discarding_it(monkeypatch):
    from exercise_motion_pkg import controlled_motion as motion
    names, points = stance(12)
    current = payload(names, points)
    current['loop'] = {'enabled': True}

    def timed_out(residual, initial, pattern, max_evaluations, **solver_options):
        residual(initial)
        raise TimeoutError

    monkeypatch.setattr(motion, 'solve_trajectory', timed_out)
    result, report = motion.fit_controlled_motion(current, timeout_seconds=180.)
    # Soft LS may stop on the solve-phase cap while outer time remains for polish.
    assert report['optimizerTermination'] in {'time_budget', 'solve_phase_budget'}
    assert report['applied']
    assert all(report['checks'].values())
    assert result.get('fixedRig')
    assert not motion.controlled_fit_processing_incomplete(report)

    def invalid_progress(residual, initial, pattern, max_evaluations, **solver_options):
        shifted = initial.copy().reshape(12, -1)
        shifted[:, 1] -= 1.
        residual(shifted.ravel())
        raise TimeoutError

    monkeypatch.setattr(motion, 'solve_trajectory', invalid_progress)
    rejected, failure = motion.fit_controlled_motion(current, timeout_seconds=180.)
    assert rejected is current
    assert not failure['applied']
    assert failure.get('checks'), failure
    # Finished checks are a decisive reject even when the soft LS hit a deadline.
    assert failure['reason'] == 'fit_validation_failed', failure
    assert not motion.controlled_fit_processing_incomplete(failure), failure


def test_support_init_watchdog_continues_to_acceptance(monkeypatch):
    """A support-stage clock stop must not discard the pose before validation."""
    from exercise_motion_pkg import controlled_motion as motion
    from exercise_motion_pkg import support_geometry
    names, points = stance(12)
    current = payload(names, points)
    # Torso support still uses the heavy LS path; plant-only feet skip it.
    stationary = [name for name in ('pelvis', 'spine1', 'spine2', 'spine3') if name in names]
    if len(stationary) < 2:
        stationary = [name for name in names if 'spine' in name or name == 'pelvis'][:3]
    evidence = {
        'required': True, 'status': 'confirmed', 'stationaryJoints': stationary,
        'coplanarGroups': [{'joints': stationary, 'normal': [0, 1, 0],
                            'planeOffsetMeters': float(points[0, names.index(stationary[0]), 1])}],
    }
    current['sourceFootSupportEvidence'] = {'bodySupport': evidence}
    monkeypatch.setattr(support_geometry, 'support_evidence', lambda payload: evidence)
    monkeypatch.setattr(support_geometry, 'plant_only_body_support', lambda evidence: False)
    monkeypatch.setattr(support_geometry, 'calibrate_support_pose',
                        lambda *args, **kwargs: (points[0], {}))
    monkeypatch.setattr(support_geometry, 'initialize_supported_motion',
                        lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError()))
    result, report = motion.fit_controlled_motion(current, timeout_seconds=20.)
    assert report.get('supportInitializationTimedOut')
    assert report.get('checks'), report
    assert not motion.controlled_fit_processing_incomplete(report)


def test_unrepaired_support_root_continuity_stops_before_main_fit(monkeypatch):
    from exercise_motion_pkg import controlled_motion as motion
    from exercise_motion_pkg import support_geometry

    names, points = stance(12)
    current = payload(names, points)
    stationary = [name for name in ('pelvis', 'spine1', 'spine2', 'spine3') if name in names]
    if len(stationary) < 2:
        stationary = [name for name in names if 'spine' in name or name == 'pelvis'][:3]
    evidence = {
        'required': True,
        'status': 'confirmed',
        'stationaryJoints': stationary,
        'coplanarGroups': [{
            'joints': stationary,
            'normal': [0., 1., 0.],
            'planeOffsetMeters': float(points[0, names.index(stationary[0]), 1]),
        }],
    }
    current['sourceFootSupportEvidence'] = {'bodySupport': evidence}

    monkeypatch.setattr(support_geometry, 'support_evidence', lambda payload: evidence)
    monkeypatch.setattr(support_geometry, 'plant_only_body_support', lambda evidence: False)
    monkeypatch.setattr(
        support_geometry, 'calibrate_support_pose', lambda *args, **kwargs: (points[0], {}),
    )
    monkeypatch.setattr(
        support_geometry, 'initialize_supported_motion',
        lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError()),
    )
    monkeypatch.setattr(motion, 'support_reference_grossly_invalid', lambda report: False)
    monkeypatch.setattr(
        motion, 'root_motion_quality',
        lambda *args, **kwargs: {'available': True, 'passed': False},
    )
    monkeypatch.setattr(
        motion, 'project_root_continuity_coordinates', lambda coordinates, *args, **kwargs: coordinates,
    )
    monkeypatch.setattr(
        motion, 'project_contact_plant_coordinates', lambda coordinates, *args, **kwargs: coordinates,
    )

    def unexpected_solver_call(*args, **kwargs):
        raise AssertionError('main trajectory fit must not run from an unrepaired support reference')

    monkeypatch.setattr(motion, 'solve_trajectory', unexpected_solver_call)
    result, report = motion.fit_controlled_motion(current, timeout_seconds=20.)

    assert result is current
    assert report['supportInitializationTimedOut'] is True
    assert report['supportReferenceRootContinuity']['passed'] is False
    assert report['reason'] == 'support_reference_projection_incomplete'
    assert report['applied'] is False


def test_support_reference_gross_failure_is_only_early_rejected_beyond_margin():
    from exercise_motion_pkg import controlled_motion as motion
    reference = {
        'supportReferenceGeometry': {
            'toleranceMeters': .01,
            'maximumStationaryJointRangeMeters': .049,
            'maximumSurfaceErrorMeters': .01,
        },
        'supportReferenceContacts': {'maximumErrorMeters': .0005},
    }
    assert not motion.support_reference_grossly_invalid(reference)
    reference['supportReferenceGeometry']['maximumSurfaceErrorMeters'] = .051
    assert motion.support_reference_grossly_invalid(reference)
    reference['supportReferenceGeometry']['maximumSurfaceErrorMeters'] = .01
    reference['supportReferenceGeometry']['maximumStationaryJointRangeMeters'] = .01
    reference['supportReferenceContacts']['maximumErrorMeters'] = .0026
    assert motion.support_reference_grossly_invalid(reference)


def test_support_anatomy_polish_does_not_require_rigid_grip_to_pass_first():
    from exercise_motion_pkg import controlled_motion as motion

    report = {
        'supportReferenceGeometry': {'passed': True},
        'supportReferenceAlignment': {'passed': True},
        'supportReferenceEquipment': {'passed': False},
    }
    assert motion.support_reference_can_be_polished(report)

    report['supportReferenceGeometry']['passed'] = False
    assert not motion.support_reference_can_be_polished(report)


def test_support_reference_near_miss_reaches_fit_but_stays_below_playback_limit():
    from exercise_motion_pkg import controlled_motion as motion

    assert motion.support_reference_contacts_pass(.000796)
    assert not motion.support_reference_contacts_pass(.0012)
    assert motion.SUPPORT_REFERENCE_CONTACT_LIMIT_METERS < motion.PLAYBACK_CONTACT_LIMIT_METERS


def test_small_monotonic_motion_is_not_a_hold():
    names,points=stance(90)
    joint=names.index('head')
    points[:,joint,0]+=np.arange(90)*.0001
    _,holds,_=controlled_target(points,names,30.)
    assert np.max(holds[10:-10,joint])<1e-10


def test_hold_coordinates_ignore_rigid_body_turns():
    names,points=stance(45)
    rotations=Rotation.from_euler('y',np.linspace(0.,.6,len(points))[:,None]).as_matrix()
    turned=np.einsum('fij,fkj->fki',rotations,points)
    np.testing.assert_allclose(body_relative_points(turned,names),body_relative_points(points,names),atol=1e-10)


def test_jump_releases_feet_and_preserves_height():
    names,points=stance(48)
    rig=FixedRig(points,names)
    points=rig.decode(rig.initial)
    phase=np.linspace(0.,np.pi,28)
    points[10:38,:,1]+=(.22*np.sin(phase))[:,None]
    p=payload(names,points)
    p['sourceFootSupportEvidence']={'contacts':[
        {'jointName':side+'_foot','contactState':'full_sole','contactMotion':'stationary',
         'startFrame':start,'endFrame':end}
        for side in ('left','right') for start,end in [(0,9),(38,47)]]}
    result,report=fit_controlled_motion(p)
    assert report['applied'],report
    track=np.array([f['joints']['pelvis'] for f in result['frames']])
    assert np.ptp(track[:,1])>.19
    assert report['maximumContactErrorMeters']<.0005


def test_small_slow_articulation_survives_full_fit():
    names,points=stance(60)
    rig=FixedRig(points,names)
    values=rig.initial.copy()
    slot=rig.slots[names.index('head')]
    values[:,slot]+=.07*np.sin(np.linspace(0.,2*np.pi,len(points)))
    points=rig.decode(values)
    result,report=fit_controlled_motion(payload(names,points))
    assert report['applied'],report
    fitted=np.array([[f['joints'][n] for n in names] for f in result['frames']])
    first=body_relative_points(points,names)[:,names.index('head')]
    last=body_relative_points(fitted,names)[:,names.index('head')]
    assert np.linalg.norm(np.ptp(last,axis=0))>.8*np.linalg.norm(np.ptp(first,axis=0))


def test_excursion_constraint_protects_large_range_without_locking_small_motion():
    from exercise_motion_pkg.controlled_motion import excursion_constraints
    names,points=stance(60)
    root=names.index('pelvis');wrist=names.index('left_wrist');head=names.index('head')
    phase=np.arange(60)*2*np.pi/60
    points[:,wrist,0]+=.2*np.sin(phase)
    points[:,head,0]+=.002*np.sin(phase)
    center,direction,minimum,active=excursion_constraints(points,root,1.)
    assert active[:,wrist].any()
    assert not active[:,head].any()
    relative=points-points[:,root:root+1]
    projection=np.sum((relative-center)*direction,axis=-1)
    assert np.all(projection[active]>=minimum[active])
    compressed=center+.5*(relative-center)
    assert np.all(np.sum((compressed-center)*direction,axis=-1)[active]<minimum[active])
    rotation=Rotation.from_euler('xyz',[.2,.5,.8]).as_matrix()
    c,d,m,a=excursion_constraints(points@rotation,root,1.)
    np.testing.assert_allclose(c,center@rotation,atol=1e-12)
    np.testing.assert_allclose(m,minimum,atol=1e-12)
    np.testing.assert_array_equal(a,active)
    np.testing.assert_allclose(d[:,wrist],direction[:,wrist]@rotation,atol=1e-12)


def test_downward_bone_does_not_invent_axial_half_turns():
    from exercise_motion_pkg.controlled_motion import transported_bone_rotations
    phase=np.linspace(0.,2*np.pi,80)
    directions=np.column_stack([.001*np.cos(phase),-np.ones(80),.001*np.sin(phase)])
    directions/=np.linalg.norm(directions,axis=1)[:,None]
    rotations=transported_bone_rotations(directions)
    np.testing.assert_allclose(rotations.apply(np.tile([0.,1.,0.],(80,1))),directions,atol=1e-12)
    changes=(rotations[:-1].inv()*rotations[1:]).magnitude()
    observed=np.arccos(np.clip(np.sum(directions[:-1]*directions[1:],axis=1),-1.,1.))
    np.testing.assert_allclose(changes,observed,atol=1e-10)
    assert np.rad2deg(changes.max())<.01


def test_vectorized_hinge_frames_match_the_final_branch_validator():
    from exercise_motion_pkg.controlled_motion import hinge_coordinates,transported_hinge_dots
    from exercise_motion_pkg.physical_validation import ARTICULATIONS
    from exercise_motion_pkg.structural_refinement import _local_hinge_bend
    from exercise_motion_pkg.models import MotionFrame
    names,points=stance(3)
    parent,bend,sine=hinge_coordinates(points,names)
    specs=[s for s in ARTICULATIONS if s[0].endswith(('_knee','_elbow'))]
    for index,(_,a,h,b,_) in enumerate(specs):
        expected=_local_hinge_bend(MotionFrame(0.,dict(zip(names,map(tuple,points[0])))),a,h,b)
        if expected is not None:
            np.testing.assert_allclose(parent[0,index],expected[0],atol=1e-12)
            np.testing.assert_allclose(bend[0,index],expected[1],atol=1e-12)
    dots=transported_hinge_dots(parent,bend,parent,-bend)
    np.testing.assert_allclose(dots[sine>1e-8],-1.,atol=1e-12)


def test_fit_budget_scales_with_frames_and_preserves_explicit_limits():
    from exercise_motion_pkg.controlled_motion import fit_time_budget
    assert fit_time_budget({'frames':[None]*60})==180.
    assert fit_time_budget({'frames':[None]*92})==230.
    assert fit_time_budget({'frames':[None]*146})==360.
    assert fit_time_budget({'frames':[None]*240})==360.
    assert fit_time_budget({'frames':[None]*2000})==360.
    assert fit_time_budget({'frames':[None]*240},60.)==60.
    assert fit_time_budget({'frames':[None]*240},0.)==0.


def test_neck_socket_repair_clears_interpolated_guard_without_moving_limbs():
    from exercise_motion_pkg.controlled_motion import (
        project_playback_neck_clearance, repair_playback_velocity_continuity, _sampling_payload)
    from exercise_motion_pkg.rig_playback import sample_rig, sample_rig_coordinates, decode_rig
    from exercise_motion_pkg.rig_interpolation import frame_boundary_velocity_jump
    fixture = json.loads((Path(__file__).parent / 'fixtures' /
        'neck_socket_interpolation_corner.json').read_text())
    names, points = stance(5)
    rig = FixedRig(points, names)
    for joint, offset in fixture['offsets'].items():
        rig.offsets[names.index(joint)] = offset
    for joint, rotations in fixture['rotations'].items():
        slot = rig.slots[names.index(joint)]
        rig.initial[:, slot:slot + 3] = rotations
    original = rig.initial.copy()
    def jump(values):
        return frame_boundary_velocity_jump(
            lambda cursors: sample_rig(_sampling_payload(rig, values), cursors),
            np.arange(1, 4), 30.)
    assert jump(original) > .001
    repaired = repair_playback_velocity_continuity(original, rig, None, None)
    assert jump(repaired) < 1e-6
    cursors = np.arange(4 * 64 + 1) / 64.
    before = sample_rig(_sampling_payload(rig, original), cursors)
    after_payload = _sampling_payload(rig, repaired)
    after = sample_rig(after_payload, cursors)
    raw = decode_rig(after_payload, sample_rig_coordinates(after_payload, cursors))
    # The guard is inactive along the dense path, not just at the knot check.
    np.testing.assert_allclose(after, raw, atol=1e-10)
    limbs = [index for index, name in enumerate(names) if name not in ('neck', 'head')]
    np.testing.assert_array_equal(after[:, limbs], before[:, limbs])
    assert np.max(np.linalg.norm(after - before, axis=-1)) < .0001
    np.testing.assert_array_equal(
        project_playback_neck_clearance(repaired, rig), repaired)


def test_support_range_derivative_matches_full_numerical_objective():
    from scipy.optimize._numdiff import approx_derivative
    from exercise_motion_pkg.controlled_motion import support_range_jacobian, angles
    names, points = stance(5)
    rig = FixedRig(points, names)
    coordinates = rig.initial.copy()
    coordinates[:, rig.slots[names.index('left_ankle')]] += np.linspace(.1, .5, len(points))
    joints = tuple(names.index(name) for name in ('left_hip', 'left_knee', 'left_ankle'))
    source = np.array([0., 1.])
    tracks = [('left_knee', joints, source)]
    def residual(values):
        candidate = rig.decode(values.reshape(coordinates.shape))
        return np.array([12000. * max(0., .92 * np.ptp(source)
            - np.ptp(angles(*(candidate[:, joint] for joint in joints))))])
    expected = approx_derivative(residual, coordinates.ravel(), method='3-point')
    actual = support_range_jacobian(coordinates.ravel(), rig, tracks).toarray()
    assert residual(coordinates.ravel())[0] > 0.
    assert np.max(np.abs(expected)) > 100.
    np.testing.assert_allclose(actual, np.atleast_2d(expected), atol=.05, rtol=1e-4)
    assert support_range_jacobian(coordinates.ravel(), rig,
        [('left_knee', joints, np.zeros(2))]).nnz == 0


def test_global_range_derivative_does_not_force_full_clip_difference_groups():
    from scipy.sparse import csr_matrix, eye, vstack
    from exercise_motion_pkg.controlled_motion import solve_trajectory
    count = 120
    initial = np.linspace(0., 1., count)
    calls = []
    def residual(values):
        calls.append(1)
        return np.r_[values - initial, 10. * max(0., 2. - np.ptp(values))]
    def tail_jacobian(values):
        result = np.zeros((1, count))
        if np.ptp(values) < 2.:
            result[0, np.argmin(values)] += 10.
            result[0, np.argmax(values)] -= 10.
        return csr_matrix(result)
    pattern = vstack([eye(count), csr_matrix(np.ones((1, count)))], format='csr')
    solved = solve_trajectory(residual, initial, pattern, 5, tail_jacobian=tail_jacobian)
    assert np.ptp(solved.x) > 1.9
    assert len(calls) < 30


def test_solver_accepts_a_precomputed_local_jacobian_with_tail_rows(monkeypatch):
    from scipy.sparse import csr_matrix, eye, vstack
    from exercise_motion_pkg import controlled_motion as motion

    target = np.array([1., -2.])
    residual = lambda values: np.r_[values - target, 0.]
    local_calls = []
    def local_jacobian(values):
        local_calls.append(values.copy())
        return eye(2, format='csr')
    def tail_jacobian(values):
        return csr_matrix([[0., 0.]])

    def unused_coloring(_pattern):
        raise AssertionError('hybrid Jacobian must not build finite-difference coloring')

    monkeypatch.setattr(motion, 'group_columns', unused_coloring)

    pattern = vstack([eye(2), csr_matrix([[1., 1.]])], format='csr')
    solved = motion.solve_trajectory(
        residual, np.zeros(2), pattern, 5,
        local_jacobian=local_jacobian, tail_jacobian=tail_jacobian)

    np.testing.assert_allclose(solved.x, target, atol=1e-8)
    assert local_calls


def test_solver_reuses_terminal_jacobian_at_next_block_start():
    from scipy.sparse import eye
    from exercise_motion_pkg.controlled_motion import solve_trajectory

    initial = np.zeros(2)
    target = np.array([10., -20.])
    local_calls = []

    def residual(values):
        return values - target

    def local_jacobian(values):
        local_calls.append(np.asarray(values).copy())
        return eye(2, format='csr')

    pattern = eye(2, format='csr')
    first_block = solve_trajectory(
        residual, initial, pattern, 2, local_jacobian=local_jacobian)
    assert not np.array_equal(first_block.x, target)
    block_start = first_block.x.copy()
    local_calls.clear()
    solved = solve_trajectory(
        residual, block_start, pattern, 2,
        local_jacobian=local_jacobian,
        initial_jacobian=first_block.jac)

    assert np.linalg.norm(solved.x - target) < np.linalg.norm(block_start - target)
    assert solved.jac.shape == (2, 2)
    assert local_calls
    assert all(not np.array_equal(values, block_start) for values in local_calls)


def test_solver_can_move_a_tiny_nonzero_rotation():
    from exercise_motion_pkg.controlled_motion import solve_trajectory
    from scipy.sparse import csr_matrix
    names,points=stance(1)
    rig=FixedRig(points,names)
    slot=rig.slots[names.index('left_ankle')]
    base=rig.initial.copy()
    base[:,:3]+=[2.,3.,4.]
    def decode(values):
        coordinates=base.copy()
        coordinates[0,slot]=values[0]
        coordinates[0,2]+=values[1]
        return rig.decode(coordinates).ravel()
    expected=np.array([.02,.11])
    target=decode(expected)
    probes=[]
    def residual(values):
        probes.append(values.copy())
        return decode(values)-target
    initial=np.array([5e-16,.1])
    solved=solve_trajectory(residual,initial,csr_matrix(np.ones((len(target),2))),25)
    np.testing.assert_allclose(solved.x,expected,atol=1e-6)
    first_rotation_probe=next(v for v in probes if v[0]!=initial[0] and v[1]==initial[1])
    derivative=(decode(first_rotation_probe)-decode(initial))/(first_rotation_probe[0]-initial[0])
    assert np.linalg.norm(derivative)>.1


def test_sparse_dependencies_cover_coupled_rotations_and_body_relative_motion():
    from exercise_motion_pkg.controlled_motion import joint_dependencies,rotation_prior_dependencies
    from scipy.optimize._numdiff import approx_derivative
    initial=Rotation.from_euler('xyz',[.3,.4,.5])
    values=np.array([0.,0.,0.,.25,-.37,.22])
    derivative=approx_derivative(lambda v:(initial.inv()*Rotation.from_rotvec(v[3:])).as_rotvec(),values)
    pattern=rotation_prior_dependencies(6).astype(bool)
    assert np.all(abs(derivative[~pattern])<1e-8)
    assert np.any(abs(derivative[:,3:]-np.diag(np.diag(derivative[:,3:])))>1e-3)
    names,points=stance(1)
    rig=FixedRig(points,names)
    values=rig.initial.ravel()+.01
    derivative=approx_derivative(lambda v:body_relative_points(rig.decode(v[None,:]),names).ravel(),values)
    basis=joint_dependencies(rig,('pelvis','left_hip','right_hip','neck'))
    pattern=np.maximum(rig.dependencies,basis[None,:]).astype(bool)
    assert np.all(abs(derivative[~pattern])<1e-7)
    assert not pattern.all()
