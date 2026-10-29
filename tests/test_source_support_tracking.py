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
            'source': 'exact_source_visual_support_observation',
            'policyVersion': 5,
            'observation': {
                'pelvisAndUpperBackSameSurface': True,
                'pelvis': 'stationary_support', 'upperBack': 'stationary_support',
                'pelvisContactSurface': 'floor', 'upperBackContactSurface': 'floor',
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
    observation = {'status': 'observed', 'source': 'exact_source_visual_support_observation',
        'sourceVideoSha256': hashlib.sha256(video.read_bytes()).hexdigest(),
    'policyVersion': 5,
                   # A squat has planted feet but no supported pelvis. The
                   # pixel tracker measures hip travel relative to that foot.
                   'observation': {'rightFoot': 'stationary_full_sole',
                                   'rightFootSurface': 'ground'}}
    result = observe_support_relative_tracks(video, pose, observation, cache_dir=tmp_path/'cache')
    assert result['available']
    assert result['hipCenterCoverage'] == {'observed': len(frames), 'expected': len(frames)}
    assert result['trackCoverage']['right_ankle'] == {'observed': len(frames), 'expected': len(frames)}
    track = result['tracks']['right_ankle']
    deltas = np.array([row['sourceDelta'] for row in track])
    # Actual eleven-pixel travel survives; detector-only alternating jitter does not.
    np.testing.assert_allclose(np.diff(deltas[:, 0])*96, 1., atol=.2)
    assert (deltas[-1, 0]-deltas[0, 0])*96 == pytest.approx(11., abs=.3)
    assert observe_support_relative_tracks(video, pose, observation, cache_dir=tmp_path/'cache') == result
    bad_observation = {**observation, 'sourceVideoSha256': 'wrong-video'}
    assert not observe_support_relative_tracks(video, pose, bad_observation, cache_dir=tmp_path/'cache')['available']
    unsupported = {**observation, 'observation': {'rightFoot': 'moving'}}
    result_without_planted_foot = observe_support_relative_tracks(
        video, pose, unsupported, cache_dir=tmp_path/'cache')
    assert result_without_planted_foot['available'] is False
    assert result_without_planted_foot['reason'] == 'support_observation_unavailable'


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
    observation = {'status': 'observed', 'source': 'exact_source_visual_support_observation',
        'sourceVideoSha256': hashlib.sha256(video.read_bytes()).hexdigest(),
    'policyVersion': 5,
                   'observation': {'pelvis': 'stationary_support', 'rightFoot': 'stationary_full_sole',
                                   'rightFootSurface': 'ground'}}
    result = observe_support_relative_tracks(video, pose, observation, cache_dir=tmp_path/'cache')
    assert result['available'] is False
    assert result.get('tracks', {}) == {}


def test_foot_material_tracks_are_exact_window_and_fail_closed(tmp_path):
    import hashlib
    import cv2
    from exercise_motion_pkg.source_support_tracking import observe_foot_material_episodes

    video = tmp_path / 'shoe.avi'
    fps, width, height, count, origin = 10., 160, 120, 24, 2.5
    writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*'MJPG'), fps,
                             (width, height))
    assert writer.isOpened()
    rng = np.random.default_rng(314)
    floor = rng.integers(0, 35, (120, 160, 3), dtype=np.uint8)
    shoe_layer = np.zeros_like(floor)
    shoe_layer[68:92, 48:104] = rng.integers(40, 220, (24, 56, 3), dtype=np.uint8)
    shoe_mask = np.zeros((height, width), dtype=np.uint8)
    shoe_mask[68:92, 48:104] = 255
    observation_frames = []
    rendered_frames = []
    for index in range(count):
        shift = 0 if index < 8 else min(index - 7, 6)
        angle = 0. if index < 14 else (index - 13) * 1.5
        transform = cv2.getRotationMatrix2D((76, 80), angle, 1.)
        transform[0, 2] += shift
        warped_shoe = cv2.warpAffine(shoe_layer, transform, (width, height))
        warped_mask = cv2.warpAffine(shoe_mask, transform, (width, height),
                                     flags=cv2.INTER_NEAREST)
        image = floor.copy()
        image[warped_mask > 0] = warped_shoe[warped_mask > 0]
        rendered_frames.append(image.copy())
        writer.write(image)
        projected = cv2.transform(np.asarray([[[54., 72.], [50., 80.], [101., 80.]]],
                                             dtype=np.float32), transform)[0]
        ankle_xy, heel_xy, toe_xy = projected
        joints = {
            'right_ankle': {'image': [float(ankle_xy[0]/width), float(ankle_xy[1]/height)], 'confidence': .98},
            'right_heel': {'image': [float(heel_xy[0]/width), float(heel_xy[1]/height)], 'confidence': .99},
            'right_toe': {'image': [float(toe_xy[0]/width), float(toe_xy[1]/height)], 'confidence': .99},
        }
        observation_frames.append({'timeSeconds': index/fps, 'joints': joints})
    writer.release()
    source_sha = hashlib.sha256(video.read_bytes()).hexdigest()
    observations = {
        'available': True, 'sourceVideoSha256': source_sha,
        'imageWidth': width, 'imageHeight': height, 'fps': fps,
        'sourceTimeOriginSec': origin, 'frames': observation_frames,
    }
    patch = {
        'available': True, 'sourceVideoSha256': source_sha,
        'sourceTimeBasis': 'absolute_source_video',
        'sourceTimeOriginSec': origin, 'sourceFps': fps,
        'sourceTimesSec': [origin + index/fps for index in range(count)],
        'feet': {'right': {'states': ['full_sole'] * count}},
    }
    episode = {
        'episodeId': 'stationary-then-travel', 'side': 'right',
        'contactState': 'full_sole', 'startFrame': 2, 'endFrame': 7,
        'startTimeSec': origin + .2, 'endTimeSec': origin + .7,
        'maximumDisplacementPixels': 2.,
    }
    result = observe_foot_material_episodes(
        video, observations, patch, [episode], cache_dir=tmp_path/'cache')
    stable = result['episodes'][0]
    assert stable['status'] == 'verified'
    assert stable['passed'] is True
    assert len(stable['timedMaterialCenters']) == 6
    assert stable['timedMaterialCenters'][0]['sourceTimeSec'] == pytest.approx(2.7)
    assert stable['heel']['coverageRatio'] == stable['toe']['coverageRatio'] == 1.

    drifting = observe_foot_material_episodes(
        video, observations, patch,
        [{**episode, 'startFrame': 8, 'endFrame': 13,
          'startTimeSec': origin + .8, 'endTimeSec': origin + 1.3}],
        cache_dir=tmp_path/'cache')
    assert drifting['episodes'][0]['status'] == 'failed'
    assert drifting['episodes'][0]['passed'] is False

    pivot = observe_foot_material_episodes(
        video, observations, patch,
        [{**episode, 'startFrame': 14, 'endFrame': 23,
          'startTimeSec': origin + 1.4, 'endTimeSec': origin + 2.3}],
        cache_dir=tmp_path/'cache')
    assert pivot['episodes'][0]['status'] in {'failed', 'unresolved'}
    assert pivot['episodes'][0]['passed'] is not True
    assert pivot['episodes'][0]['heading']['maximumHeadingChangeDegrees'] > 10.

    occluded_video = tmp_path / 'occluded-shoe.avi'
    writer = cv2.VideoWriter(occluded_video.as_posix(), cv2.VideoWriter_fourcc(*'MJPG'),
                             fps, (width, height))
    for index, image in enumerate(rendered_frames):
        if index >= 4:
            image = image.copy()
            image[64:98, 44:108] = 15
        writer.write(image)
    writer.release()
    occluded_sha = hashlib.sha256(occluded_video.read_bytes()).hexdigest()
    occluded_result = observe_foot_material_episodes(
        occluded_video,
        {**observations, 'sourceVideoSha256': occluded_sha},
        {**patch, 'sourceVideoSha256': occluded_sha},
        [episode], cache_dir=tmp_path/'cache')
    assert occluded_result['episodes'][0]['status'] == 'unresolved'
    assert occluded_result['episodes'][0]['passed'] is None

    wrong_clock = {**patch, 'sourceTimesSec': [index/fps for index in range(count)]}
    mismatch = observe_foot_material_episodes(
        video, observations, wrong_clock, [episode], cache_dir=tmp_path/'cache')
    assert mismatch['reason'] == 'source_native_clock_mismatch'

    airborne = {**patch, 'feet': {'right': {'states': ['unknown'] * count}}}
    not_applicable = observe_foot_material_episodes(
        video, observations, airborne, [episode], cache_dir=tmp_path/'cache')
    assert not_applicable['episodes'][0]['status'] == 'not_applicable'
