import json
from pathlib import Path
import numpy as np
from exercise_motion_pkg.sequence_stabilization import (
    SkeletalCoordinates, contact_mask, denoise_features, stabilize_exported_sequence,
)


def test_small_independent_noise_is_reduced_without_erasing_a_small_deliberate_motion():
    rng = np.random.default_rng(71)
    time = np.arange(180)/30.
    clean = np.zeros((180, 8, 3))
    clean[:, 4, 1] = .01*np.sin(2*np.pi*.4*time)
    noisy = clean.copy()
    noisy[:, 5, 2] = rng.normal(0., .007, len(time))
    result, report = denoise_features(noisy, 30.)
    assert report['changed']
    assert np.std(result[:, 5, 2]) < np.std(noisy[:, 5, 2])*.5
    assert np.ptp(result[:, 4, 1]) >= .99*np.ptp(clean[:, 4, 1])
    assert np.max(abs(result[:, 4, 1]-clean[:, 4, 1])) < .0001


def test_fast_coordinated_motion_is_filtered_at_multiple_sample_rates():
    for fps in (24., 30., 60.):
        time = np.arange(int(6*fps))/fps
        values = np.zeros((len(time), 8, 3))
        for group in range(2, 7):
            values[:, group, 1] = .015*np.sin(2*np.pi*8*time)
        result, report = denoise_features(values, fps)
        interior = slice(int(fps), -int(fps))
        assert report['policy'] == 'animation_bandwidth_v3'
        assert np.linalg.norm(result[interior]) < .02*np.linalg.norm(values[interior])


def test_large_single_frame_spike_is_filtered_without_restoring_its_extreme():
    values = np.zeros((90, 6, 3))
    values[45, 4, 1] = 1.
    result, _ = denoise_features(values, 30.)
    assert result[45, 4, 1] < .25
    assert np.max(abs(np.diff(result[:, 4, 1]))) < .1


def test_parent_coordinates_roundtrip_asymmetric_and_travelling_motion():
    from scipy.spatial.transform import Rotation
    fixture = json.loads((Path(__file__).parent/'fixtures/bulgarian-split-squat-renderer.json').read_text())
    names = list(fixture['frames'][0]['joints'])
    points = np.array([[f['joints'][n] for n in names] for f in fixture['frames']])
    points += np.linspace(0., .7, len(points))[:, None, None]
    rotation = Rotation.from_euler('xyz', [.3, -.8, .1]).as_matrix()
    for data in [points, points@rotation]:
        model = SkeletalCoordinates(data, names)
        np.testing.assert_allclose(model.decode(model.features, data), data, atol=1e-10)
    first, _ = denoise_features(SkeletalCoordinates(points, names).features, fixture['fps'])
    second, _ = denoise_features(SkeletalCoordinates(points@rotation, names).features, fixture['fps'])
    np.testing.assert_allclose(first[:, 3:], second[:, 3:], atol=1e-8)


def test_contact_mask_skips_unrepresented_heel_without_dropping_other_plants():
    names = ['left_ankle', 'left_foot', 'right_ankle', 'right_foot']
    payload = {'sourceFootSupportEvidence': {'contacts': [
        {'jointName': 'left_foot', 'contactState': 'heel_only', 'contactMotion': 'stationary',
         'startFrame': 0, 'endFrame': 9},
        {'jointName': 'right_foot', 'contactState': 'full_sole', 'contactMotion': 'stationary',
         'startFrame': 0, 'endFrame': 9},
    ]}}
    mask = contact_mask(payload, names, 10)
    assert mask is not None
    assert not mask[:, :2].any()
    assert mask[:, 2:].all()


def test_contact_mask_preserves_release_and_unilateral_support():
    names = ['left_ankle', 'left_foot', 'right_ankle', 'right_foot', 'left_hand']
    payload = {'sourceFootSupportEvidence': {'contacts': [
        {'jointName': 'left_foot', 'contactState': 'full_sole', 'contactMotion': 'stationary', 'startFrame': 0, 'endFrame': 3},
        {'jointName': 'right_foot', 'contactState': 'toe_only', 'contactMotion': 'stationary', 'startFrame': 6, 'endFrame': 9},
        {'jointName': 'left_hand', 'contactMotion': 'stationary', 'startFrame': 2, 'endFrame': 5},
    ]}}
    mask = contact_mask(payload, names, 10)
    assert mask[:4, :2].all() and not mask[4:, :2].any()
    assert mask[6:, 3].all() and not mask[:, 2].any()
    assert mask[2:6, 4].all() and not mask[:2, 4].any()


def test_irregular_sampling_and_unresolved_repair_are_retained():
    payload = {'fps': 30., 'frames': [{'timeSec': float(i), 'joints': {}} for i in range(9)]}
    result, report = stabilize_exported_sequence(payload)
    assert result is payload
    assert report['reason'] == 'irregular_sampling_requires_resampling'
    payload['postBakeForefootContactConstraint'] = {'requiresReconstruction': True}
    result, report = stabilize_exported_sequence(payload)
    assert result is payload and report['reason'] == 'upstream_repair_unresolved'

def test_isolated_rapid_periodic_motion_is_filtered_but_slow_motion_remains():
    time = np.arange(180)/30.
    values = np.zeros((180, 8, 3))
    values[:, 5, 2] = .012*np.sin(2*np.pi*6*time)
    values[:, 4, 2] = .012*np.sin(2*np.pi*.5*time)
    result, _ = denoise_features(values, 30.)
    assert np.std(result[30:-30, 5, 2]) < .02*np.std(values[30:-30, 5, 2])
    np.testing.assert_allclose(result[30:-30, 4, 2], values[30:-30, 4, 2], atol=1e-5)


def noisy_stance():
    from copy import deepcopy
    fixture = json.loads((Path(__file__).parent/'fixtures/sequence_stabilization_stance.json').read_text())
    names = list(fixture['joints'])
    rng = np.random.default_rng(193)
    frames = []
    for i in range(60):
        joints = deepcopy(fixture['joints'])
        neck = np.array(joints['neck'])
        direction = np.array(joints['head'])-neck
        angle = .006*np.sin(2*np.pi*.5*i/30.)+rng.normal(0., .009)
        from scipy.spatial.transform import Rotation
        joints['head'] = (neck+Rotation.from_rotvec([angle, 0., 0.]).apply(direction)).tolist()
        frames.append({'timeSec': i/30., 'joints': joints, 'sourceJoints': deepcopy(joints)})
    return {'fps': 30., 'jointNames': names, 'rootJoint': 'pelvis', 'frames': frames,
            'renderFloorY': fixture['renderFloorY']}


def test_complete_sequence_projection_reduces_noise_and_keeps_stationary_supports():
    from exercise_motion_pkg.temporal_quality import body_local_head_direction
    payload = noisy_stance()
    payload['sourceFootSupportEvidence'] = {'contacts': [
        {'jointName': side+'_foot', 'contactState': 'full_sole', 'contactMotion': 'stationary',
         'startRatio': 0., 'endRatio': 1.} for side in ('left', 'right')]}
    result, report = stabilize_exported_sequence(payload)
    assert report['applied'], report
    assert report['noiseImproved'] and report['rangePreserved']
    assert report['maximumBoneLengthErrorMeters'] < .002
    names = payload['jointNames']
    tracks = [np.array([[f['joints'][n] for n in names] for f in p['frames']]) for p in (payload, result)]
    heads = [body_local_head_direction(x, names) for x in tracks]
    assert np.linalg.norm(np.diff(heads[1], n=2, axis=0)) < np.linalg.norm(np.diff(heads[0], n=2, axis=0))*.7
    for side in ('left', 'right'):
        for part in ('ankle', 'foot'):
            index = names.index(side+'_'+part)
            np.testing.assert_array_equal(tracks[0][:, index], tracks[1][:, index])
    result['sequenceStabilization'] = report
    repeated, repeated_report = stabilize_exported_sequence(result)
    assert repeated is result and repeated_report['reused']


def test_projection_without_foot_support_and_bounded_timeout():
    payload = noisy_stance()
    result, report = stabilize_exported_sequence(payload)
    assert report['applied'], report
    timed_out, report = stabilize_exported_sequence(payload, timeout_seconds=0.)
    assert timed_out is payload and report['reason'] == 'bounded_stabilization_timeout'

def test_asymmetric_split_squat_projection_preserves_motion_range():
    fixture = json.loads((Path(__file__).parent/'fixtures/bulgarian-split-squat-renderer.json').read_text())
    fixture['jointNames'] = list(fixture['frames'][0]['joints'])
    fixture['rootJoint'] = 'pelvis'
    for i, frame in enumerate(fixture['frames']):
        frame['timeSec'] = i/fixture['fps']
        frame['sourceJoints'] = frame['joints'].copy()
    result, report = stabilize_exported_sequence(fixture)
    assert report['applied'], report
    assert report['rangePreserved']
    assert report['evidence']['policy'] == 'animation_bandwidth_v3'
    assert result['frames'] != fixture['frames']

def test_bake_preserves_source_joint_order_for_optimizer_packing(monkeypatch):
    from exercise_motion_pkg import bake_and_rank as bake
    payload = noisy_stance()
    expected = list(payload['frames'][0]['sourceJoints'])
    class Captured(Exception):
        pass
    def inspect(source, proposed, **kwargs):
        assert source.joint_names == expected
        assert proposed.joint_names == expected
        raise Captured
    monkeypatch.setattr(bake, 'constrain_to_source_articulation_envelope', inspect)
    import pytest
    with pytest.raises(Captured):
        bake.constrain_baked_payload_to_source_articulation(payload)
