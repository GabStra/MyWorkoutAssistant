from pathlib import Path

import numpy as np
import pytest


def test_definition_contract_materializes_observed_body_support_without_pose_constraints():
    from exercise_motion_pkg.body_support_observation import materialize_body_support

    joints = {
        'pelvis': [0., 0., 0.], 'left_hip': [-0.2, 0., 0.],
        'right_hip': [0.2, 0., 0.], 'left_shoulder': [-0.3, 0., 0.],
        'right_shoulder': [0.3, 0., 0.], 'neck': [0., 0.1, 0.],
        'spine1': [0., 0., 0.], 'spine2': [0., 0.03, 0.],
        'spine3': [0., 0.06, 0.],
    }
    payload = {
        'jointNames': list(joints), 'frames': [{'joints': joints}],
        'sourceFootSupportEvidence': {'bodySupportObservation': {
            'status': 'observed', 'sourceVideoSha256': 'source',
            'observation': {
                'pelvisAndUpperBackSameSurface': True,
                'pelvis': 'stationary_support', 'upperBack': 'stationary_support',
                'torsoSurface': 'horizontal',
            },
        }},
    }
    source_pose = {'frames': [{'joints': joints} for _ in range(8)]}
    contract = {
        'contractScope': 'definition_only', 'primaryMovingRegions': ['upper_limb'],
        'referenceRegions': ['torso'],
    }

    materialize_body_support(payload, source_pose, contract)

    assert payload['sourceFootSupportEvidence']['bodySupport']['status'] == 'confirmed'


def test_pixel_support_tracks_remove_detector_drift_without_freezing_real_travel(tmp_path):
    import cv2
    from exercise_motion_pkg.source_support_tracking import observe_support_relative_tracks

    video = tmp_path / 'source.avi'
    writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*'MJPG'), 10., (128, 96))
    assert writer.isOpened()
    texture = np.random.default_rng(7).integers(0, 256, (20, 20, 3), dtype=np.uint8)
    frames = []
    for index in range(12):
        image = np.zeros((96, 128, 3), dtype=np.uint8)
        image[20:40, 20+index:40+index] = texture
        image[65:85, 85:105] = texture
        writer.write(image)
        jitter = 5. if index % 2 else 0.
        joints = {'left_hip': [(28+index+jitter)/128, 30/96, 0.],
                  'right_hip': [(32+index+jitter)/128, 30/96, 0.],
                  'right_ankle': [95/128, 75/96, 0.]}
        frames.append({'sourceTimeSec': index/10., 'joints': joints,
                       'jointConfidence': {name: .99 for name in joints}})
    writer.release()
    pose = {'coordinateSpace': 'normalized_image_xy', 'imageWidth': 128, 'imageHeight': 96,
            'frames': frames, 'sourceTimeOriginSec': 0.}
    import hashlib
    observation = {'status': 'observed', 'sourceVideoSha256': hashlib.sha256(video.read_bytes()).hexdigest(),
                   'observation': {'pelvis': 'stationary_support', 'rightFoot': 'stationary_full_sole',
                                   'rightFootSurface': 'ground'}}
    result = observe_support_relative_tracks(video, pose, observation, cache_dir=tmp_path/'cache')
    assert result['available']
    track = result['tracks']['right_ankle']
    deltas = np.array([row['sourceDelta'] for row in track])
    # Actual eleven-pixel travel survives; detector-only alternating jitter does not.
    np.testing.assert_allclose(np.diff(deltas[:, 0])*96, 1., atol=.2)
    assert (deltas[-1, 0]-deltas[0, 0])*96 == pytest.approx(11., abs=.3)
    assert observe_support_relative_tracks(video, pose, observation, cache_dir=tmp_path/'cache') == result
    bad_observation = {**observation, 'sourceVideoSha256': 'wrong-video'}
    assert not observe_support_relative_tracks(video, pose, bad_observation, cache_dir=tmp_path/'cache')['available']


def test_unobservable_pixel_support_keeps_detector_evidence(tmp_path):
    import cv2
    from exercise_motion_pkg.source_support_tracking import observe_support_relative_tracks
    import hashlib

    video = tmp_path/'blank.avi'
    writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*'MJPG'), 10., (128, 96))
    for _ in range(8):
        writer.write(np.zeros((96, 128, 3), dtype=np.uint8))
    writer.release()
    joints = {'left_hip': [.3, .3, 0.], 'right_hip': [.4, .3, 0.], 'right_ankle': [.8, .8, 0.]}
    pose = {'coordinateSpace': 'normalized_image_xy', 'imageWidth': 128, 'imageHeight': 96,
            'frames': [{'sourceTimeSec': i/10., 'joints': joints,
                        'jointConfidence': {n: .99 for n in joints}} for i in range(8)]}
    observation = {'status': 'observed', 'sourceVideoSha256': hashlib.sha256(video.read_bytes()).hexdigest(),
                   'observation': {'pelvis': 'stationary_support', 'rightFoot': 'stationary_full_sole',
                                   'rightFootSurface': 'ground'}}
    result = observe_support_relative_tracks(video, pose, observation, cache_dir=tmp_path/'cache')
    assert result['available'] is False
    assert result.get('tracks', {}) == {}
