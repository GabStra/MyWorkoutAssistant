from copy import deepcopy

import numpy as np
import pytest

from exercise_motion_pkg.contact_interpolation import (
    ContactFootIKUnreachable, native_material_key_sample_requirements,
    native_material_playback_residuals)
from exercise_motion_pkg.controlled_motion import (
    _sampling_payload, native_material_contact_domain,
    native_material_key_sample_requirements_by_side,
    native_material_playback_sample_requirements,
    native_material_contact_verdict, native_typed_material_reuse_proof,
    rendered_native_material_contact_domain,
    sample_fresh_fit_subframe_points)
from exercise_motion_pkg.native_material_frames import (
    freeze_material_frames, material_axes)
from exercise_motion_pkg.rig_playback import (
    _native_sampling_rig, sample_rig, sample_rig_coordinates)
from test_native_contact_reach import _fixture


def _artifact_payload(rig, tracks, *, legs='mirrored'):
    """Build the real artifact shape consumed by ``_native_sampling_rig``."""
    fixed_rig = {
        key: (value.tolist() if isinstance(value, np.ndarray) else value)
        for key, value in _sampling_payload(rig, rig.initial).items()
    }
    fixed_rig['contactFootTracks'] = tracks
    points = rig.decode(rig.initial)
    return {
        'fixedRig': fixed_rig,
        'frames': [{'joints': dict(zip(rig.names, row.tolist()))}
                   for row in points],
        'nativeFootGeometry': rig.native_foot_geometry_for_sampling,
        'canonicalExecution': ({'legs': legs} if legs else {}),
        'loop': {'enabled': True},
    }


def _rendered_fixture(mode='stationary', correction=.0007):
    rig, tracks = _fixture(mode, correction=correction)
    axes = {side: np.tile([1., 0., 0.], (len(rig.initial), 1))
            for side in ('left', 'right')}
    rig.material_frames = freeze_material_frames(rig, tracks, axes)
    return rig, tracks, _native_sampling_rig(_artifact_payload(rig, tracks))


def _production_cursors(frame_count, *, cyclic=True):
    """The quarter-frame playback clock shared by the fit and renderer."""
    interval_count = frame_count if cyclic else max(frame_count - 1, 0)
    return (np.arange(interval_count)[:, None]
            + np.array([.25, .5, .75])).ravel()


def test_rendered_material_contact_measures_final_playback_pose():
    """The rendered proof must sample contact IK, not the pre-correction FK."""
    rig, tracks, sampling = _rendered_fixture()
    cursors = np.array([.5])
    raw_coordinates = sample_rig_coordinates(sampling, cursors, wrap=True)
    raw_points = rig.decode(raw_coordinates)
    raw_axes = material_axes(sampling, cursors, wrap=True)
    playback_sampling = {**sampling, 'contactFootTracks': tracks}
    rendered_points, rendered_axes = sample_rig(
        playback_sampling, cursors, wrap=True, return_side_axes=True)

    # The candidate's raw pose and its final playback pose genuinely differ.
    assert np.max(np.linalg.norm(rendered_points - raw_points, axis=-1)) > 1e-4
    raw_residual = native_material_playback_residuals(
        raw_points, rig.names, rig.offsets, tracks, cursors, wrap=True,
        fractional_side_axes=raw_axes)
    rendered_residual = native_material_playback_residuals(
        rendered_points, rig.names, rig.offsets, tracks, cursors, wrap=True,
        fractional_side_axes=rendered_axes)
    assert (np.linalg.norm(rendered_residual)
            < np.linalg.norm(raw_residual) - 1e-4)

    active, metrics, required, verdict = rendered_native_material_contact_domain(
        rig.names, rig.offsets, tracks, cursors, cyclic=True,
        sampling_payload=sampling,
        native_geometry=rig.native_foot_geometry_for_sampling,
        foot_scale=rig.native_foot_scale_for_sampling)

    assert active and metrics['available'] and verdict['passed']
    expected, expected_by_side = native_material_playback_sample_requirements(
        tracks, cursors, cyclic=True)
    assert required == expected
    assert verdict['passed']
    assert expected_by_side
    assert all(row['requiredSampleCount'] == row['sampleCount']
               for row in verdict['components']
               if row['feature'] in {'left_stationary_xyz',
                                     'right_stationary_xyz'})
    # The rendered proof owns only the dense playback clock; exact keyframes
    # stay on the raw candidate domain and are not duplicated here.
    assert metrics['keyframeSampleCount'] == 0
    assert metrics['playbackSampleCount'] == 1
    np.testing.assert_allclose(
        metrics['maximumErrorMeters'],
        float(np.linalg.norm(rendered_residual)), atol=1e-12)


def test_rendered_material_contact_proof_fails_closed_when_unreachable():
    rig, tracks, sampling = _rendered_fixture(correction=.004)
    with pytest.raises(ContactFootIKUnreachable):
        rendered_native_material_contact_domain(
            rig.names, rig.offsets, tracks, np.array([.5]), cyclic=True,
            sampling_payload=sampling,
            native_geometry=rig.native_foot_geometry_for_sampling,
            foot_scale=rig.native_foot_scale_for_sampling)


def _raw_native_metrics(tracks):
    """Minimal passing raw proof for the retained stationary keyframes."""
    required = native_material_key_sample_requirements(tracks)
    by_side = native_material_key_sample_requirements_by_side(tracks)
    metrics = {
        'available': True,
        'keyframeStationarySampleCount':
            required['keyframeStationarySampleCount'],
        'keyframeStationaryMaximumErrorMeters': 1e-5,
        'keyframeHeightSampleCount': required['keyframeHeightSampleCount'],
        'keyframeHeightMaximumErrorMeters': 0.,
        'playbackStationarySampleCount': 0,
        'playbackStationaryMaximumErrorMeters': 0.,
        'playbackHeightSampleCount': 0,
        'playbackHeightMaximumErrorMeters': 0.,
        'sampleCount': sum(required.values()),
        'maximumErrorMeters': 1e-5,
    }
    metrics['bySide'] = {
        side: {
            'keyframeStationarySampleCount':
                counts['keyframeStationarySampleCount'],
            'keyframeStationaryMaximumErrorMeters':
                1e-5 if counts['keyframeStationarySampleCount'] else 0.,
            'keyframeHeightSampleCount':
                counts['keyframeHeightSampleCount'],
            'keyframeHeightMaximumErrorMeters':
                1e-5 if counts['keyframeHeightSampleCount'] else 0.,
        }
        for side, counts in by_side.items()
    }
    return metrics


def _reuse_payload(tracks, raw_metrics, *, rendered=None, cyclic=True, rig=None):
    evidence = {
        'nativeMaterialActive': True,
        'nativeMaterialEvaluated': True,
        'nativeMaterialPlayback': raw_metrics,
    }
    if rendered is not None:
        evidence.update({
            'nativeMaterialRenderedApplicable': True,
            'nativeMaterialRenderedEvaluated': True,
            'nativeMaterialRenderedPlayback': rendered,
        })
    payload = {
        'fixedRig': {'contactFootTracks': tracks},
        'loop': {'enabled': cyclic},
        'controlledMotionFit': {'contactConstraintEvidence': evidence},
    }
    if rig is not None:
        # Reuse is a real-artifact admission check, so exercise the serialized
        # clocks (fixedRig.coordinates, frames, materialFrames) as well.
        payload = _artifact_payload(rig, tracks)
        payload['loop'] = {'enabled': cyclic}
        payload['controlledMotionFit'] = {
            'contactConstraintEvidence': evidence}
    return payload


def test_typed_reuse_proof_rejects_legacy_active_native_without_rendered_proof():
    rig, tracks, _ = _rendered_fixture()
    payload = _reuse_payload(tracks, _raw_native_metrics(tracks))
    # The old marker-free contract accepted the raw pre-contact-IK proof.
    # Active native material now forces revalidation instead.
    assert native_typed_material_reuse_proof(payload) is False


def test_typed_reuse_proof_rejects_available_but_empty_dense_proof():
    rig, tracks, _ = _rendered_fixture()
    cursors = _production_cursors(len(rig.initial), cyclic=True)
    expected, expected_by_side = native_material_playback_sample_requirements(
        tracks, cursors, cyclic=True)
    assert expected['playbackStationarySampleCount'] > 0
    assert any(row['playbackStationarySampleCount'] > 0
               for row in expected_by_side.values())
    empty = {
        'available': True, 'sampleCount': 0,
        'playbackStationarySampleCount': 0,
        'playbackStationaryMaximumErrorMeters': 0.,
        'playbackHeightSampleCount': 0,
        'playbackHeightMaximumErrorMeters': 0.,
        'maximumErrorMeters': 0.,
        'bySide': {
            side: {
                'sampleCount': 0,
                'playbackStationarySampleCount': 0,
                'playbackStationaryMaximumErrorMeters': 0.,
                'playbackHeightSampleCount': 0,
                'playbackHeightMaximumErrorMeters': 0.,
            }
            for side in expected_by_side
        },
    }
    payload = _reuse_payload(
        tracks, _raw_native_metrics(tracks), rendered=empty)
    assert native_typed_material_reuse_proof(payload) is False


def test_fresh_rendered_verdict_rejects_missing_expected_dense_samples():
    rig, tracks, _ = _rendered_fixture()
    cursors = _production_cursors(len(rig.initial), cyclic=True)
    expected, expected_by_side = native_material_playback_sample_requirements(
        tracks, cursors, cyclic=True)
    empty = {
        'available': True, 'sampleCount': 0,
        'playbackStationarySampleCount': 0,
        'playbackStationaryMaximumErrorMeters': 0.,
        'playbackHeightSampleCount': 0,
        'playbackHeightMaximumErrorMeters': 0.,
        'maximumErrorMeters': 0.,
        'bySide': {},
    }
    verdict = native_material_contact_verdict(
        empty, required=expected, required_by_side=expected_by_side)
    assert verdict['passed'] is False
    assert verdict['reason'] == 'native_material_required_proof_missing'


def test_typed_reuse_proof_accepts_real_rendered_dense_proof():
    rig, tracks, sampling = _rendered_fixture()
    cursors = _production_cursors(len(rig.initial), cyclic=True)
    active, rendered, required, verdict = (
        rendered_native_material_contact_domain(
            rig.names, rig.offsets, tracks, cursors, cyclic=True,
            sampling_payload=sampling,
            native_geometry=rig.native_foot_geometry_for_sampling,
            foot_scale=rig.native_foot_scale_for_sampling))
    expected, expected_by_side = native_material_playback_sample_requirements(
        tracks, cursors, cyclic=True)
    assert active and rendered['available'] and verdict['passed']
    assert required == expected
    assert rendered['sampleCount'] == sum(expected.values())
    for side, counts in expected_by_side.items():
        for key, count in counts.items():
            assert rendered['bySide'][side][key] == count
    payload = _reuse_payload(
        tracks, _raw_native_metrics(tracks), rendered=rendered, rig=rig)
    assert native_typed_material_reuse_proof(payload) is True


@pytest.mark.parametrize('mode, required_key', [
    ('stationary', 'playbackStationarySampleCount'),
    ('verticalOnly', 'playbackHeightSampleCount'),
])
def test_playback_sample_requirements_split_mode_and_side(mode, required_key):
    rig, tracks, _ = _rendered_fixture(mode=mode)
    cursors = _production_cursors(len(rig.initial), cyclic=True)
    required, by_side = native_material_playback_sample_requirements(
        tracks, cursors, cyclic=True)
    other_key = ('playbackHeightSampleCount'
                 if required_key == 'playbackStationarySampleCount'
                 else 'playbackStationarySampleCount')
    assert required[required_key] > 0
    assert required[other_key] == 0
    assert set(by_side) == {'right'}
    assert by_side['right'][required_key] == required[required_key]


def test_single_frame_native_material_fails_closed_without_leaking_exceptions():
    rig, tracks, _ = _rendered_fixture()
    one_frame = {
        'version': 2,
        'right': {
            **tracks['right'],
            'active': tracks['right']['active'][:1],
            'directions': tracks['right']['directions'][:1],
            'sideAxes': tracks['right']['sideAxes'][:1],
            'anchorIds': tracks['right']['anchorIds'][:1],
            'episodes': [{**tracks['right']['episodes'][0],
                          'startFrame': 0, 'endFrame': 0}],
        },
    }
    assert native_material_playback_sample_requirements(
        one_frame, np.array([]), cyclic=False) == (
            {'playbackStationarySampleCount': 0,
             'playbackHeightSampleCount': 0}, {})
    # The production sampler refuses fewer than two frames, so the raw
    # exact-key proof cannot stand in for an unrenderable artifact.
    payload = _reuse_payload(
        one_frame, _raw_native_metrics(one_frame), cyclic=False)
    assert native_typed_material_reuse_proof(payload) is False

    # The fresh raw domain still measures the exact key, but its verdict fails
    # closed on the unsupported clock instead of raising a reshape error.
    key_points = rig.decode(rig.initial[:1])
    active, metrics, required, verdict = native_material_contact_domain(
        key_points, None, rig.names, rig.offsets, one_frame, np.array([]),
        cyclic=False, key_side_axes={'right': tracks['right']['sideAxes'][:1]},
        dense_side_axes=None,
        native_geometry=rig.native_foot_geometry_for_sampling,
        foot_scale=rig.native_foot_scale_for_sampling)
    assert active and metrics['available']
    assert required['keyframeStationarySampleCount'] == 1
    assert verdict['passed'] is False
    assert verdict['reason'] == 'native_material_playback_clock_unsupported'

    # The rendered proof returns the same typed failure without calling the
    # sampler, so no ValueError can escape into the fit.
    rendered_active, rendered_metrics, rendered_required, rendered_verdict = (
        rendered_native_material_contact_domain(
            rig.names, rig.offsets, one_frame, np.array([.25, .5, .75]),
            cyclic=True, sampling_payload={'coordinates': np.zeros((1, 1))},
            native_geometry=rig.native_foot_geometry_for_sampling,
            foot_scale=rig.native_foot_scale_for_sampling))
    assert rendered_active
    assert rendered_metrics['available'] is False
    assert rendered_required == {}
    assert rendered_verdict['passed'] is False
    assert (rendered_verdict['reason']
            == 'native_material_playback_clock_unsupported')


def test_reuse_proof_rejects_renderer_invalid_schema_and_loop_semantics():
    rig, tracks, sampling = _rendered_fixture()
    raw = _raw_native_metrics(tracks)
    cursors = _production_cursors(len(rig.initial), cyclic=False)
    _, rendered, _, _ = rendered_native_material_contact_domain(
        rig.names, rig.offsets, tracks, cursors, cyclic=False,
        sampling_payload=sampling,
        native_geometry=rig.native_foot_geometry_for_sampling,
        foot_scale=rig.native_foot_scale_for_sampling)
    non_cyclic = _reuse_payload(
        tracks, raw, rendered=rendered, cyclic=False, rig=rig)
    assert native_typed_material_reuse_proof(non_cyclic) is True
    # Playback treats a truthy loop flag as cyclic; reuse must use the same
    # clock, so this 12-sample proof cannot satisfy the 15-sample cyclic one.
    truthy_loop = _reuse_payload(tracks, raw, rendered=rendered)
    truthy_loop['loop'] = {'enabled': 1}
    assert native_typed_material_reuse_proof(truthy_loop) is False
    # The renderer rejects a non-int version and unknown top-level fields.
    assert native_typed_material_reuse_proof(
        _reuse_payload({**tracks, 'version': 2.0}, raw,
                       rendered=rendered, cyclic=False)) is False
    assert native_typed_material_reuse_proof(
        _reuse_payload({**tracks, 'extra': True}, raw,
                       rendered=rendered, cyclic=False)) is False


def test_rendered_sampling_uses_canonical_mirrored_legs():
    rig, tracks, sampling = _rendered_fixture()
    plain = _native_sampling_rig(_artifact_payload(rig, tracks, legs=None))
    cursors = np.array([.5])
    mirrored_points = sample_rig(
        {**sampling, 'contactFootTracks': tracks}, cursors, wrap=True)
    plain_points = sample_rig(
        {**plain, 'contactFootTracks': tracks}, cursors, wrap=True)
    left_knee = rig.names.index('left_knee')
    right_knee = rig.names.index('right_knee')
    assert np.max(np.linalg.norm(
        mirrored_points[:, left_knee] - plain_points[:, left_knee],
        axis=-1)) > 1e-4
    # The mirrored canonical execution only owns the inactive opposite leg.
    np.testing.assert_allclose(
        mirrored_points[:, right_knee], plain_points[:, right_knee], atol=1e-12)


def test_rendered_domain_uses_caller_supplied_geometry_and_scale():
    rig, tracks, sampling = _rendered_fixture()
    # Remove the rig-attached fallbacks: only the explicit arguments can
    # provide the calibrated shoe geometry the sampler requires.
    bare = {key: value for key, value in sampling.items()
            if key not in ('_nativeFootGeometryForSampling',
                           '_nativeFootScaleForSampling')}
    cursors = np.array([.5])
    active, metrics, required, verdict = (
        rendered_native_material_contact_domain(
            rig.names, rig.offsets, tracks, cursors, cyclic=True,
            sampling_payload=bare,
            native_geometry=rig.native_foot_geometry_for_sampling,
            foot_scale=rig.native_foot_scale_for_sampling))
    assert active and metrics['available'] and verdict['passed']
    assert required['playbackStationarySampleCount'] == 1


def test_fresh_fit_subframe_clock_handles_single_frame_noncyclic_without_raising():
    """A one-frame non-cyclic clip has no quarter-frame interval to sample."""
    rig, _tracks, _sampling = _rendered_fixture()
    playback_rig = _sampling_payload(rig, rig.initial)
    # ``count - 1 == 0`` for a single non-cyclic frame: the old unconditional
    # ``sample_rig_coordinates`` call reshaped an empty cursor array and raised.
    empty = sample_fresh_fit_subframe_points(
        rig, playback_rig, np.array([]), cyclic=False)
    assert empty.shape == (0, len(rig.names), 3)
    # A supported clock still decodes the shared quarter-frame playback points.
    supported = sample_fresh_fit_subframe_points(
        rig, playback_rig, _production_cursors(len(rig.initial), cyclic=True),
        cyclic=True)
    assert supported.shape == (15, len(rig.names), 3)


@pytest.mark.parametrize('clock', ['coordinates', 'frames', 'materialFrames'])
def test_typed_reuse_proof_requires_serialized_clocks_to_match_track_clock(clock):
    rig, tracks, sampling = _rendered_fixture()
    cursors = _production_cursors(len(rig.initial), cyclic=True)
    _, rendered, _, _ = rendered_native_material_contact_domain(
        rig.names, rig.offsets, tracks, cursors, cyclic=True,
        sampling_payload=sampling,
        native_geometry=rig.native_foot_geometry_for_sampling,
        foot_scale=rig.native_foot_scale_for_sampling)
    payload = _reuse_payload(
        tracks, _raw_native_metrics(tracks), rendered=rendered, rig=rig)
    # The real payload is admissible while all serialized clocks agree.
    assert native_typed_material_reuse_proof(payload) is True
    if clock == 'coordinates':
        payload['fixedRig']['coordinates'] = (
            payload['fixedRig']['coordinates'][:-1])
    elif clock == 'frames':
        payload['frames'] = payload['frames'][:-1]
    else:
        material = payload['fixedRig']['materialFrames']
        material['referenceCoordinates'] = material['referenceCoordinates'][:-1]
    # The track active length disagrees with the serialized clock the renderer
    # samples; reuse must fail closed instead of admitting an unrenderable fit.
    assert native_typed_material_reuse_proof(payload) is False


def test_typed_reuse_proof_rejects_malformed_or_empty_serialized_clocks():
    rig, tracks, sampling = _rendered_fixture()
    cursors = _production_cursors(len(rig.initial), cyclic=True)
    _, rendered, _, _ = rendered_native_material_contact_domain(
        rig.names, rig.offsets, tracks, cursors, cyclic=True,
        sampling_payload=sampling,
        native_geometry=rig.native_foot_geometry_for_sampling,
        foot_scale=rig.native_foot_scale_for_sampling)
    payload = _reuse_payload(
        tracks, _raw_native_metrics(tracks), rendered=rendered, rig=rig)

    empty_coordinates = deepcopy(payload)
    empty_coordinates['fixedRig']['coordinates'] = []
    assert native_typed_material_reuse_proof(empty_coordinates) is False

    empty_frames = deepcopy(payload)
    empty_frames['frames'] = []
    assert native_typed_material_reuse_proof(empty_frames) is False

    malformed_material = deepcopy(payload)
    malformed_material['fixedRig']['materialFrames'] = {}
    assert native_typed_material_reuse_proof(malformed_material) is False

    malformed_coordinates = deepcopy(payload)
    malformed_coordinates['fixedRig']['coordinates'] = 'not-a-clock'
    assert native_typed_material_reuse_proof(malformed_coordinates) is False
