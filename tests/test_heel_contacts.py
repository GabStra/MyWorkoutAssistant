import copy
import hashlib
import json
from types import SimpleNamespace

import numpy as np
import pytest

from exercise_motion_pkg.foot_kinematics import HEEL_BEHIND_ANKLE_RATIO
from exercise_motion_pkg.heel_contacts import heel_contact_tracks


def test_cache_only_foot_landmark_loader_reuses_hash_bound_observation_without_inference(tmp_path, monkeypatch):
    from exercise_motion_pkg import foot_contact_observation as foot

    video = tmp_path / 'source.mp4'
    video.write_bytes(b'exact source bytes')
    digest = hashlib.sha256(video.read_bytes()).hexdigest()
    model_hash = 'a' * 64
    cache_dir = tmp_path / 'foot_landmarks'
    cache_dir.mkdir()
    payload = {
        'available': True,
        'observationCacheVersion': foot.OBSERVATION_CACHE_VERSION,
        'sourceVideoSha256': digest,
        'modelSha256': model_hash,
        'frames': [],
    }
    (cache_dir / f'{digest}.{model_hash[:16]}.v{foot.OBSERVATION_CACHE_VERSION}.json').write_text(
        json.dumps(payload), encoding='utf-8',
    )
    monkeypatch.delenv('EXERCISE_MOTION_FOOT_LANDMARK_MODEL', raising=False)
    monkeypatch.setattr(foot, '_model_asset_path', lambda: tmp_path / 'missing-model.task')
    monkeypatch.setattr(foot, 'observe_foot_landmarks', lambda *args, **kwargs: pytest.fail('inference ran'))

    assert foot.load_cached_foot_landmarks(video) == payload


def test_cache_only_foot_landmark_loader_honors_explicit_model_override(tmp_path, monkeypatch):
    from exercise_motion_pkg import foot_contact_observation as foot

    video = tmp_path / 'source.mp4'
    video.write_bytes(b'exact source bytes')
    digest = hashlib.sha256(video.read_bytes()).hexdigest()
    old_model_hash = 'a' * 64
    new_model = tmp_path / 'override.task'
    new_model.write_bytes(b'current model')
    cache_dir = tmp_path / 'foot_landmarks'
    cache_dir.mkdir()
    payload = {
        'available': True,
        'observationCacheVersion': foot.OBSERVATION_CACHE_VERSION,
        'sourceVideoSha256': digest,
        'modelSha256': old_model_hash,
        'frames': [],
    }
    (cache_dir / f'{digest}.{old_model_hash[:16]}.v{foot.OBSERVATION_CACHE_VERSION}.json').write_text(
        json.dumps(payload), encoding='utf-8',
    )
    monkeypatch.setenv('EXERCISE_MOTION_FOOT_LANDMARK_MODEL', str(new_model))
    monkeypatch.setattr(foot, '_model_asset_path', lambda: new_model)

    assert foot.load_cached_foot_landmarks(video) is None


def test_observed_patch_keeps_timed_source_ankle_support_without_promoting_whole_foot(monkeypatch):
    from exercise_motion_pkg import foot_contact_observation as foot

    states = ['unknown'] * 12
    states[4:10] = ['full_sole'] * 6
    evidence = {
        'feet': {'right': {'jointName': 'right_ankle', 'continuousSupport': False}},
        'contacts': [{
            'jointName': 'right_ankle', 'supportKind': 'foot',
            'contactMotion': 'stationary', 'startRatio': 4 / 11, 'endRatio': 9 / 11,
            'sourceStartSample': 4, 'sourceEndSample': 9,
            'sourceStartTimeSec': 4 / 30, 'sourceEndTimeSec': 9 / 30,
            'sourceTimeBasis': 'absolute_source_video', 'confidence': 0.8,
        }],
        'sourceVideoSha256': 'exact-source-hash',
    }
    patch = {
        'available': True, 'sourceFrameCount': len(states),
        'sourceFps': 30., 'sourceTimeBasis': 'absolute_source_video',
        'sourceTimeOriginSec': 0., 'sourceVideoDurationSec': len(states) / 30.,
        'sourceVideoSha256': 'exact-source-hash',
        'sourceTimesSec': [i / 30 for i in range(len(states))],
        'feet': {'right': {'states': states}}, 'contacts': [],
    }
    monkeypatch.setattr(foot, 'classify_foot_contacts', lambda *args, **kwargs: patch)

    result = foot.add_observed_foot_contacts(evidence, {}, {'frames': []})

    retained = [item for item in result['contacts'] if item.get('source') ==
                'source_pose_stationary_ankle_excluding_observed_airborne']
    assert len(retained) == 1
    assert retained[0]['jointName'] == 'right_ankle'
    assert retained[0]['anchorKind'] == 'ankle'
    assert 'contactState' not in retained[0]
    assert retained[0]['startFrame'] == 4 and retained[0]['endFrame'] == 9


def test_sparse_source_ankle_contact_uses_absolute_native_clock_not_sample_ratio(monkeypatch):
    from exercise_motion_pkg import foot_contact_observation as foot

    source_fps, native_count, source_pose_count = 29.97, 228, 58
    digest = 'manmaker-source-sha'
    states = ['unknown'] * 183 + ['full_sole'] * (native_count - 183)
    start_time = 184 / source_fps
    end_time = native_count / source_fps
    source_contact = {
        'jointName': 'right_ankle', 'supportKind': 'foot',
        'contactMotion': 'stationary', 'startRatio': 46 / 57, 'endRatio': 1.0,
        'sourceStartSample': 46, 'sourceEndSample': 57,
        'sourceStartTimeSec': start_time, 'sourceEndTimeSec': end_time,
        'sourceTimeBasis': 'absolute_source_video', 'confidence': .8,
    }
    evidence = {'feet': {'right': {'continuousSupport': False}},
                'contacts': [source_contact], 'sourceVideoSha256': digest}
    patch = {
        'available': True, 'sourceFrameCount': native_count,
        'sourceFps': source_fps, 'sourceTimeBasis': 'absolute_source_video',
        'sourceTimeOriginSec': 0., 'sourceVideoDurationSec': native_count / source_fps,
        'sourceVideoSha256': digest,
        'sourceTimesSec': [index / source_fps for index in range(native_count)],
        'feet': {'right': {'states': states}},
        'contacts': [{
            'jointName': 'right_foot', 'contactState': 'full_sole',
            'contactMotion': 'stationary', 'startFrame': 183, 'endFrame': 227,
            'startRatio': 183 / 227, 'endRatio': 1.0,
            'source': 'observed_foot_patch',
        }],
    }
    monkeypatch.setattr(foot, 'classify_foot_contacts', lambda *args, **kwargs: patch)
    source_pose = {
        'frames': [{'sourceTimeSec': (index * 4) / source_fps}
                   for index in range(source_pose_count)],
    }

    result = foot.add_observed_foot_contacts(evidence, {}, source_pose)

    retained = [item for item in result['contacts'] if item.get('anchorKind') == 'ankle']
    retained_fullsole = [item for item in result['contacts']
                         if item.get('contactState') == 'full_sole']
    assert round(source_contact['startRatio'] * (native_count - 1)) == 183
    assert len(retained) == 1
    assert (retained[0]['startFrame'], retained[0]['endFrame']) == (184, 227)
    assert retained[0]['sourcePoseStartTimeSec'] == pytest.approx(start_time)
    assert len(retained_fullsole) == 1
    assert (retained_fullsole[0]['startFrame'], retained_fullsole[0]['endFrame']) == (183, 227)


def test_source_ankle_interval_maps_to_resampled_fit_clock_without_synthetic_frames():
    from exercise_motion_pkg.contact_constraints import motion_space_support_evidence

    source_fps, native_count = 29.97, 228
    digest = 'same-source-clock'
    states = ['unknown'] * 183 + ['full_sole'] * (native_count - 183)
    start_time, end_time = 184 / source_fps, 227 / source_fps
    ankle_contact = {
        'jointName': 'right_ankle', 'supportKind': 'foot',
        'contactMotion': 'stationary', 'anchorKind': 'ankle',
        'startFrame': 184, 'endFrame': 227,
        # These ratios are native-patch ratios and would incorrectly start at
        # fitted frame 183 if scaled against the fitted 30fps frame count.
        'startRatio': 184 / 227, 'endRatio': 1.0,
        'sourcePoseStartTimeSec': start_time,
        'sourcePoseEndTimeSec': end_time,
        'sourceTimeBasis': 'absolute_source_video',
    }
    patch = {
        'available': True, 'sourceFrameCount': native_count,
        'sourceFps': source_fps, 'sourceTimeBasis': 'absolute_source_video',
        'sourceTimeOriginSec': 0., 'sourceVideoDurationSec': native_count / source_fps,
        'sourceVideoSha256': digest,
        'sourceTimesSec': [index / source_fps for index in range(native_count)],
        'feet': {'right': {'states': states}}, 'contacts': [],
    }
    fit_count = 199
    duration = native_count / source_fps
    frames = [
        {'sourceTimeSec': duration * (index / (fit_count - 1)) ** 1.2}
        for index in range(fit_count)
    ]
    # This adaptive fit clock differs materially from native-row ratios.
    # Row 166 is deliberately 10ms before contact (inside half a native frame)
    # and must remain unsupported; synthetic bridge rows are also excluded.
    frames[166]['sourceTimeSec'] = start_time - .01
    frames[180] = {'sourceTimeSec': frames[180]['sourceTimeSec'],
                   'syntheticLoopBridge': True}
    payload = {
        'sourceFootSupportEvidence': {
            'sourceVideoSha256': digest,
            'footPatchEvidence': patch,
            'contacts': [ankle_contact],
        },
        'frames': frames,
    }

    mapped = motion_space_support_evidence(payload)
    contact = next(item for item in mapped['contacts'] if item.get('anchorKind') == 'ankle')

    assert contact['_fitFrameRuns'] == [[167, 179], [181, 197]]
    assert contact['_fitFrameCount'] == fit_count
    # The independently measured patch interval remains on its original
    # native clock, rather than inheriting this ankle interval's fit bounds.
    assert mapped['footPatchEvidence']['feet']['right']['states'][183] == 'full_sole'

    mismatched = copy.deepcopy(payload)
    mismatched['sourceFootSupportEvidence']['sourceVideoSha256'] = 'different-source'
    unresolved = motion_space_support_evidence(mismatched)
    unresolved_contact = next(item for item in unresolved['contacts']
                              if item.get('anchorKind') == 'ankle')
    assert unresolved_contact['_fitFrameRuns'] == []


def test_observed_airborne_splits_timed_source_ankle_support(monkeypatch):
    from exercise_motion_pkg import foot_contact_observation as foot

    states = ['full_sole'] * 12
    states[6:8] = ['airborne'] * 2
    evidence = {
        'feet': {'right': {'jointName': 'right_ankle', 'continuousSupport': False}},
        'contacts': [{
            'jointName': 'right_ankle', 'supportKind': 'foot',
            'contactMotion': 'stationary', 'startRatio': 0.0, 'endRatio': 1.0,
            'sourceStartSample': 0, 'sourceEndSample': 11,
            'sourceStartTimeSec': 0., 'sourceEndTimeSec': 11 / 30,
            'sourceTimeBasis': 'absolute_source_video', 'confidence': 0.8,
        }],
        'sourceVideoSha256': 'airborne-source-hash',
    }
    patch = {
        'available': True, 'sourceFrameCount': len(states),
        'sourceFps': 30., 'sourceTimeBasis': 'absolute_source_video',
        'sourceTimeOriginSec': 0., 'sourceVideoDurationSec': len(states) / 30.,
        'sourceVideoSha256': 'airborne-source-hash',
        'sourceTimesSec': [i / 30 for i in range(len(states))],
        'feet': {'right': {'states': states}}, 'contacts': [],
    }
    monkeypatch.setattr(foot, 'classify_foot_contacts', lambda *args, **kwargs: patch)

    result = foot.add_observed_foot_contacts(evidence, {}, {'frames': []})

    retained = [item for item in result['contacts'] if item.get('source') ==
                'source_pose_stationary_ankle_excluding_observed_airborne']
    assert [(item['startFrame'], item['endFrame']) for item in retained] == [(0, 5), (8, 11)]


def test_material_tracks_only_corroborate_existing_full_sole_episode(tmp_path, monkeypatch):
    from exercise_motion_pkg import foot_contact_observation as foot
    from exercise_motion_pkg import source_support_tracking

    video = tmp_path / 'source.mp4'
    video.write_bytes(b'exact source')
    states = ['unknown'] * 4 + ['full_sole'] * 4 + ['airborne'] * 4
    contact = {
        'jointName': 'right_foot', 'supportKind': 'observed_foot_patch',
        'contactState': 'full_sole', 'contactMotion': 'unknown',
        'startFrame': 4, 'endFrame': 7, 'startRatio': 4 / 11, 'endRatio': 7 / 11,
    }
    patch = {
        'available': True, 'sourceFrameCount': len(states),
        'sourceFps': 29.97, 'sourceVideoSha256': hashlib.sha256(video.read_bytes()).hexdigest(),
            'sourceTimeBasis': 'absolute_source_video', 'sourceTimeOriginSec': 0.0,
            'sourceVideoDurationSec': len(states) / 29.97,
        'sourceTimesSec': [i / 29.97 for i in range(len(states))],
        'feet': {'right': {
            'states': states,
            'rayObservations': [
                {'sourceTimeSec': i / 29.97, 'state': state} for i, state in enumerate(states)
            ],
            'heelImageObservations': [
                {'sourceTimeSec': i / 29.97, 'state': state} for i, state in enumerate(states)
            ],
        }}, 'contacts': [contact],
    }
    joints = {
        'right_heel': {'image': [.50, .8], 'confidence': .95},
        'right_toe': {'image': [.58, .8], 'confidence': .95},
    }
    observations = {
        'imageWidth': 640, 'imageHeight': 360,
        'sourceVideoSha256': hashlib.sha256(video.read_bytes()).hexdigest(),
        'frames': [{'joints': joints} for _ in states],
    }
    observed = {}

    def track(video_path, _observations, _patch, episodes, *, cache_dir):
        observed['episodes'] = episodes
        observed['cache_dir'] = cache_dir
        return {
            'available': True,
            'policyVersion': source_support_tracking.FOOT_MATERIAL_POLICY_VERSION,
            'episodes': [{**episodes[0], 'sourceVideoSha256': patch['sourceVideoSha256'],
                          'status': 'verified', 'passed': True}],
        }

    monkeypatch.setattr(foot, 'classify_foot_contacts', lambda *args, **kwargs: patch)
    monkeypatch.setattr(source_support_tracking, 'observe_foot_material_episodes', track)

    result = foot.add_observed_foot_contacts(
        {'feet': {}, 'contacts': []}, observations, {'frames': []},
        source_video_path=video,
    )

    updated = result['footPatchEvidence']['contacts'][0]
    assert updated['contactMotion'] == 'stationary'
    assert updated['startFrame'] == 4 and updated['endFrame'] == 7
    assert result['footPatchEvidence']['feet']['right']['states'] == states
    assert updated['materialStationarityEvidence']['passed'] is True
    assert result['sourceMaterialStationarityPolicyVersion'] == source_support_tracking.FOOT_MATERIAL_POLICY_VERSION
    assert observed['episodes'][0]['contactState'] == 'full_sole'
    assert observed['episodes'][0]['startFrame'] == 4 and observed['episodes'][0]['endFrame'] == 7
    assert observed['episodes'][0]['maximumDisplacementPixels'] == pytest.approx(.15 * .08 * 360)
    assert updated['anchorGroupId'] and updated['ankleAnchorGroupId']
    for field in ('rayObservations', 'heelImageObservations'):
        rows = result['footPatchEvidence']['feet']['right'][field]
        assert all(rows[index]['stationaryAnchorGroupId'] == updated['anchorGroupId']
                   for index in range(4, 8))
        assert all(rows[index].get('stationaryAnchorGroupId') is None
                   for index in list(range(4)) + list(range(8, 12)))

    from exercise_motion_pkg.contact_constraints import (
        motion_space_support_evidence, observed_ground_contact_mask,
    )
    result['sharedSupportPlaneY'] = 0.0
    payload = {
        'sourceFootSupportEvidence': result,
        'frames': [{'sourceTimeSec': i / 30} for i in range(len(states))],
    }
    fit_evidence = motion_space_support_evidence(payload)
    fit_contacts = fit_evidence['contacts']
    assert fit_contacts[0]['_fitFrameRuns']
    mask = observed_ground_contact_mask(fit_evidence, ['right_foot'], len(states))
    assert mask.any()


def test_material_tracks_never_promote_unknown_or_airborne_states(tmp_path, monkeypatch):
    from exercise_motion_pkg import foot_contact_observation as foot
    from exercise_motion_pkg import source_support_tracking

    video = tmp_path / 'source.mp4'
    video.write_bytes(b'exact source')
    states = ['unknown'] * 12
    contact = {
        'jointName': 'right_foot', 'contactState': 'full_sole',
        'contactMotion': 'unknown', 'startFrame': 3, 'endFrame': 6,
        'startRatio': 3 / 11, 'endRatio': 6 / 11,
    }
    patch = {'available': True, 'sourceFrameCount': 12,
             'sourceTimesSec': [i / 30 for i in range(12)],
             'feet': {'right': {'states': states}}, 'contacts': [contact]}
    joints = {
        'right_heel': {'image': [.50, .8], 'confidence': .95},
        'right_toe': {'image': [.58, .8], 'confidence': .95},
    }
    observations = {'imageWidth': 640, 'imageHeight': 360,
                    'frames': [{'joints': joints} for _ in states]}
    monkeypatch.setattr(foot, 'classify_foot_contacts', lambda *args, **kwargs: patch)
    monkeypatch.setattr(source_support_tracking, 'observe_foot_material_episodes',
                        lambda *args, **kwargs: pytest.fail('unknown states reached pixel flow'))

    result = foot.add_observed_foot_contacts(
        {'feet': {}, 'contacts': []}, observations, {'frames': []},
        source_video_path=video,
    )

    assert result['footPatchEvidence']['contacts'][0]['contactMotion'] == 'unknown'
    assert result['footPatchEvidence']['feet']['right']['states'] == states


def test_stale_patch_cache_miss_removes_old_foot_claims_but_keeps_source_ankle_evidence(
    tmp_path, monkeypatch,
):
    from exercise_motion_pkg import bake_and_rank as bake

    workspace = tmp_path / 'candidate'
    reference_dir = workspace / 'segment_detection'
    reference_dir.mkdir(parents=True)
    video = workspace / 'source.mp4'
    video.write_bytes(b'exact source interval')
    reference = reference_dir / 'exact_source_pose_reference.json'
    reference.write_text('{}', encoding='utf-8')
    source_contact = {
        'jointName': 'right_ankle', 'supportKind': 'foot',
        'contactMotion': 'stationary', 'startRatio': .5, 'endRatio': 1.0,
        'source': 'source_pose_stationary_ankle_excluding_observed_airborne',
    }
    stale = {
        'sourcePoseSupportEvidencePolicyVersion': bake.SOURCE_POSE_SUPPORT_EVIDENCE_POLICY_VERSION,
        'sourcePoseSupportContractFingerprint': None,
        'sourceVideoSha256': hashlib.sha256(video.read_bytes()).hexdigest(),
        'feet': {'right': {'continuousSupport': True, 'jointName': 'right_ankle'}},
        'footContactCandidates': [source_contact],
        'contacts': [source_contact, {
            'jointName': 'right_foot', 'supportKind': 'observed_foot_patch',
            'contactState': 'full_sole', 'contactMotion': 'stationary',
            'startRatio': 0.0, 'endRatio': 1.0,
        }],
        'footPatchEvidence': {'available': True, 'policyVersion': bake.FOOT_CONTACT_POLICY_VERSION - 1},
    }
    monkeypatch.setattr(bake, 'load_pre_reconstruction_exact_source_phase_metrics',
                        lambda _: {'sourceFootSupportEvidence': stale})
    monkeypatch.setattr(bake, 'verified_source_video_for_pose_reference',
                        lambda *_: video)
    monkeypatch.setattr(bake, 'load_verified_source_pose_reference',
                        lambda *_: {'frames': []})
    monkeypatch.setattr(bake, 'load_cached_foot_landmarks', lambda *_: None)

    result = bake.pre_reconstruction_source_foot_support_evidence(
        workspace, exercise_motion_contract=None,
    )

    assert result['footPatchEvidenceUnavailable'] == 'matching_cached_observations_unavailable'
    assert 'footPatchEvidence' not in result
    assert result['contacts'] == [source_contact]
    assert result['feet']['right']['continuousSupport'] is False
    assert result['feet']['right']['supportSplitByUnresolvedFootPatch'] is True


def test_fresh_support_receives_ground_plane_without_parent_depth_timing(tmp_path, monkeypatch):
    from exercise_motion_pkg import bake_and_rank as bake
    raw_dir = tmp_path / 'raw'
    raw_dir.mkdir()
    normal = [0., -0.95, -0.31]
    (raw_dir / 'motion.raw.json').write_text(json.dumps({'metadata': {'videoWorldAlignment': {
        'cameraGroundPlane': {'normal': normal},
        'videoFloorDistanceObservations': {'left_ankle': [99.]},
    }}}))
    child_video = tmp_path / 'child.mp4'
    child_video.touch()
    digest = hashlib.sha256(child_video.read_bytes()).hexdigest()
    (raw_dir / 'motion.raw.json').write_text(json.dumps({'metadata': {
        'sourceVideoSha256': digest,
        'videoWorldAlignment': {
            'cameraGroundPlane': {'normal': normal},
            'videoFloorDistanceObservations': {'left_ankle': [99.]},
        },
    }}))
    fresh = {
        'contacts': [{'jointName': 'left_hand'}],
        'sourcePoseSupportEvidencePolicyVersion': bake.SOURCE_POSE_SUPPORT_EVIDENCE_POLICY_VERSION,
        'sourcePoseSupportContractFingerprint': None,
        'sourceVideoSha256': digest,
    }
    pose = {'frames': []}
    observations = {'source': 'observed-child'}
    monkeypatch.setattr(bake, 'observe_foot_landmarks', lambda path: observations if path == child_video else None)
    def classify(evidence, observed, reference, camera_normal, depth_alignment=None, **kwargs):
        assert evidence is fresh and observed is observations and reference is pose
        assert camera_normal == normal and depth_alignment is None
        return {**evidence, 'groundReferenced': True}
    monkeypatch.setattr(bake, 'add_observed_foot_contacts', classify)
    result, source = bake.authoritative_source_foot_support_evidence(
        SimpleNamespace(candidate_workspace=tmp_path),
        {'sourceFootSupportEvidence': fresh, 'sourceVideoPath': str(child_video), '_sourcePoseReference': pose})
    assert result['groundReferenced'] and result['contacts'] == fresh['contacts']
    assert source == 'exact_selected_source_video'
    assert 'groundReferenced' not in fresh


def test_fresh_source_phase_reuses_only_matching_cached_support_review(tmp_path, monkeypatch):
    from exercise_motion_pkg import bake_and_rank as bake
    from exercise_motion_pkg.body_support_observation import POLICY_VERSION

    video = tmp_path / 'selected.mp4'
    video.write_bytes(b'exact selected interval')
    digest = hashlib.sha256(video.read_bytes()).hexdigest()
    cache = tmp_path / 'segment_detection' / 'body_support'
    cache.mkdir(parents=True)
    observed = {
        'status': 'observed', 'source': 'exact_source_visual_support_observation',
        'sourceVideoSha256': digest, 'policyVersion': POLICY_VERSION,
        'observation': {'leftFoot': 'stationary_full_sole', 'leftFootSurface': 'ground',
                        'rightFoot': 'stationary_full_sole', 'rightFootSurface': 'ground'},
    }
    (cache / f'body-support-{digest}-v{POLICY_VERSION}.json').write_text(json.dumps(observed))
    fresh = {'footPatchEvidence': {'available': True}, 'contacts': [],
             'sourcePoseSupportEvidencePolicyVersion': bake.SOURCE_POSE_SUPPORT_EVIDENCE_POLICY_VERSION,
             'sourcePoseSupportContractFingerprint': None,
             'sourceVideoSha256': digest,
             'bodySupport': {'source': 'fresh-derived-geometry'}}
    monkeypatch.setattr(bake, 'source_pose_reference_from_phase_metrics', lambda _: None)

    result, source = bake.authoritative_source_foot_support_evidence(
        SimpleNamespace(candidate_workspace=tmp_path),
        {'sourceFootSupportEvidence': fresh, 'sourceVideoPath': str(video)},
    )

    assert source == 'exact_selected_source_video'
    assert result['bodySupportObservation'] == observed
    assert result['bodySupport'] == fresh['bodySupport']
    assert 'bodySupportObservation' not in fresh


@pytest.mark.parametrize('mismatch', ['sourceVideoSha256', 'policyVersion'])
def test_fresh_source_phase_does_not_reuse_incompatible_support_review(tmp_path, monkeypatch, mismatch):
    from exercise_motion_pkg import bake_and_rank as bake
    from exercise_motion_pkg.body_support_observation import POLICY_VERSION

    video = tmp_path / 'selected.mp4'
    video.write_bytes(b'exact selected interval')
    digest = hashlib.sha256(video.read_bytes()).hexdigest()
    cache = tmp_path / 'segment_detection' / 'body_support'
    cache.mkdir(parents=True)
    observed = {
        'status': 'observed', 'source': 'exact_source_visual_support_observation',
        'sourceVideoSha256': digest, 'policyVersion': POLICY_VERSION,
        'observation': {'leftFoot': 'stationary_full_sole'},
    }
    observed[mismatch] = 'different-source' if mismatch == 'sourceVideoSha256' else POLICY_VERSION - 1
    (cache / f'body-support-{digest}-v{POLICY_VERSION}.json').write_text(json.dumps(observed))
    fresh = {'footPatchEvidence': {'available': True}, 'contacts': [],
             'sourcePoseSupportEvidencePolicyVersion': bake.SOURCE_POSE_SUPPORT_EVIDENCE_POLICY_VERSION,
             'sourcePoseSupportContractFingerprint': None,
             'sourceVideoSha256': digest}
    monkeypatch.setattr(bake, 'source_pose_reference_from_phase_metrics', lambda _: None)

    result, _ = bake.authoritative_source_foot_support_evidence(
        SimpleNamespace(candidate_workspace=tmp_path),
        {'sourceFootSupportEvidence': fresh, 'sourceVideoPath': str(video)},
    )

    assert 'bodySupportObservation' not in result


def evidence(end=1.):
    return {'contacts': [{'jointName': 'left_foot', 'contactState': 'heel_only',
                         'contactMotion': 'stationary', 'surfaceKind': 'ground',
                         'startRatio': 0., 'endRatio': end}]}


def test_material_heel_anchor_allows_toe_rotation_and_releases_contact():
    angle = np.linspace(.2, .6, 8)
    foot = .2 * np.stack([np.cos(angle), np.sin(angle), np.zeros(8)], axis=1)
    ankles = HEEL_BEHIND_ANKLE_RATIO * foot
    points = np.stack([ankles, ankles + foot], axis=1)
    tracks = heel_contact_tracks(points, ['left_ankle', 'left_foot'], evidence(.5), floor=0.)
    np.testing.assert_allclose(tracks.residual(points), 0., atol=1e-15)
    shifted = points + [.01, 0., 0.]
    errors = tracks.residual(shifted)
    np.testing.assert_allclose(errors[:5, 0, 0], .01)
    np.testing.assert_array_equal(errors[5:], 0.)


@pytest.mark.parametrize('state', ['heel_only', 'toe_only'])
def test_fitter_and_playback_enforce_partial_foot_support(state):
    from test_controlled_motion_pipeline import accepted_payload
    from exercise_motion_pkg.controlled_motion import fit_controlled_motion
    from exercise_motion_pkg.rig_playback import validate_rig_playback, decode_rig

    original = accepted_payload()
    original.pop('controlledMotionFit')
    original.pop('fixedRig')
    original['sourceFootSupportEvidence'] = evidence()
    original['sourceFootSupportEvidence']['contacts'][0].update(contactState=state, verticalOnly=False)
    result, report = fit_controlled_motion(original, max_evaluations=2, timeout_seconds=60.)
    assert report['applied'], report
    valid = validate_rig_playback(result)
    assert valid['passed'], valid
    assert valid['maximumHeelContactErrorMeters'] < .0005
    moved = copy.deepcopy(result)
    coordinates = np.asarray(moved['fixedRig']['coordinates'])
    coordinates[:, 0] += .01
    moved['fixedRig']['coordinates'] = coordinates.tolist()
    poses = decode_rig(moved['fixedRig'], coordinates)
    for frame, pose in zip(moved['frames'], poses):
        frame['joints'] = dict(zip(moved['jointNames'], pose.tolist()))
    rejected = validate_rig_playback(moved)
    assert not rejected['passed']
    assert rejected['maximumContactErrorMeters'] >= .0099
