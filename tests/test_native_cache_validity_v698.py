"""Native-v2 cache admission regressions for malformed track semantics (v698).

The selective typed-material cache proof must never treat an unreadable
native-v2 side track as "no key proof required". The shared native track
validator is the single semantic owner; these regressions pin that malformed
stationary targets and malformed height-only planes fail closed while valid
stationary, valid height-only, and legacy/nonnative reuse stay unchanged.
"""
from __future__ import annotations

from exercise_motion_pkg.contact_interpolation import (
    _validated_native_side_track,
    native_material_key_sample_requirements,
)
from exercise_motion_pkg.controlled_motion import native_typed_material_reuse_proof
from test_native_material_authority import _stationary_track
from test_wood_native_integration_v694 import (
    _evidence_for,
    _stationary_payload,
    _valid_stationary_metrics,
)


def _tracks_without_stationary_target():
    """Root reproducer: valid stationary geometry minus ``targetWorld``."""
    tracks = _stationary_track(target_world=[0., 0., 0.])[3]
    for side in ('left', 'right'):
        for episode in (tracks.get(side) or {}).get('episodes') or ():
            episode.pop('targetWorld', None)
    return tracks


def _height_only_tracks():
    """Valid height-only shape: vertical-only episodes own no world target."""
    tracks = _stationary_track(target_world=[.05, 0., .03], sides=('left', 'right'))[3]
    for side in ('left', 'right'):
        for episode in (tracks.get(side) or {}).get('episodes') or ():
            episode['mode'] = 'verticalOnly'
            episode.pop('targetWorld', None)
    return tracks


def test_missing_stationary_target_cannot_bypass_typed_key_proof():
    tracks = _tracks_without_stationary_target()
    assert native_typed_material_reuse_proof(
        {'fixedRig': {'contactFootTracks': tracks}}) is False
    # A malformed target must also fail closed even if a valid-looking typed
    # metrics stamp is persisted: the stamp cannot replace track semantics.
    assert native_typed_material_reuse_proof(
        _stationary_payload(tracks, _evidence_for(_valid_stationary_metrics()))
    ) is False


def test_nonfinite_or_invalid_stationary_target_fails_closed():
    nonfinite = _tracks_without_stationary_target()
    nonfinite['left']['episodes'][0]['targetWorld'] = [float('nan'), 0., 0.]
    assert native_typed_material_reuse_proof(
        {'fixedRig': {'contactFootTracks': nonfinite}}) is False

    invalid_material = _stationary_track(target_world=[0., 0., 0.])[3]
    invalid_material['left']['episodes'][0]['barycentric'] = [.2, .3, .6]
    assert native_typed_material_reuse_proof(
        {'fixedRig': {'contactFootTracks': invalid_material}}) is False

    missing_plane = _stationary_track(target_world=[0., 0., 0.])[3]
    missing_plane['left']['episodes'][0].pop('surfaceNormal')
    assert native_typed_material_reuse_proof(
        {'fixedRig': {'contactFootTracks': missing_plane}}) is False


def test_valid_stationary_track_requires_and_accepts_exact_key_proof():
    tracks = _stationary_track(target_world=[.05, 0., .03])[3]
    assert native_material_key_sample_requirements(tracks) == {
        'keyframeStationarySampleCount': 2, 'keyframeHeightSampleCount': 0}
    # No persisted proof is not "nothing to prove".
    assert native_typed_material_reuse_proof(
        {'fixedRig': {'contactFootTracks': tracks}}) is False
    assert native_typed_material_reuse_proof(
        _stationary_payload(tracks, _evidence_for(_valid_stationary_metrics()))
    ) is True

    violating = dict(_valid_stationary_metrics(),
                     keyframeStationaryMaximumErrorMeters=6.5e-4)
    assert native_typed_material_reuse_proof(
        _stationary_payload(tracks, _evidence_for(violating))) is False
    uncovered = dict(_valid_stationary_metrics(),
                     keyframeStationarySampleCount=0,
                     keyframeStationaryMaximumErrorMeters=0.)
    assert native_typed_material_reuse_proof(
        _stationary_payload(tracks, _evidence_for(uncovered))) is False


def test_valid_height_only_and_legacy_nonnative_reuse_stay_admissible():
    assert native_typed_material_reuse_proof({}) is True
    legacy = {'fixedRig': {'contactFootTracks': {'version': 1, 'left': {}}}}
    assert native_typed_material_reuse_proof(legacy) is True

    height_only = _height_only_tracks()
    for side in ('left', 'right'):
        _validated_native_side_track(
            height_only[side], len(height_only[side]['active']), side)
    assert native_material_key_sample_requirements(height_only) == {
        'keyframeStationarySampleCount': 0, 'keyframeHeightSampleCount': 4}
    # The existing height-plane proof owns this cache; typed stationary proof
    # has no stationary key demand to satisfy.
    assert native_typed_material_reuse_proof(
        {'fixedRig': {'contactFootTracks': height_only}}) is True


def test_invalid_height_only_semantics_and_legacy_target_world_fail_closed():
    malformed_plane = _height_only_tracks()
    malformed_plane['left']['episodes'][0]['planeOffsetMeters'] = float('nan')
    assert native_typed_material_reuse_proof(
        {'fixedRig': {'contactFootTracks': malformed_plane}}) is False

    nonunit_normal = _height_only_tracks()
    nonunit_normal['left']['episodes'][0]['surfaceNormal'] = [0., 2., 0.]
    assert native_typed_material_reuse_proof(
        {'fixedRig': {'contactFootTracks': nonunit_normal}}) is False

    # A height-only episode carrying a stationary world target is itself an
    # invalid native-v2 shape; it must not collapse into zero key demand.
    legacy_target = _height_only_tracks()
    legacy_target['left']['episodes'][0]['targetWorld'] = [.05, 0., .03]
    assert native_typed_material_reuse_proof(
        {'fixedRig': {'contactFootTracks': legacy_target}}) is False


def test_malformed_track_shapes_are_reported_by_the_shared_validator():
    """The shared owner, not a second structural validator, rejects these."""
    tracks = _tracks_without_stationary_target()
    try:
        _validated_native_side_track(
            tracks['left'], len(tracks['left']['active']), 'left')
    except ValueError as exc:
        assert 'stationary native contact target is invalid' in str(exc)
    else:  # pragma: no cover - regression guard
        raise AssertionError('missing stationary target was accepted')
