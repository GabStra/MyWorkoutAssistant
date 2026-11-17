from pathlib import Path

import numpy as np
import pytest

from exercise_motion_pkg.body_support_observation import (
    CONTACT_TIMELINE_POLICY_VERSION,
    POLICY_VERSION,
)


def test_material_identity_rejects_occluder_without_erasing_real_foot_travel():
    import cv2
    from exercise_motion_pkg.source_support_tracking import _material_identity_tracks

    texture = np.random.default_rng(41).integers(30, 220, (18, 42), dtype=np.uint8)
    for travel in (0, 2):
        images, joints = [], []
        for index in range(9):
            shift = travel*index
            image = np.zeros((100, 140), np.uint8)
            image[60:78, 40+shift:82+shift] = texture
            # A textured hand crosses the heel at the first exposure.
            hand_y = 58-4*index
            image[hand_y:hand_y+8, 41+shift:49+shift] = 255
            images.append(image)
            row = {}
            for name, point in [('ankle', (49+shift, 61)), ('heel', (42+shift, 73)),
                                ('toe', (79+shift, 73)), ('wrist', (45+shift, hand_y+4))]:
                row['left_'+name] = {'image': [point[0]/140, point[1]/100], 'confidence': .99}
            joints.append(row)
        groups = _material_identity_tracks(images, joints, 'left', np.array([140, 100]), cv2)
        assert groups is not None
        assert groups['heel']['seedFrameOffset'] > 0
        centers = groups['heel']['identityTracks'][:, :, 0].mean(axis=1)
        assert np.max(np.abs((centers-centers[0])[:, 1])) < 1.
        assert abs(float(centers[-1, 0]-centers[0, 0])-travel*8) < 1.


def test_definition_contract_materializes_observed_body_support_without_pose_constraints():
    from exercise_motion_pkg.body_support_observation import materialize_body_support

    digest = 'source'
    joints = {
        'pelvis': [0., 0., 0.], 'left_hip': [-0.2, 0., 0.],
        'right_hip': [0.2, 0., 0.], 'left_shoulder': [-0.3, 0., 0.],
        'right_shoulder': [0.3, 0., 0.], 'neck': [0., 0.1, 0.],
        'spine1': [0., 0., 0.], 'spine2': [0., 0.03, 0.],
        'spine3': [0., 0.06, 0.],
    }
    # Physical support authority is exact-time direct contact on the observed
    # surface, not a coarse stationary summary.
    direct_contact_samples = [
        {'sampleId': f'{joint}-{index}', 'sourceTimeSec': index / 30.,
         'sourceFrameIndex': index, 'sourcePoseFrameIndex': index, 'sourceFps': 30.,
         'side': side, 'landmark': 'joint', 'jointName': joint,
         'contactState': 'direct_contact', 'surface': 'floor', 'visible': True,
         'sourceTrackStationary': True}
        for joint, side in (('pelvis', 'center'), ('left_shoulder', 'left'),
                            ('right_shoulder', 'right'))
        for index in (0, 1)
    ]
    payload = {
        'jointNames': list(joints), 'frames': [{'joints': joints}],
        'sourceFootSupportEvidence': {'bodySupportObservation': {
            'status': 'observed', 'sourceVideoSha256': digest,
            'source': 'exact_source_visual_support_observation',
            'policyVersion': POLICY_VERSION,
            'observation': {
                'pelvisAndUpperBackSameSurface': True,
                'pelvis': 'stationary_support', 'upperBack': 'stationary_support',
                'pelvisContactSurface': 'floor', 'upperBackContactSurface': 'floor',
                'torsoSurface': 'horizontal',
            },
            'contactTimeline': {
                'schemaVersion': 1, 'policyVersion': CONTACT_TIMELINE_POLICY_VERSION,
                'source': 'exact_source_visual_contact_timeline',
                'sourceClock': 'video_frame_zero_seconds', 'status': 'observed',
                'sourceVideoSha256': digest, 'samples': direct_contact_samples,
            },
        }},
    }
    source_pose = {'sourceVideoSha256': digest,
                   'frames': [{'sourceTimeSec': index / 30., 'joints': joints}
                              for index in range(8)]}
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
    'policyVersion': POLICY_VERSION,
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


def test_hand_support_tracks_reject_carried_motion_and_allow_camera_motion(tmp_path):
    import cv2
    import hashlib
    from exercise_motion_pkg.source_support_tracking import observe_support_relative_tracks

    video = tmp_path / 'hand-support.avi'
    writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*'MJPG'), 10., (192, 128))
    assert writer.isOpened()
    rng = np.random.default_rng(18)
    background = rng.integers(0, 256, (128, 192, 3), dtype=np.uint8)
    patch = rng.integers(0, 256, (40, 40, 3), dtype=np.uint8)
    frames = []
    for index in range(12):
        image = background.copy()
        image[15:55, 20 + index:60 + index] = patch
        image[15:55, 115:155] = patch
        image[70:110, 56 + index:96 + index] = patch
        camera_shift = index // 2
        writer.write(np.roll(image, camera_shift, axis=1))
        joints = {'left_wrist': [(40 + index + camera_shift) / 192, 35 / 128, 0.],
                  'right_wrist': [(135 + camera_shift) / 192, 35 / 128, 0.],
                  'left_hip': [(72 + index + camera_shift) / 192, 90 / 128, 0.],
                  'right_hip': [(80 + index + camera_shift) / 192, 90 / 128, 0.]}
        frames.append({'sourceTimeSec': index / 10., 'joints': joints,
                       'jointConfidence': {name: .99 for name in joints}})
    writer.release()
    pose = {'coordinateSpace': 'normalized_image_xy', 'sourceTimeOriginSec': 0., 'frames': frames}
    observation = {'status': 'observed', 'source': 'exact_source_visual_support_observation',
                   'policyVersion': POLICY_VERSION, 'sourceVideoSha256': hashlib.sha256(video.read_bytes()).hexdigest(),
                   'observation': {'leftHand': 'stationary_support', 'rightHand': 'stationary_support',
                                   'leftHandContactSurface': 'fixed_bar', 'rightHandContactSurface': 'fixed_bar'}}

    result = observe_support_relative_tracks(video, pose, observation, cache_dir=tmp_path / 'cache')

    evidence = result['stationaryContactEvidence']
    assert evidence['left_wrist']['available']
    assert not evidence['left_wrist']['passed']
    assert evidence['left_wrist']['maximumImageTravelPixels'] > evidence['left_wrist']['limitPixels']
    assert evidence['left_wrist']['movesWithBody']
    assert evidence['right_wrist']['available']
    assert evidence['right_wrist']['passed']
    assert evidence['right_wrist']['maximumImageTravelPixels'] < .5
    assert not evidence['right_wrist']['movesWithBody']


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
    'policyVersion': POLICY_VERSION,
                   'observation': {'pelvis': 'stationary_support', 'rightFoot': 'stationary_full_sole',
                                   'rightFootSurface': 'ground'}}
    result = observe_support_relative_tracks(video, pose, observation, cache_dir=tmp_path/'cache')
    assert result['available'] is False
    assert result.get('tracks', {}) == {}


@pytest.mark.parametrize(('width', 'height', 'toe'), [
    (1920, 1080, [.3, .4]), (1920, 1080, [.2, .5]), (1080, 1920, [.2, .5]),
])
def test_material_spread_tolerance_uses_pixel_geometry(tmp_path, monkeypatch, width, height, toe):
    from exercise_motion_pkg import source_support_tracking as tracking
    from exercise_motion_pkg.foot_contact_observation import _corroborate_observed_full_sole_material

    video = tmp_path / 'source.mp4'
    video.touch()
    frame = {'joints': {
        'right_heel': {'image': [.2, .4], 'confidence': .99},
        'right_toe': {'image': toe, 'confidence': .99},
    }}
    observations = {'imageWidth': width, 'imageHeight': height, 'frames': [frame] * 3}
    patch = {'sourceFrameCount': 3, 'sourceTimesSec': [0., .1, .2],
             'feet': {'right': {'states': ['full_sole'] * 3}},
             'contacts': [{'jointName': 'right_foot', 'contactState': 'full_sole',
                           'contactMotion': 'unknown', 'startRatio': 0., 'endRatio': 1.}]}
    captured = []
    monkeypatch.setattr(tracking, 'observe_foot_material_episodes',
                        lambda _video, _observations, _patch, episodes, **kwargs: captured.extend(episodes))
    _corroborate_observed_full_sole_material(video, observations, patch)
    expected = .15 * np.linalg.norm((np.asarray(toe) - [.2, .4]) * [width, height])
    assert captured[0]['maximumDisplacementPixels'] == pytest.approx(expected)


def test_foot_material_tracks_are_exact_window_and_fail_closed(tmp_path, monkeypatch):
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

    camera_video = tmp_path / 'panned-shoe.avi'
    writer = cv2.VideoWriter(str(camera_video), cv2.VideoWriter_fourcc(*'MJPG'), fps, (width, height))
    assert writer.isOpened()
    for index, image in enumerate(rendered_frames):
        transform = np.asarray([[1., 0., index], [0., 1., 0.]])
        writer.write(cv2.warpAffine(image, transform, (width, height), borderMode=cv2.BORDER_REFLECT))
    writer.release()
    camera_digest = hashlib.sha256(camera_video.read_bytes()).hexdigest()
    camera_observations = {
        **observations, 'sourceVideoSha256': camera_digest,
        'frames': [{**frame, 'joints': {
            name: {**point, 'image': [point['image'][0] + index / width, point['image'][1]]}
            for name, point in frame['joints'].items()
        }} for index, frame in enumerate(observation_frames)],
    }
    panned = observe_foot_material_episodes(
        camera_video, camera_observations, {**patch, 'sourceVideoSha256': camera_digest},
        [episode], cache_dir=tmp_path/'cache')
    camera_heel = panned['episodes'][0]['heel']
    assert panned['episodes'][0]['passed'] is True
    assert camera_heel['reference'] == 'registered_scene'
    assert camera_heel['maximumRawDisplacementPixels'] > episode['maximumDisplacementPixels']

    from exercise_motion_pkg import camera_stability
    background_transform = camera_stability.estimate_background_camera_transform
    registration_calls = 0

    def lose_registration(**kwargs):
        nonlocal registration_calls
        registration_calls += 1
        return ({'status': 'unavailable'} if registration_calls == 3
                else background_transform(**kwargs))

    with monkeypatch.context() as local_patch:
        local_patch.setattr(camera_stability, 'estimate_background_camera_transform',
                            lose_registration)
        unregistered = observe_foot_material_episodes(
            camera_video, camera_observations, {**patch, 'sourceVideoSha256': camera_digest},
            [episode], cache_dir=tmp_path/'unregistered-camera-cache')['episodes'][0]
    assert unregistered['heel']['coverageRatio'] == 1.
    assert unregistered['heel']['maximumRawDisplacementPixels'] > episode['maximumDisplacementPixels']
    assert unregistered['heel']['reference'] == 'source_image'
    assert unregistered['status'] == 'unresolved'
    assert unregistered['passed'] is None
    assert unregistered['reason'] == 'background_camera_registration_incomplete'
    assert unregistered['cameraRegistration']['status'] == 'incomplete'

    optical_flow = cv2.calcOpticalFlowPyrLK

    def lose_features(*args, **kwargs):
        moved, status, error = optical_flow(*args, **kwargs)
        if status is not None:
            # Drop one side of the texture while retaining sufficient static features.
            points = args[2][:, 0]
            status[points[:, 0] > np.quantile(points[:, 0], .8)] = 0
        return moved, status, error

    with monkeypatch.context() as local_patch:
        local_patch.setattr(cv2, 'calcOpticalFlowPyrLK', lose_features)
        dropout = observe_foot_material_episodes(
            video, observations, patch, [episode], cache_dir=tmp_path/'dropout-cache')
    assert dropout['episodes'][0]['passed'] is True
    for part in ('heel', 'toe'):
        assert dropout['episodes'][0][part]['maximumDisplacementPixels'] < .05

    drifting = observe_foot_material_episodes(
        video, observations, patch,
        [{**episode, 'startFrame': 8, 'endFrame': 13,
          'startTimeSec': origin + .8, 'endTimeSec': origin + 1.3}],
        cache_dir=tmp_path/'cache')
    assert drifting['episodes'][0]['status'] == 'failed'
    assert drifting['episodes'][0]['passed'] is False
    assert drifting['episodes'][0]['heel']['reference'] == 'registered_scene'

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
