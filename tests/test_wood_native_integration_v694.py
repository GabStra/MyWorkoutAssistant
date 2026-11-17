"""Wood native typed-contact integration regressions (v694).

Bounded checks retained from the v691 fix set:
1. The early support-seed direction-restoration branch must bind the same
   camera-ray-conditioned heading authority as the pre-solve path (the v691
   crash used the name before its later assignment).
2. Green native-v2 stationary caches may not be reused without the persisted
   typed exact-key proof (old v140-era caches predate ``contactConstraintEvidence``).
"""
from __future__ import annotations

from copy import deepcopy

import numpy as np
import pytest

from exercise_motion_pkg.controlled_motion import (
    REQUIRED_FIT_CHECKS, CONTROLLED_MOTION_STRATEGY,
    native_typed_material_reuse_proof,
)


# ---------------------------------------------------------------------------
# Check 1: early seed-restoration binds ray-conditioned heading authority
# ---------------------------------------------------------------------------

def test_early_seed_direction_restoration_binds_ray_conditioned_heading_authority(monkeypatch):
    from exercise_motion_pkg import (
        contact_heel_pitch, controlled_motion as motion,
        joint_plant_initialization, support_geometry,
    )
    from test_controlled_motion import payload, stance

    frame_count = 12
    names, points = stance(frame_count)
    current = payload(names, points)
    stationary = [name for name in ('pelvis', 'spine1', 'spine2', 'spine3') if name in names]
    if len(stationary) < 2:
        stationary = [name for name in names if 'spine' in name or name == 'pelvis'][:3]
    evidence = {
        'required': True, 'status': 'confirmed', 'stationaryJoints': stationary,
        'coplanarGroups': [{'joints': stationary, 'normal': [0, 1, 0],
                            'planeOffsetMeters': float(points[0, names.index(stationary[0]), 1])}],
    }
    current['sourceFootSupportEvidence'] = {'bodySupport': evidence}

    # Observed-ray coverage: one paired right-ankle observation marks exactly
    # its endpoint frames; the left side stays without any authoritative ray.
    constraint = {
        'available': True, 'observations': [],
        'sourceFootRaySideMapping': {'right': 'right'},
        'sourceFootRayObservations': [{
            'sourceSide': 'right', 'leftFrame': 2, 'rightFrame': 5, 'alpha': .5,
            'ankleJointIndex': names.index('right_ankle'),
            'footJointIndex': names.index('right_foot'),
            'targetRay': np.array([1., 0.]), 'headingOffsetRadians': 0.,
        }],
    }
    monkeypatch.setattr(motion, '_prepare_source_projection_fit_constraints',
                        lambda *args, **kwargs: constraint)
    monkeypatch.setattr(contact_heel_pitch, 'propose_source_heel_pitch',
                        lambda *_args, **_kwargs: (None, {'available': False}))
    monkeypatch.setattr(support_geometry, 'support_evidence',
                        lambda *args, **kwargs: evidence)
    monkeypatch.setattr(support_geometry, 'plant_only_body_support', lambda _evidence: False)
    monkeypatch.setattr(support_geometry, 'calibrate_support_pose',
                        lambda *args, **kwargs: (points[0], {}))
    # The static calibration frame owns a separate unit under test; pass it so
    # the flow continues into the seed/restore stage instead of returning.
    monkeypatch.setattr(support_geometry, 'validate_static_support_pose',
                        lambda *args, **kwargs: {'passed': True})
    # The LS watchdog stops this stage; the fit must continue from the seed and
    # reach the early direction-restoration branch, not an early reject.
    monkeypatch.setattr(support_geometry, 'initialize_supported_motion',
                        lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError()))
    monkeypatch.setattr(joint_plant_initialization,
                        'contact_conditioned_articulation_reference',
                        lambda reference, *_args, **_kwargs: (
                            reference.copy(),
                            {side: np.zeros(len(points), dtype=bool) for side in ('left', 'right')},
                            {side: np.zeros(len(points), dtype=bool) for side in ('left', 'right')},
                            {}))
    monkeypatch.setattr(joint_plant_initialization,
                        'source_conditioned_foot_direction_reference',
                        lambda reference, *_args, **_kwargs: (reference.copy(), {}, {}))
    monkeypatch.setattr(motion, 'support_reference_grossly_invalid', lambda *args, **kwargs: False)
    monkeypatch.setattr(motion, 'support_reference_can_be_polished', lambda *args, **kwargs: False)
    # The joint fit must keep repairing the seed here; a verified-frame deferral
    # would skip the early direction-restoration branch under test.
    monkeypatch.setattr(motion, 'supported_seed_frame_is_valid',
                        lambda *args, **kwargs: False)
    monkeypatch.setattr(motion, 'support_articulation_guard_required',
                        lambda *args, **kwargs: True)
    monkeypatch.setattr(
        motion, 'support_initialization_articulation_regressions',
        lambda *args, **kwargs: [{
            'feature': 'right_observed_camera_foot_heading',
            'p95ChangeDegrees': 20., 'toleranceDegrees': 15.,
        }])

    captured = {}

    class EarlyBranchReached(Exception):
        pass

    def restore(_rig, _coordinates, _reference, _evidence, _deadline, **kwargs):
        captured.update(kwargs)
        raise EarlyBranchReached()

    monkeypatch.setattr(support_geometry, 'restore_supported_foot_directions', restore)

    with pytest.raises(EarlyBranchReached):
        motion._fit_controlled_motion_impl(current, timeout_seconds=120.)

    # Before the v694 fix this raised UnboundLocalError (argument evaluated
    # before the later pre-solve assignment), so reaching the stub at all is
    # the regression signal; the masks below pin the shared semantics.
    authority = captured['heading_authority']
    assert set(authority) == {'left', 'right'}
    expected_left = np.ones(frame_count, dtype=bool)
    expected_right = np.ones(frame_count, dtype=bool)
    expected_right[[2, 5]] = False  # only the ray endpoint frames are owned by the camera
    np.testing.assert_array_equal(authority['left'], expected_left)
    np.testing.assert_array_equal(authority['right'], expected_right)
    assert np.asarray(captured['pinned']).shape == (frame_count, len(names))


# ---------------------------------------------------------------------------
# Check 2: selective native-v2 stationary reuse proof
# ---------------------------------------------------------------------------

def _stationary_payload(tracks, evidence):
    return {
        'fixedRig': {'contactFootTracks': tracks},
        'controlledMotionFit': {'contactConstraintEvidence': evidence},
    }


def _valid_stationary_metrics():
    return {
        'available': True,
        'keyframeStationarySampleCount': 2,
        'keyframeStationaryMaximumErrorMeters': 2.48155e-4,
        'keyframeHeightSampleCount': 0,
        'keyframeHeightMaximumErrorMeters': 0.,
        'playbackStationarySampleCount': 48,
        'playbackStationaryMaximumErrorMeters': 8.6e-4,
        'playbackHeightSampleCount': 0,
        'playbackHeightMaximumErrorMeters': 0.,
        'sampleCount': 50,
        'maximumErrorMeters': 8.6e-4,
    }


def _evidence_for(metrics):
    return {
        'applicable': True, 'status': 'verified', 'passed': True,
        'nativeMaterialActive': True, 'nativeMaterialEvaluated': True,
        'nativeMaterialPlayback': metrics,
        'nativeMaterialRequiredKeySamples': {
            'keyframeStationarySampleCount': 2, 'keyframeHeightSampleCount': 0},
        'nativeMaterialTypedVerdict': {'available': True, 'passed': True,
                                       'reason': None, 'components': []},
    }


def test_typed_reuse_proof_keeps_non_native_and_height_only_caches_admissible():
    from test_native_material_authority import _stationary_track

    assert native_typed_material_reuse_proof({}) is True
    assert native_typed_material_reuse_proof({'fixedRig': {}}) is True
    legacy = {'fixedRig': {'contactFootTracks': {'version': 1, 'left': {}}},
              'controlledMotionFit': {'applied': True}}
    assert native_typed_material_reuse_proof(legacy) is True

    tracks = _stationary_track(target_world=[.05, 0., .03])[3]
    height_only = deepcopy(tracks)
    for side in ('left', 'right'):
        for episode in (height_only.get(side) or {}).get('episodes') or ():
            episode['mode'] = 'verticalOnly'
            episode.pop('targetWorld', None)
    # No stationary key demand: the heightOnly proof owns this cache instead.
    assert native_typed_material_reuse_proof(
        {'fixedRig': {'contactFootTracks': height_only}}) is True


def test_typed_reuse_proof_fails_closed_for_old_green_cache_without_proof():
    from test_native_material_authority import _stationary_track

    tracks = _stationary_track(target_world=[.05, 0., .03])[3]
    v140_cache = {'fixedRig': {'contactFootTracks': tracks},
                  'controlledMotionFit': {'applied': True, 'checks': {'contacts': True}}}
    assert native_typed_material_reuse_proof(v140_cache) is False
    missing_report = {'fixedRig': {'contactFootTracks': tracks}}
    assert native_typed_material_reuse_proof(missing_report) is False


def test_typed_reuse_proof_fails_stationary_key_over_half_millimetre_or_uncovered():
    from test_native_material_authority import _stationary_track

    tracks = _stationary_track(target_world=[.05, 0., .03])[3]

    violating = dict(_valid_stationary_metrics(),
                     keyframeStationaryMaximumErrorMeters=6.5e-4)
    assert native_typed_material_reuse_proof(
        _stationary_payload(tracks, _evidence_for(violating))) is False

    nonfinite = dict(_valid_stationary_metrics(),
                     keyframeStationaryMaximumErrorMeters=float('nan'))
    assert native_typed_material_reuse_proof(
        _stationary_payload(tracks, _evidence_for(nonfinite))) is False

    uncovered = dict(_valid_stationary_metrics(),
                     keyframeStationarySampleCount=0,
                     keyframeStationaryMaximumErrorMeters=0.)
    assert native_typed_material_reuse_proof(
        _stationary_payload(tracks, _evidence_for(uncovered))) is False


def test_typed_reuse_proof_accepts_current_valid_stationary_key_proof():
    from test_native_material_authority import _stationary_track

    tracks = _stationary_track(target_world=[.05, 0., .03])[3]
    assert native_typed_material_reuse_proof(
        _stationary_payload(tracks, _evidence_for(_valid_stationary_metrics()))) is True

    # Neither the active nor the evaluated flag may be faked alongside the
    # metrics: each alone fails closed.
    inactive = _evidence_for(_valid_stationary_metrics())
    inactive['nativeMaterialActive'] = False
    assert native_typed_material_reuse_proof(
        _stationary_payload(tracks, inactive)) is False
    unevaluated = _evidence_for(_valid_stationary_metrics())
    unevaluated['nativeMaterialEvaluated'] = False
    assert native_typed_material_reuse_proof(
        _stationary_payload(tracks, unevaluated)) is False


def test_can_reuse_consumes_typed_material_proof(monkeypatch):
    """The selective proof is wired into reuse admission in both directions."""
    from exercise_motion_pkg import (
        controlled_motion as motion, contact_constraints, foot_geometry,
        rig_playback, support_alignment, support_geometry,
    )
    from test_native_material_authority import _stationary_track

    tracks = _stationary_track(target_world=[.05, 0., .03])[3]
    payload = {
        'fixedRig': {'contactFootTracks': tracks},
        'controlledMotionFit': {
            'applied': True, 'strategy': CONTROLLED_MOTION_STRATEGY,
            'checks': {key: True for key in REQUIRED_FIT_CHECKS},
            'fitSourceEvidenceDigest': 'digest', 'outputPoseDigest': 'pose',
            'contactConstraintEvidence': _evidence_for(_valid_stationary_metrics()),
        },
    }
    monkeypatch.setattr(contact_constraints, 'source_support_mapping_unresolved',
                        lambda *args, **kwargs: False)
    monkeypatch.setattr(motion, 'source_foot_patch_clock_failure', lambda *args, **kwargs: None)
    monkeypatch.setattr(motion, 'source_foot_patch_pose_binding_failure',
                        lambda *args, **kwargs: None)
    monkeypatch.setattr(motion, 'intentional_open_loop_seam', lambda *args, **kwargs: False)
    monkeypatch.setattr(motion, 'controlled_motion_fit_source_evidence_digest',
                        lambda *args, **kwargs: 'digest')
    monkeypatch.setattr(motion, 'pose_digest', lambda *args, **kwargs: 'pose')
    monkeypatch.setattr(motion, 'native_height_material_reuse_proof',
                        lambda *args, **kwargs: True)
    monkeypatch.setattr(support_geometry, 'validate_support_geometry',
                        lambda *args, **kwargs: {'passed': True})
    monkeypatch.setattr(support_geometry, 'validate_supported_shoe_orientation',
                        lambda *args, **kwargs: {'passed': True})
    monkeypatch.setattr(support_alignment, 'validate_payload_alignment',
                        lambda *args, **kwargs: {'passed': True})
    monkeypatch.setattr(rig_playback, 'mirrored_arm_policy_evidence',
                        lambda *args, **kwargs: {'passed': True})
    monkeypatch.setattr(rig_playback, 'canonical_execution_policy_evidence',
                        lambda *args, **kwargs: {'passed': True})
    monkeypatch.setattr(foot_geometry, 'canonical_material_shoe_evidence',
                        lambda *args, **kwargs: {'passed': True})

    assert motion.can_reuse_controlled_motion(payload) is True
    stale = deepcopy(payload)
    stale['controlledMotionFit'].pop('contactConstraintEvidence')
    assert motion.can_reuse_controlled_motion(stale) is False
