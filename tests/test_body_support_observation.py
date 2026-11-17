from copy import deepcopy
import json
from pathlib import Path

import pytest

from exercise_motion_pkg.body_support_observation import (
    POLICY_VERSION, CONTACT_TIMELINE_POLICY_VERSION,
    body_support_source_readiness,
    materialize_body_support,
)


def _add_direct_contact_timeline(observed, source_pose, joints):
    reference = source_pose if isinstance(source_pose, dict) else {}
    pose = reference.get('pose') if isinstance(reference.get('pose'), dict) else reference
    digest = observed['sourceVideoSha256']
    reference.setdefault('sourceVideoSha256', digest)
    pose.setdefault('sourceVideoSha256', digest)
    frames = pose['frames']
    for index, frame in enumerate(frames):
        frame.setdefault('sourceTimeSec', index / 10.)
    samples = []
    for joint, surface in joints.items():
        side = joint.split('_', 1)[0] if joint.startswith(('left_', 'right_')) else 'center'
        for index in sorted({0, len(frames) - 1}):
            sample_id = f'{joint}-{index}'
            samples.append({'sampleId': sample_id, 'sourceTimeSec': frames[index]['sourceTimeSec'],
                'sourceFrameIndex': round(frames[index]['sourceTimeSec'] * 10), 'sourceFps': 10.,
                'sourcePoseFrameIndex': index, 'side': side,
                'landmark': 'knee' if joint.endswith('_knee') else 'joint',
                'jointName': joint, 'contactState': 'direct_contact', 'surface': surface,
                'visible': True, 'sourceTrackStationary': True})
    observed['contactTimeline'] = {'schemaVersion': 1, 'policyVersion': CONTACT_TIMELINE_POLICY_VERSION,
        'source': 'exact_source_visual_contact_timeline', 'sourceVideoSha256': digest,
        'sourceClock': 'video_frame_zero_seconds', 'status': 'observed', 'samples': samples}


def _registered_material_conflict(side, digest):
    """Material stationarity only conflicts when both shoe tracks are scene-registered."""
    return {'sourceVideoSha256': digest, 'episodes': [{
        'side': side, 'passed': False, 'sourceVideoSha256': digest,
        'heel': {'reference': 'registered_scene'}, 'toe': {'reference': 'registered_scene'}}]}


def test_ankle_restraint_needs_same_source_stationary_track_and_never_declares_sole(tmp_path):
    from exercise_motion_pkg.body_support_observation import (
        materialize_ankle_support, materialize_stationary_sole_support,
    )
    from exercise_motion_pkg.sequence_stabilization import contact_mask
    from exercise_motion_pkg.contact_constraints import (
        _fit_local_timed_support_evidence, _swap_support_evidence_sides,
    )
    from nonfoot_support_fixture import build_nonfoot_support_fixture
    names = ['left_ankle', 'right_ankle', 'left_foot', 'right_foot', 'nose']
    video, _reference_path, reference, payload = build_nonfoot_support_fixture(
        tmp_path, frame_count=10, sample_frames=tuple(range(10)),
        sides=('left', 'right'), joint_names=names,
        joint_positions={'right_ankle': lambda index: [.2 + .06 * index, .8]},
        observation_overrides={'leftFoot': 'unknown', 'leftFootSurface': 'unknown'})
    evidence = payload['sourceFootSupportEvidence']
    materialize_ankle_support(payload, reference, source_video_path=video)
    assert [row['jointName'] for row in evidence['supportContacts']] == ['left_ankle'] * 10
    assert 'contactState' not in evidence['supportContacts'][0]
    assert evidence['bodySupport']['stationaryJoints'] == ['left_ankle']
    assert not evidence['bodySupport']['coplanarGroups'] and not evidence['bodySupport']['soleContacts']
    mapped = _fit_local_timed_support_evidence(payload, evidence)
    mask = contact_mask(payload, names, 10, support_evidence=mapped)
    assert mask[:, 0].all() and not mask[:, 1:4].any()
    swapped = _swap_support_evidence_sides(evidence)
    assert swapped['bodySupportObservation']['observation']['rightAnkle'] == 'stationary_support'
    digest = evidence['sourceVideoSha256']
    evidence['footPatchEvidence'] = {'available': True, 'sourceVideoSha256': digest,
        'sourceFrameCount': 10, 'sourceFps': 10., 'sourceTimeBasis': 'absolute_source_video',
        'sourceTimesSec': [index / 10. for index in range(10)],
        'feet': {side: {'states': ['unknown'] * 10} for side in ('left', 'right')}}
    evidence['stationarySoleIntervalReview'] = {'sourceVideoSha256': digest, 'sourceFrameCount': 10,
        'framesPerChunk': 6, 'feet': {'left': {'confirmed': True, 'reviewedFrameCount': 10,
            'decisions': ['stationary_full_sole_ground'] * 2}}}
    rebuilt = materialize_stationary_sole_support(payload)
    assert any(row.get('supportKind') == 'observed_source_stance_interval'
               for row in rebuilt['contacts'])
    assert [contact.get('nonFootSupportReceipt') for contact in rebuilt['supportContacts']] == [
        contact.get('nonFootSupportReceipt') for contact in evidence['supportContacts']]
    assert 'left_ankle' in rebuilt['bodySupport']['stationaryJoints']
    # Cycle selection normalizes generic supportContacts into contacts.
    evidence['contacts'] = evidence.pop('supportContacts')
    normalized = materialize_stationary_sole_support(payload)
    assert 'left_ankle' in normalized['bodySupport']['stationaryJoints']
    reference['sourceVideoSha256'] = 'other'
    materialize_ankle_support(payload, reference)
    assert evidence['supportContacts'] == []
    assert not any(row.get('supportKind') == 'observed_stationary_ankle_restraint'
                   for row in evidence['contacts'])
    assert 'left_ankle' not in (evidence.get('bodySupport') or {}).get('stationaryJoints', [])


@pytest.mark.parametrize('moving_ankle', [False, True])
@pytest.mark.parametrize('frame_count', [6, 14, 32])
def test_dense_stance_review_adds_only_fully_reviewed_video_bound_contacts(
        tmp_path, monkeypatch, moving_ankle, frame_count):
    import cv2
    import hashlib
    import numpy as np
    from exercise_motion_pkg import body_support_observation as bso
    from exercise_motion_pkg.body_support_observation import (
        observe_stationary_sole_intervals, materialize_stationary_sole_support,
    )
    from exercise_motion_pkg.sequence_stabilization import contact_mask

    video = tmp_path / 'source.avi'
    writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*'MJPG'), 10., (96, 64))
    assert writer.isOpened()
    for _ in range(frame_count):
        writer.write(np.zeros((64, 96, 3), dtype=np.uint8))
    writer.release()
    digest = hashlib.sha256(video.read_bytes()).hexdigest()
    pose = {'coordinateSpace': 'normalized_image_xy', 'frames': [
        {'sourceTimeSec': i / 10.,
         'joints': {'left_ankle': [.3, .8], 'left_hip': [.4, .5], 'nose': [.5, .1]}}
        for i in range(frame_count)]}
    verified_pose = [pose]

    def verified_track(_video_path, side, expected_digest):
        source_pose = verified_pose[0]
        frames = source_pose.get('frames') or []
        valid = []
        try:
            for frame in frames:
                point = (frame.get('joints') or {}).get(f'{side}_ankle')
                confidence = (frame.get('jointConfidence') or {}).get(f'{side}_ankle', 1.)
                if (point is not None and len(point) >= 2 and
                        np.isfinite(point[:2]).all() and np.isfinite(confidence) and confidence >= .5):
                    valid.append((float(frame['sourceTimeSec']), point, confidence))
        except (TypeError, ValueError, OverflowError, KeyError):
            return None, None
        if len(valid) < max(6, .7 * len(frames)):
            return None, None
        return ({'sourceVideoSha256': expected_digest, 'jointName': f'{side}_ankle',
                 'stationary': bso.stationary_source_track(source_pose, f'{side}_ankle'),
                 'sourcePoseFrameCount': len(frames),
                 'sourcePoseTrackSha256': 'focused-test-track'}, source_pose)

    # Isolate the batching/cache behavior from the independently tested disk
    # receipt loader while still requiring a complete, confidence-valid track.
    monkeypatch.setattr(bso, '_verified_source_pose_track_proof', verified_track)
    if moving_ankle:
        for index, frame in enumerate(pose['frames']):
            frame['joints']['left_ankle'][1] -= .03 * index
    evidence = {'sourceVideoSha256': digest,
        'bodySupportObservation': {'status': 'observed', 'sourceVideoSha256': digest,
            'policyVersion': POLICY_VERSION, 'source': 'exact_source_visual_support_observation',
            'observation': {'leftFoot': 'stationary_forefoot' if moving_ankle else 'stationary_full_sole',
                            'leftFootSurface': 'ground'}},
        'footPatchEvidence': {'available': True, 'sourceVideoSha256': digest, 'sourceFrameCount': frame_count,
            'sourceFps': 10., 'sourceTimeBasis': 'absolute_source_video',
            'sourceTimesSec': [i / 10. for i in range(frame_count)],
            'feet': {'left': {'states': ['full_sole'] + ['unknown'] * (frame_count - 1)}}},
        'contacts': [{'jointName': 'left_foot', 'contactState': 'full_sole',
                      'contactMotion': 'stationary', 'startRatio': 0., 'endRatio': 0.}]}
    calls = []
    def caption_images(**kwargs):
        calls.append(kwargs)
        fields = set(kwargs['response_schema']['properties'])
        motion_fields = {field for field in fields
                         if field.startswith(('heelMotion_image_', 'forefootMotion_image_'))}
        ids = fields - motion_fields
        assert len(kwargs['frame_paths']) <= 5
        assert all(Path(path).is_file() for path in kwargs['frame_paths'])
        if frame_count == 32 and len(calls) == 1:
            # Persist only one complete sheet from this five-image response;
            # the other four sheets must remain unresolved and resume later.
            ids = {sample_id for sample_id in ids if 0 <= int(sample_id) < 6}
            motion_fields = {field for field in motion_fields if field.endswith('_image_0')}
        return json.dumps({**{sample_id: 'full_sole_ground' for sample_id in ids},
                           **{field: 'stationary' for field in motion_fields}})
    proof = observe_stationary_sole_intervals(video, {'sourceVideoSha256': digest, 'pose': pose},
                                            evidence, caption_images, tmp_path / 'review')
    chunk_count = (frame_count + 5) // 6
    request_count = (chunk_count + 4) // 5
    assert len(calls) == request_count
    requested_ids = [sample_id for call in calls
                     for sample_id in set(call['response_schema']['properties'])
                     if sample_id.isdigit()]
    assert sorted(map(int, requested_ids)) == list(range(frame_count))
    assert max(len(call['frame_paths']) for call in calls) <= 5
    assert len(calls[0]['frame_paths']) == min(5, chunk_count)
    assert proof['framesPerChunk'] == 6
    if frame_count == 32:
        # A successful batch can commit its first complete page without
        # advertising full interval coverage; resumption asks only for pages
        # lacking a validated per-sheet checkpoint.
        assert proof['feet']['left']['reviewedFrameCount'] == 8
        assert proof['feet']['left']['confirmed'] is False
        proof = observe_stationary_sole_intervals(
            video, {'sourceVideoSha256': digest, 'pose': pose}, evidence,
            caption_images, tmp_path / 'review')
        assert proof['feet']['left']['reviewedFrameCount'] == frame_count
        assert proof['feet']['left']['confirmed'] is True
        assert len(calls) == request_count + 1
        request_count += 1
    else:
        assert proof['feet']['left']['reviewedFrameCount'] == frame_count
    # Batched review still writes exact per-sheet legacy answers. If the new
    # grouped/source-bound checkpoints disappear, those exact-image answers
    # remain readable without another visual request.
    import shutil
    shutil.rmtree(tmp_path / 'review' / 'questions' / 'stance-interval-batch-v2')
    shutil.rmtree(tmp_path / 'review' / 'questions' / 'stance-interval-sourcebound')
    legacy_reuse = observe_stationary_sole_intervals(
        video, {'sourceVideoSha256': digest, 'pose': pose}, evidence,
        caption_images, tmp_path / 'review')
    assert legacy_reuse == proof
    assert len(calls) == request_count
    if not moving_ankle:
        partial_pose = deepcopy(pose)
        for frame in partial_pose['frames']:
            frame['jointConfidence'] = {'left_ankle': float('inf')}
        partial_pose['frames'][0]['joints'] = None
        partial_pose['frames'][1]['jointConfidence']['left_ankle'] = None
        verified_pose[0] = partial_pose
        partial_evidence = deepcopy(evidence)
        partial_evidence['bodySupportObservation']['observation']['leftFoot'] = 'stationary_forefoot'
        assert observe_stationary_sole_intervals(
            video, {'sourceVideoSha256': digest, 'pose': partial_pose},
            partial_evidence, caption_images, tmp_path / 'partial-review') is None
        assert len(calls) == request_count
    payload = {'jointNames': ['left_ankle', 'left_foot'], 'frames': [
        {'sourceTimeSec': i / 10., 'joints': {'left_ankle': [0., .1, 0.], 'left_foot': [0., 0., .1]}}
        for i in range(frame_count)], 'sourceFootSupportEvidence': evidence}
    evidence['stationarySoleIntervalReview'] = proof
    legacy_payload = deepcopy(payload)
    legacy_evidence = legacy_payload['sourceFootSupportEvidence']
    legacy_evidence['stationarySoleIntervalReview'].pop('framesPerChunk')
    legacy_materialized = materialize_stationary_sole_support(legacy_payload)
    assert not contact_mask(legacy_payload, payload['jointNames'], frame_count,
                            support_evidence=legacy_materialized).all()
    from exercise_motion_pkg.foot_contact_observation import _reviewed_sole_mode_masks
    legacy_neutral, legacy_contact, *_ = _reviewed_sole_mode_masks(legacy_evidence, {
        'sourceVideoSha256': digest,
        'frames': [{'timeSeconds': i / 10.} for i in range(frame_count)]}, 'left')
    assert not legacy_neutral.any() and not legacy_contact.any()
    legacy_evidence['stationarySoleIntervalReview']['framesPerChunk'] = 32
    legacy_materialized = materialize_stationary_sole_support(legacy_payload)
    assert not contact_mask(legacy_payload, payload['jointNames'], frame_count,
                            support_evidence=legacy_materialized).all()
    legacy_neutral, legacy_contact, *_ = _reviewed_sole_mode_masks(legacy_evidence, {
        'sourceVideoSha256': digest,
        'frames': [{'timeSeconds': i / 10.} for i in range(frame_count)]}, 'left')
    assert not legacy_neutral.any() and not legacy_contact.any()
    materialized = materialize_stationary_sole_support(payload)
    completed_mask = contact_mask(payload, payload['jointNames'], frame_count,
                                  support_evidence=materialized)
    assert not completed_mask[:, 0].any() and completed_mask[:, 1].all()
    from exercise_motion_pkg.foot_geometry import calibrated_foot_rest_pitches
    points = np.asarray([[frame['joints'][name] for name in payload['jointNames']]
                         for frame in payload['frames']])
    assert 'left' in calibrated_foot_rest_pitches(points, payload['jointNames'], materialized)
    assert evidence['footPatchEvidence']['feet']['left']['states'] == ['full_sole'] + ['unknown'] * (frame_count - 1)
    assert evidence['contacts'][0]['endRatio'] == 0.
    toe_payload = deepcopy(payload)
    toe_evidence = toe_payload['sourceFootSupportEvidence']
    toe_evidence['stationarySoleIntervalReview']['feet']['left']['decisions'] = ['stationary_forefoot_ground'] * chunk_count
    materialized = materialize_stationary_sole_support(toe_payload)
    pins = contact_mask(toe_payload, toe_payload['jointNames'], frame_count, support_evidence=materialized)
    assert pins[:, 1].all()
    assert not pins[:, 0].any()
    assert materialized['bodySupportObservation']['observation']['leftFoot'] == 'stationary_forefoot'
    assert toe_evidence['bodySupportObservation']['observation']['leftFoot'] == ('stationary_forefoot' if moving_ankle else 'stationary_full_sole')
    if frame_count == 14:
        mixed = deepcopy(toe_payload)
        mixed['sourceFootSupportEvidence']['stationarySoleIntervalReview']['feet']['left']['decisions'] = [
            'stationary_full_sole_ground', 'stationary_forefoot_ground', 'stationary_full_sole_ground']
        mixed_evidence = materialize_stationary_sole_support(mixed)
        mixed_pins = contact_mask(mixed, mixed['jointNames'], frame_count, support_evidence=mixed_evidence)
        assert mixed_pins[:, 1].all()
        assert not mixed_pins[:, 0].any()
        from exercise_motion_pkg.foot_contact_observation import _reviewed_sole_mode_masks
        neutral, contact, *_ = _reviewed_sole_mode_masks(mixed['sourceFootSupportEvidence'], {
            'sourceVideoSha256': digest,
            'frames': [{'timeSeconds': i / 10.} for i in range(frame_count)]}, 'left')
        assert contact.all()
        assert neutral.tolist() == [True] * 6 + [False] * 6 + [True] * 2
    for changed in ('wrong_video', 'partial_review', 'observed_release', 'material_disagreement'):
        altered = deepcopy(payload)
        current = altered['sourceFootSupportEvidence']
        if changed == 'wrong_video':
            current['stationarySoleIntervalReview']['sourceVideoSha256'] = 'wrong'
        elif changed == 'partial_review':
            current['stationarySoleIntervalReview']['feet']['left']['reviewedFrameCount'] = 5
        elif changed == 'observed_release':
            current['footPatchEvidence']['feet']['left']['states'][2] = 'airborne'
        else:
            current['sourceMaterialStationarityEvidence'] = _registered_material_conflict('left', digest)
        materialized = materialize_stationary_sole_support(altered)
        assert not contact_mask(altered, altered['jointNames'], frame_count, support_evidence=materialized).all()


def test_unresolved_unknown_patch_with_stationary_ankle_proposes_review(tmp_path):
    import cv2
    import hashlib
    import numpy as np
    from exercise_motion_pkg.body_support_observation import (
        UNRESOLVED_CONTINUOUS_GROUND_SOLE_REVIEW,
        materialize_stationary_sole_support,
        observe_stationary_sole_intervals,
        source_sole_review_side_eligibility,
    )
    from exercise_motion_pkg.sequence_stabilization import contact_mask

    frame_count = 6
    video = tmp_path / 'source.avi'
    writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*'MJPG'), 10., (96, 64))
    assert writer.isOpened()
    for _ in range(frame_count):
        writer.write(np.zeros((64, 96, 3), dtype=np.uint8))
    writer.release()
    digest = hashlib.sha256(video.read_bytes()).hexdigest()
    pose = {'coordinateSpace': 'normalized_image_xy', 'frames': [
        {'joints': {'left_ankle': [.3, .8], 'left_hip': [.4, .5], 'nose': [.5, .1]}}
        for _ in range(frame_count)]}

    def make_evidence(observation, states):
        return {'sourceVideoSha256': digest,
            'bodySupportObservation': {'status': 'observed', 'sourceVideoSha256': digest,
                'policyVersion': POLICY_VERSION, 'source': 'exact_source_visual_support_observation',
                'observation': observation},
            'footPatchEvidence': {'available': True, 'sourceVideoSha256': digest,
                'sourceFrameCount': frame_count, 'sourceFps': 10.,
                'sourceTimeBasis': 'absolute_source_video',
                'sourceTimesSec': [i / 10. for i in range(frame_count)],
                'feet': {'left': {'states': states}}},
            'contacts': []}

    moving = {'leftFoot': 'moving', 'leftFootSurface': 'ground'}
    evidence = make_evidence(moving, ['unknown'] * frame_count)
    eligible = lambda current, current_pose, mode: source_sole_review_side_eligibility(
        current, current_pose, 'left', ground_contact_mode=mode)
    assert eligible(evidence, pose, 'continuous') == UNRESOLVED_CONTINUOUS_GROUND_SOLE_REVIEW
    assert eligible(evidence, pose, 'intermittent') is None
    raised = deepcopy(evidence)
    raised['bodySupportObservation']['observation']['leftFootSurface'] = 'fixed_bar'
    assert eligible(raised, pose, 'continuous') is None
    conflict = deepcopy(evidence)
    conflict['sourceMaterialStationarityEvidence'] = _registered_material_conflict('left', digest)
    assert eligible(conflict, pose, 'continuous') is None
    stale = deepcopy(evidence)
    stale['footPatchEvidence']['sourceVideoSha256'] = 'other'
    assert eligible(stale, pose, 'continuous') is None
    moving_pose = deepcopy(pose)
    for index, frame in enumerate(moving_pose['frames']):
        frame['joints']['left_ankle'][1] -= .1 * index
    assert eligible(evidence, moving_pose, 'continuous') is None

    calls = []
    def stationary_caption(**kwargs):
        calls.append(kwargs)
        ids = set(kwargs['response_schema']['properties']) - {'heelMotion', 'forefootMotion'}
        return json.dumps({**{sample_id: 'full_sole_ground' for sample_id in ids},
                           'heelMotion': 'stationary', 'forefootMotion': 'stationary'})
    reference = {'sourceVideoSha256': digest, 'pose': pose}
    proof = observe_stationary_sole_intervals(
        video, reference, evidence, stationary_caption, tmp_path / 'review',
        ground_contact_mode='continuous')
    assert len(calls) == 1
    assert proof['feet']['left']['confirmed'] is True
    evidence['stationarySoleIntervalReview'] = proof
    payload = {'jointNames': ['left_ankle', 'left_foot'], 'groundContactMode': 'continuous',
        'frames': [{'sourceTimeSec': i / 10.,
                    'joints': {'left_ankle': [0., .1, 0.], 'left_foot': [0., 0., .1]}}
                   for i in range(frame_count)], 'sourceFootSupportEvidence': evidence}
    materialized = materialize_stationary_sole_support(payload)
    assert contact_mask(payload, payload['jointNames'], frame_count, support_evidence=materialized).all()

    negative_evidence = make_evidence(moving, ['unknown'] * frame_count)
    def moving_caption(**kwargs):
        ids = set(kwargs['response_schema']['properties']) - {'heelMotion', 'forefootMotion'}
        return json.dumps({**{sample_id: 'airborne' for sample_id in ids},
                           'heelMotion': 'moving', 'forefootMotion': 'moving'})
    negative = observe_stationary_sole_intervals(
        video, reference, negative_evidence, moving_caption, tmp_path / 'negative',
        ground_contact_mode='continuous')
    assert negative['feet']['left']['confirmed'] is False
    negative_evidence['stationarySoleIntervalReview'] = negative
    negative_payload = deepcopy(payload)
    negative_payload['sourceFootSupportEvidence'] = negative_evidence
    materialized = materialize_stationary_sole_support(negative_payload)
    assert not contact_mask(negative_payload, negative_payload['jointNames'], frame_count,
                            support_evidence=materialized).any()


def test_observed_knee_support_requires_timed_visible_contact_and_stationarity():
    from exercise_motion_pkg.body_support_observation import (
        CONTACT_TIMELINE_POLICY_VERSION, materialize_knee_support)
    from exercise_motion_pkg.support_geometry import support_contact_masks
    joints = {'left_knee': [.2, .8, 0.], 'right_knee': [.4, .8, 0.],
              'pelvis': [.3, .5, 0.], 'head': [.3, .1, 0.]}
    pose = {'coordinateSpace': 'normalized_image_xy', 'frames': [
        {'sourceTimeSec': index / 10, 'joints': deepcopy(joints)} for index in range(12)]}
    reference = {'sourceVideoSha256': 'fixture', 'pose': pose}
    payload = {'jointNames': list(joints), 'frames': deepcopy(pose['frames']),
               'sourceFootSupportEvidence': {'bodySupportObservation': {
                   'status': 'observed', 'source': 'exact_source_visual_support_observation',
                   'sourceVideoSha256': 'fixture', 'sourceClock': 'video_frame_zero_seconds',
                   'policyVersion': POLICY_VERSION, 'observation': {
                       'leftKnee': 'stationary_support', 'leftKneeContactSurface': 'floor',
                       'rightKnee': 'unknown', 'rightKneeContactSurface': 'unknown'}}}}
    # A coarse answer that knees are stationary on the floor is insufficient:
    # this fixture has no time-scoped visible contact proof.
    materialize_knee_support(payload, reference)
    assert 'bodySupport' not in payload['sourceFootSupportEvidence']
    timeline_samples = []
    for index in (0, len(pose['frames']) - 1):
        timeline_samples.append({
            'sampleId': f'contact-left-knee-pose-{index}', 'side': 'left',
            'landmark': 'knee', 'jointName': 'left_knee',
            'contactState': 'direct_contact', 'surface': 'floor', 'visible': True,
            'sourceTrackStationary': True, 'sourcePoseFrameIndex': index,
            'sourceFrameIndex': index, 'sourceFps': 10., 'sourceTimeSec': index / 10,
        })
    payload['sourceFootSupportEvidence']['bodySupportObservation']['contactTimeline'] = {
        'schemaVersion': 1, 'policyVersion': CONTACT_TIMELINE_POLICY_VERSION,
        'source': 'exact_source_visual_contact_timeline',
        'sourceVideoSha256': 'fixture', 'sourceClock': 'video_frame_zero_seconds',
        'status': 'observed', 'samples': timeline_samples,
    }
    materialize_knee_support(payload, reference)
    support = payload['sourceFootSupportEvidence']['bodySupport']
    assert support['stationaryJoints'] == ['left_knee']
    pins, _ = support_contact_masks(support, payload['jointNames'], len(payload['frames']))
    assert pins[:, payload['jointNames'].index('left_knee')].all()
    assert not pins[:, payload['jointNames'].index('right_knee')].any()
    # Positive timed evidence retains the existing knee-anchor capability.
    for index in range(6, len(pose['frames'])):
        payload['frames'][index]['joints']['left_knee'][0] += .4
        pose['frames'][index]['joints']['left_knee'][0] += .4
    materialize_knee_support(payload, reference)
    assert 'bodySupport' not in payload['sourceFootSupportEvidence']
    for index, frame in enumerate(pose['frames']):
        frame['joints']['left_knee'][0] += index * .03
    materialize_knee_support(payload, reference)
    assert 'bodySupport' not in payload['sourceFootSupportEvidence']
    for invalid in ({'sourceVideoSha256': 'other', 'pose': pose},
                    {'sourceVideoSha256': 'fixture', 'pose': {'frames': []}}):
        materialize_knee_support(payload, invalid)
        assert 'bodySupport' not in payload['sourceFootSupportEvidence']


def test_observed_hand_plane_requires_both_stationary_source_tracks():
    from exercise_motion_pkg.body_support_observation import materialize_hand_support
    from exercise_motion_pkg.support_geometry import validate_support_geometry
    joints = {'left_wrist': [.2, .3, 0.], 'right_wrist': [.7, .4, 0.],
              'pelvis': [.5, .6, 0.], 'head': [.5, .1, 0.]}
    pose = {'coordinateSpace': 'normalized_image_xy',
            'frames': [{'joints': deepcopy(joints)} for _ in range(12)]}
    base = {'jointNames': list(joints), 'frames': [{'joints': deepcopy(joints)} for _ in range(12)],
            'sourceFootSupportEvidence': {'bodySupportObservation': {'status': 'observed',
            'source': 'exact_source_visual_support_observation', 'sourceVideoSha256': 'fixture',
            'policyVersion': POLICY_VERSION,
                'observation': {'leftHand': 'stationary_support', 'rightHand': 'stationary_support',
                                'leftHandContactSurface': 'floor', 'rightHandContactSurface': 'floor',
                                'handsSameHorizontalSurface': True}}}}
    base['sourceFootSupportEvidence']['supportRelativePixelTracks'] = {
        'sourceVideoSha256': 'fixture', 'stationaryContactEvidence': {
            name: {'available': True, 'passed': True}
            for name in ('left_wrist', 'right_wrist')}}
    _add_direct_contact_timeline(
        base['sourceFootSupportEvidence']['bodySupportObservation'], pose,
        {'left_wrist': 'floor', 'right_wrist': 'floor'})
    accepted = deepcopy(base)
    materialize_hand_support(accepted, pose)
    support = accepted['sourceFootSupportEvidence']['bodySupport']
    assert support['stationaryJoints'] == ['left_wrist', 'right_wrist']
    assert not validate_support_geometry(accepted)['passed']  # Unequal hand heights remain a real failure.
    for frame in accepted['frames']:
        frame['joints']['right_wrist'][1] = .3
    assert validate_support_geometry(accepted)['passed']
    for index, frame in enumerate(pose['frames']):
        frame['joints']['right_wrist'][0] += index*.015
    partial = deepcopy(base)
    materialize_hand_support(partial, pose)
    assert partial['sourceFootSupportEvidence']['bodySupport']['stationaryJoints'] == ['left_wrist']
    assert partial['sourceFootSupportEvidence']['bodySupport']['coplanarGroups'] == []
    partial = deepcopy(base)
    partial['sourceFootSupportEvidence']['bodySupportObservation']['observation']['leftHand'] = 'unknown'
    materialize_hand_support(partial, pose)
    assert 'bodySupport' not in partial['sourceFootSupportEvidence']

    # A stationary-looking held implement does not establish world anchors.
    held = deepcopy(accepted)
    observation = held['sourceFootSupportEvidence']['bodySupportObservation']['observation']
    observation['leftHandContactSurface'] = 'moving_implement'
    observation['rightHandContactSurface'] = 'moving_implement'
    materialize_hand_support(held, pose)
    assert 'bodySupport' not in held['sourceFootSupportEvidence']

    unsupported = deepcopy(accepted)
    unsupported['sourceFootSupportEvidence']['supportRelativePixelTracks']['stationaryContactEvidence'] = {
        name: {'available': True, 'passed': False, 'movesWithBody': True}
        for name in ('left_wrist', 'right_wrist')}
    materialize_hand_support(unsupported, pose)
    assert 'bodySupport' not in unsupported['sourceFootSupportEvidence']


@pytest.mark.parametrize("contact_state,surface,visible", [
    ("no_contact", "none", True),
    ("unknown", "unknown", False),
    ("direct_contact", "bench", True),
])
def test_stationary_hand_anchor_uses_hand_landmark_and_wrist_locator(contact_state, surface, visible):
    from exercise_motion_pkg.body_support_observation import materialize_hand_support
    from exercise_motion_pkg.support_geometry import support_contact_masks
    pose_joints = {'left_wrist': [.2, .3, 0.], 'right_wrist': [.7, .3, 0.]}
    pose = {'coordinateSpace': 'normalized_image_xy', 'sourceVideoSha256': 'fixture',
            'frames': [{'joints': deepcopy(pose_joints)} for _ in range(12)]}
    payload_joints = {**pose_joints, 'left_hand': [.25, .3, 0.], 'right_hand': [.75, .3, 0.]}
    payload = {'jointNames': list(payload_joints),
               'frames': [{'joints': deepcopy(payload_joints)} for _ in range(12)],
               'sourceFootSupportEvidence': {'bodySupportObservation': {
                   'status': 'observed', 'source': 'exact_source_visual_support_observation',
                   'sourceVideoSha256': 'fixture', 'policyVersion': POLICY_VERSION,
                   'observation': {'leftHand': 'stationary_support', 'rightHand': 'stationary_support',
                                   'leftHandContactSurface': 'fixed_bar',
                                   'rightHandContactSurface': 'fixed_bar',
                                   'handsSameHorizontalSurface': True}},
                   'bodySupport': {'source': 'exact_source_contacts_and_stationary_pose_tracks',
                                   'sourceVideoSha256': 'fixture',
                                   'stationaryJoints': ['left_wrist', 'right_wrist'],
                                   'coplanarGroups': [{'joints': ['left_wrist', 'right_wrist'],
                                                       'normal': [0., 1., 0.]}]}}}
    payload['sourceFootSupportEvidence']['supportRelativePixelTracks'] = {
        'sourceVideoSha256': 'fixture', 'stationaryContactEvidence': {
            name: {'available': True, 'passed': True} for name in ('left_wrist', 'right_wrist')}}
    _add_direct_contact_timeline(payload['sourceFootSupportEvidence']['bodySupportObservation'], pose,
                                 {'left_wrist': 'fixed_bar', 'right_wrist': 'fixed_bar'})
    before = deepcopy(pose)
    materialize_hand_support(payload, pose)
    support = payload['sourceFootSupportEvidence']['bodySupport']
    assert support['stationaryJoints'] == ['left_hand', 'right_hand']
    assert support['coplanarGroups'] == [{'joints': ['left_hand', 'right_hand'], 'normal': [0., 1., 0.]}]
    assert pose == before
    mask, _ = support_contact_masks(payload['sourceFootSupportEvidence']['bodySupport'], payload['jointNames'], 12)
    assert mask[:, payload['jointNames'].index('left_hand')].all()
    assert not mask[:, payload['jointNames'].index('left_wrist')].any()
    observation = payload['sourceFootSupportEvidence']['bodySupportObservation']
    contradiction = deepcopy(observation['contactTimeline']['samples'][0])
    contradiction.update(sampleId='left-wrist-interior', sourceTimeSec=.5,
                         sourceFrameIndex=5, sourcePoseFrameIndex=5,
                         contactState=contact_state, surface=surface, visible=visible)
    observation['contactTimeline']['samples'].append(contradiction)
    materialize_hand_support(payload, pose)
    support = payload['sourceFootSupportEvidence']['bodySupport']
    assert support['stationaryJoints'] == ['right_hand']
    assert support['coplanarGroups'] == []
    assert pose == before


def test_sparse_full_sole_review_does_not_add_full_clip_foot_anchors():
    fixture = json.loads((Path(__file__).parent / 'fixtures' /
                          'sequence_stabilization_stance.json').read_text())
    joints = fixture['joints']
    pose = {'frames': [{'joints': deepcopy(joints)} for _ in range(12)]}
    evidence = {
        'bodySupportObservation': {
            'status': 'observed', 'source': 'exact_source_visual_support_observation',
            'sourceVideoSha256': 'source-hash',
            'policyVersion': POLICY_VERSION,
            'observation': {
                'torsoSurface': 'horizontal', 'pelvisAndUpperBackSameSurface': True,
                'pelvis': 'stationary_support', 'upperBack': 'stationary_support',
                'pelvisContactSurface': 'floor', 'upperBackContactSurface': 'floor',
                'leftFoot': 'stationary_full_sole', 'leftFootSurface': 'ground',
                'rightFoot': 'stationary_full_sole', 'rightFootSurface': 'ground',
            },
        },
        'footPatchEvidence': {'available': True, 'feet': {
            'left': {'states': ['full_sole'] * 5},
            'right': {'states': ['full_sole'] * 5},
        }},
    }
    _add_direct_contact_timeline(evidence['bodySupportObservation'], pose,
        {'pelvis': 'floor', 'left_shoulder': 'floor', 'right_shoulder': 'floor'})
    payload = {'jointNames': list(joints), 'renderFloorY': fixture['renderFloorY'],
               'frames': [{'joints': deepcopy(joints)} for _ in range(12)],
               'sourceFootSupportEvidence': evidence}

    materialize_body_support(payload, pose)

    support = evidence['bodySupport']
    assert {'pelvis', 'left_shoulder', 'right_shoulder'}.issubset(
        set(support['stationaryJoints']))
    assert not ({'left_ankle', 'left_foot', 'right_ankle', 'right_foot'}
                & set(support['stationaryJoints']))


def test_exact_stationary_contacts_override_moving_region_labels_and_refresh_partial_support():
    from exercise_motion_pkg.body_support_observation import body_support_required_anchors

    joints = json.loads((Path(__file__).parent / 'fixtures' /
                        'sequence_stabilization_stance.json').read_text())['joints']
    pose = {'sourceVideoSha256': 'exact-cut', 'frames': [
        {'sourceTimeSec': index / 10., 'joints': deepcopy(joints)} for index in range(12)]}
    observed = {'status': 'observed', 'source': 'exact_source_visual_support_observation',
                'sourceVideoSha256': 'exact-cut', 'policyVersion': POLICY_VERSION,
                'observation': {'torsoSurface': 'horizontal',
                                'pelvisAndUpperBackSameSurface': True,
                                'pelvis': 'stationary_support', 'upperBack': 'stationary_support',
                                'pelvisContactSurface': 'bench', 'upperBackContactSurface': 'bench'}}
    _add_direct_contact_timeline(observed, pose,
        {'pelvis': 'bench', 'left_shoulder': 'bench', 'right_shoulder': 'bench'})
    contract = {'primaryMovingRegions': ['shoulders', 'elbows', 'upper_limb']}
    payload = {'jointNames': list(joints), 'frames': deepcopy(pose['frames']),
               'sourceFootSupportEvidence': {'bodySupportObservation': observed,
                   'bodySupport': {'required': True, 'status': 'confirmed',
                       'source': 'exact_source_contacts_and_stationary_pose_tracks',
                       'sourceVideoSha256': 'exact-cut', 'stationaryJoints': ['pelvis'],
                       'coplanarGroups': [], 'nonPenetrationChains': [], 'soleContacts': []}}}
    assert body_support_required_anchors(contract) == ('pelvis',)
    materialize_body_support(payload, pose, contract)
    support = payload['sourceFootSupportEvidence']['bodySupport']
    assert support['stationaryJoints'] == ['pelvis', 'left_shoulder', 'right_shoulder']
    support['retainedReceipt'] = 'keep'
    materialize_body_support(payload, pose, contract)
    assert payload['sourceFootSupportEvidence']['bodySupport']['retainedReceipt'] == 'keep'

    def anchors(source=pose, observation=observed):
        return body_support_required_anchors(contract, source_pose=source, observed=observation)

    assert anchors({**pose, 'sourceVideoSha256': 'different-cut'}) == ('pelvis',)
    assert anchors({k: v for k, v in pose.items() if k != 'sourceVideoSha256'}) == ('pelvis',)
    for state in ('moving', 'unknown'):
        changed = deepcopy(observed)
        changed['observation']['upperBack'] = state
        changed['observation']['upperBackContactSurface'] = 'none' if state == 'moving' else 'unknown'
        assert anchors(observation=changed) == ('pelvis',)
    moving = deepcopy(pose)
    for index, frame in enumerate(moving['frames']):
        frame['joints']['right_shoulder'][0] += index * .05
    assert anchors(source=moving) == ('pelvis', 'left_shoulder')


def test_observed_ground_toe_keeps_heel_pitch_free_and_rejects_release():
    from exercise_motion_pkg.body_support_observation import materialize_observed_ground_contacts
    import numpy as np
    from exercise_motion_pkg.support_geometry import geometry_errors, validate_support_geometry
    joints = {'left_ankle': [.2, .2, 0.], 'left_foot': [.2, 0., .1], 'head': [.5, .9, 0.]}
    source = {'frames': [{'joints': deepcopy(joints)} for _ in range(12)]}
    base = {'jointNames': list(joints), 'renderFloorY': 0.,
            'frames': [{'joints': deepcopy(joints)} for _ in range(12)],
            'sourceFootSupportEvidence': {'bodySupportObservation': {'status': 'observed',
            'source': 'exact_source_visual_support_observation', 'sourceVideoSha256': 'fixture',
            'policyVersion': POLICY_VERSION,
                'observation': {'leftFoot': 'stationary_full_sole', 'leftFootSurface': 'ground'}}}}
    result = deepcopy(base)
    materialize_observed_ground_contacts(result, source)
    support = result['sourceFootSupportEvidence']['bodySupport']
    assert support['stationaryJoints'] == ['left_foot']
    assert support['soleContacts'] == []
    points = np.array([[frame['joints'][name] for name in joints] for frame in result['frames']])
    assert np.max(np.abs(geometry_errors(points, list(joints), support))) == 0.
    assert not validate_support_geometry(result)['passed']  # Coarse labels do not prove contact.
    result['frames'][0]['joints']['left_foot'][1] = .02
    points[0, list(joints).index('left_foot'), 1] = .02
    assert np.max(np.abs(geometry_errors(points, list(joints), support))) > 0.
    for contradiction in ['airborne', 'heel_only']:
        result = deepcopy(base)
        result['sourceFootSupportEvidence']['footPatchEvidence'] = {
            'feet': {'left': {'states': ['unknown']*5 + [contradiction]}}}
        materialize_observed_ground_contacts(result, source)
        assert 'bodySupport' not in result['sourceFootSupportEvidence']
    for mode in ('intermittent', 'none'):
        result = deepcopy(base)
        result['groundContactMode'] = mode
        timed = [{'jointName': 'left_foot', 'startRatio': .1, 'endRatio': .3}]
        result['sourceFootSupportEvidence']['supportContacts'] = deepcopy(timed)
        materialize_observed_ground_contacts(result, source)
        assert 'bodySupport' not in result['sourceFootSupportEvidence']
        assert result['sourceFootSupportEvidence']['supportContacts'] == timed

        # Old cache entries may still contain a full-clip plant even when the
        # current temporal observations include a release. Clear that stale
        # materialized support without discarding the observed timed contacts.
        result['sourceFootSupportEvidence']['bodySupport'] = {
            'required': True, 'status': 'confirmed',
            'source': 'exact_source_contacts_and_stationary_pose_tracks',
            'stationaryJoints': ['left_foot', 'right_foot'],
            'coplanarGroups': [{'joints': ['left_foot', 'right_foot'],
                                'normal': [0., 1., 0.]}],
            'nonPenetrationChains': [], 'soleContacts': [],
        }
        result['sourceFootSupportEvidence']['footPatchEvidence'] = {
            'available': True,
            'feet': {
                'left': {'states': ['full_sole', 'airborne', 'full_sole']},
                'right': {'states': ['unknown'] * 3},
            },
        }
        materialize_observed_ground_contacts(result, source)
        assert 'bodySupport' not in result['sourceFootSupportEvidence']
        assert result['sourceFootSupportEvidence']['supportContacts'] == timed


def test_hash_matched_confirmed_support_adds_only_observed_stationary_ground_feet():
    from exercise_motion_pkg.body_support_observation import (
        materialize_observed_ground_contacts,
        materialize_stationary_sole_support,
    )

    fixture = json.loads((Path(__file__).parent / 'fixtures' /
                          'sequence_stabilization_stance.json').read_text())
    joints = fixture['joints']
    frame_count = 12
    source_pose = {'frames': [
        {'joints': deepcopy(joints)} for _ in range(frame_count)
    ]}

    def payload_for(*, airborne_side=None, matching_hash=True):
        video_hash = 'source-video-hash'
        evidence_hash = video_hash if matching_hash else 'different-video-hash'
        evidence = {
            'bodySupport': {
                'required': True,
                'status': 'confirmed',
                'source': 'exact_source_contacts_and_stationary_pose_tracks',
                'sourceVideoSha256': evidence_hash,
                'stationaryJoints': ['left_foot'],
                'coplanarGroups': [{
                    'joints': ['left_foot'], 'normal': [0., 1., 0.],
                    'planeOffsetMeters': fixture['renderFloorY'],
                }],
                'nonPenetrationChains': [],
                'soleContacts': [],
            },
            'bodySupportObservation': {
                'status': 'observed',
                'source': 'exact_source_visual_support_observation',
                'policyVersion': POLICY_VERSION,
                'sourceVideoSha256': video_hash,
                'observation': {
                    'leftFoot': 'stationary_full_sole', 'leftFootSurface': 'ground',
                    'rightFoot': 'stationary_full_sole', 'rightFootSurface': 'ground',
                },
            },
            'footPatchEvidence': {
                'available': True,
                'feet': {
                    'left': {'states': ['full_sole'] * frame_count},
                    'right': {'states': ['full_sole'] * frame_count},
                },
                    'contacts': [
                        {'jointName': f'{side}_foot', 'contactState': 'full_sole',
                         'contactMotion': 'stationary', 'startRatio': 0., 'endRatio': 1.}
                        for side in ('left', 'right')
                    ],
            },
        }
        if airborne_side:
            states = evidence['footPatchEvidence']['feet'][airborne_side]['states']
            states[frame_count // 2] = 'airborne'
        return {
            'jointNames': list(joints),
            'renderFloorY': fixture['renderFloorY'],
            'frames': [{'joints': deepcopy(joints)} for _ in range(frame_count)],
            'sourceFootSupportEvidence': evidence,
            'sourcePoseCameraReference': {
                'camera': {'bilateralAssignment': 'swapped'},
                'sourcePose': source_pose,
            },
        }

    payload = payload_for()
    # A horizontal shoe shift cannot change the shared ground height, including
    # when source labels are swapped between production and fit preparation.
    for frame in payload['frames']:
        frame['joints']['left_foot'][2] += .25
    direct_support = materialize_stationary_sole_support(payload)['bodySupport']
    materialize_body_support(payload, source_pose)
    rig_evidence = materialize_stationary_sole_support(payload)
    rig_support = rig_evidence['bodySupport']
    def sole_planes(support):
        return {tuple(sorted(group['joints'])): group['planeOffsetMeters']
                for group in support['coplanarGroups']
                if len(group['joints']) == 1 and group['joints'][0].endswith('_foot')}

    assert sole_planes(rig_support) == sole_planes(direct_support)
    assert set(sole_planes(rig_support).values()) == {fixture['renderFloorY']}
    for side in ('left', 'right'):
        assert sum(f'{side}_foot' in group['joints']
                   for group in rig_support['coplanarGroups']) == 1

    # Cached complete soles can still carry an older raw ground-point plane.
    # Reopening the cache must not give one foot two different target heights.
    stale_planes = deepcopy(payload)
    stale_planes['sourceFootSupportEvidence']['bodySupport']['coplanarGroups'].append({
        'joints': ['left_foot'], 'normal': [0., 1., 0.],
        'planeOffsetMeters': fixture['renderFloorY']})
    reopened = materialize_stationary_sole_support(stale_planes)['bodySupport']
    assert sole_planes(reopened) == sole_planes(rig_support)
    assert len(reopened['coplanarGroups']) == len(rig_support['coplanarGroups'])
    assert {'left_ankle', 'left_foot', 'right_ankle', 'right_foot'}.issubset(
        set(rig_support['stationaryJoints']))
    assert {contact['joints'][2] for contact in rig_support['soleContacts']} == {
        'left_foot', 'right_foot',
    }

    # The ordinary bake path's later temporal filter must preserve those same
    # hash-matched, source-observed anchors when patch frames are merely unknown.
    materialize_observed_ground_contacts(payload, source_pose)
    source_support = payload['sourceFootSupportEvidence']['bodySupport']
    assert {'left_foot', 'right_foot'}.issubset(set(source_support['stationaryJoints']))

    # A short leading occlusion may be bridged only under the exact-video
    # visual observation above; the stationary-track displacement gates remain.
    from exercise_motion_pkg.body_support_observation import stationary_source_track
    partially_occluded_pose = deepcopy(source_pose)
    for frame in partially_occluded_pose['frames'][:3]:
        frame['joints'].pop('right_ankle')
    assert not stationary_source_track(partially_occluded_pose, 'right_ankle')
    assert stationary_source_track(
        partially_occluded_pose, 'right_ankle', max_leading_gap_ratio=.30)
    partially_occluded = payload_for()
    partially_occluded['sourcePoseCameraReference']['sourcePose'] = partially_occluded_pose
    materialize_body_support(partially_occluded, partially_occluded_pose)
    partial_rig_support = materialize_stationary_sole_support(partially_occluded)['bodySupport']
    assert {'left_ankle', 'left_foot', 'right_ankle', 'right_foot'}.issubset(
        set(partial_rig_support['stationaryJoints']))

    airborne = payload_for(airborne_side='right')
    materialize_body_support(airborne, source_pose)
    airborne_rig = materialize_stationary_sole_support(airborne)
    airborne_sole_joints = {
        contact['joints'][2]
        for contact in airborne_rig.get('bodySupport', {}).get('soleContacts', [])
    }
    assert 'right_foot' in airborne_sole_joints  # Source left maps to rig right.
    assert 'left_foot' not in airborne_sole_joints

    stale = payload_for(matching_hash=False)
    materialize_body_support(stale, source_pose)
    stale_support = stale['sourceFootSupportEvidence'].get('bodySupport') or {}
    assert not {'left_ankle', 'left_foot', 'right_ankle', 'right_foot'}.intersection(
        stale_support.get('stationaryJoints') or [])

    # Sparse unknown patch bands cannot be promoted by a full-clip ankle track
    # and five-frame visual review. Timed contacts remain available to the fitter.
    unresolved = payload_for()
    unresolved['sourceFootSupportEvidence']['footPatchEvidence']['feet']['left'][
        'states'
    ][5] = 'unknown'
    unresolved['sourceFootSupportEvidence']['footPatchEvidence']['feet']['right'][
        'states'
    ][5] = 'unknown'
    unresolved['sourceFootSupportEvidence']['supportContacts'] = [
        {'jointName': 'left_foot', 'contactState': 'full_sole',
         'contactMotion': 'stationary', 'startFrame': 0, 'endFrame': 4},
    ]
    unresolved_support = materialize_stationary_sole_support(unresolved)
    assert not ({'left_ankle', 'left_foot'} & set(
        unresolved_support.get('bodySupport', {}).get('stationaryJoints', [])))
    assert len(unresolved_support['supportContacts']) == 1
    assert (unresolved_support['supportContacts'][0]['startFrame'],
            unresolved_support['supportContacts'][0]['endFrame']) == (0, 4)
    sparse = payload_for()
    sparse['sourceFootSupportEvidence']['footPatchEvidence']['feet']['left'][
        'states'
    ] = ['full_sole'] * 5
    sparse['sourceFootSupportEvidence']['footPatchEvidence']['feet']['right'][
        'states'
    ] = ['full_sole'] * 5
    sparse['sourceFootSupportEvidence']['footPatchEvidence']['contacts'] = []
    sparse_support = materialize_stationary_sole_support(sparse)
    assert 'left_ankle' not in sparse_support.get('bodySupport', {}).get('stationaryJoints', [])

    # Source patch and fit can use different frame rates. Full source coverage
    # is proved by normalized contact endpoints, not array-length equality.
    resampled = payload_for()
    resampled['frames'] = [deepcopy(resampled['frames'][0]) for _ in range(300)]
    resampled['sourceFootSupportEvidence']['footPatchEvidence']['feet'] = {
        side: {'states': ['full_sole'] * 240} for side in ('left', 'right')
    }
    resampled_support = materialize_stationary_sole_support(resampled)
    assert {'left_ankle', 'left_foot', 'right_ankle', 'right_foot'}.issubset(
        set(resampled_support['bodySupport']['stationaryJoints']))


def test_observed_ground_contact_needs_full_cycle_corroboration_when_patch_data_exists():
    from exercise_motion_pkg.body_support_observation import materialize_observed_ground_contacts

    joints = {'left_ankle': [.2, .2, 0.], 'left_foot': [.2, 0., .1],
              'right_ankle': [.7, .2, 0.], 'right_foot': [.7, 0., .1],
              'pelvis': [.5, .5, 0.], 'head': [.5, .9, 0.]}
    source = {'frames': [{'joints': deepcopy(joints)} for _ in range(12)]}
    contacts = [
        {'jointName': 'left_foot', 'supportKind': 'observed_foot_patch',
         'contactState': 'full_sole', 'contactMotion': 'stationary',
         'startFrame': 1, 'endFrame': 4},
        {'jointName': 'left_foot', 'supportKind': 'observed_foot_patch',
         'contactState': 'full_sole', 'contactMotion': 'stationary',
         'startFrame': 7, 'endFrame': 10},
    ]
    base = {'jointNames': list(joints), 'renderFloorY': 0.,
            'frames': [{'joints': deepcopy(joints)} for _ in range(12)],
            'sourceFootSupportEvidence': {
                'temporalResolutionSufficient': True,
                'contacts': deepcopy(contacts),
                'footContactCandidates': [
                    {'jointName': 'left_ankle', 'contactMotion': 'stationary',
                     'startRatio': 0., 'endRatio': 1.},
                    {'jointName': 'right_ankle', 'contactMotion': 'stationary',
                     'startRatio': 0., 'endRatio': 1.},
                ],
                'footPatchEvidence': {'available': True, 'feet': {
                    'left': {'states': ['full_sole', 'toe_only', 'full_sole']},
                    'right': {'states': ['unknown']*3},
                }},
                'bodySupportObservation': {'status': 'observed',
                'source': 'exact_source_visual_support_observation', 'sourceVideoSha256': 'fixture',
                'policyVersion': POLICY_VERSION,
                    'observation': {'leftFoot': 'stationary_full_sole',
                                    'leftFootSurface': 'ground',
                                    'rightFoot': 'stationary_full_sole',
                                    'rightFootSurface': 'ground'}},
            }}

    contradicted = deepcopy(base)
    materialize_observed_ground_contacts(contradicted, source)
    assert 'bodySupport' not in contradicted['sourceFootSupportEvidence']
    assert contradicted['sourceFootSupportEvidence']['contacts'] == contacts

    stale_support = deepcopy(base)
    stale_support['sourceFootSupportEvidence']['bodySupport'] = {
        'required': True, 'status': 'confirmed',
        'source': 'exact_source_contacts_and_stationary_pose_tracks',
        'stationaryJoints': ['pelvis', 'left_foot', 'right_foot'],
        'coplanarGroups': [
            {'joints': ['pelvis'], 'normal': [0., 1., 0.], 'planeOffsetMeters': .5},
            {'joints': ['left_foot', 'right_foot'], 'normal': [0., 1., 0.],
             'planeOffsetMeters': 0.},
        ],
        'nonPenetrationChains': [], 'soleContacts': [],
    }
    materialize_observed_ground_contacts(stale_support, source)
    retained_support = stale_support['sourceFootSupportEvidence']['bodySupport']
    assert retained_support['stationaryJoints'] == ['pelvis']
    assert retained_support['coplanarGroups'] == [
        {'joints': ['pelvis'], 'normal': [0., 1., 0.], 'planeOffsetMeters': .5}
    ]

    corroborated = deepcopy(base)
    corroborated['sourceFootSupportEvidence']['footPatchEvidence']['feet']['left'][
        'states'
    ] = ['unknown', 'full_sole', 'unknown']
    materialize_observed_ground_contacts(corroborated, source)
    assert 'bodySupport' not in corroborated['sourceFootSupportEvidence']


def test_visual_contact_needs_independent_stationarity_and_keeps_moving_parts_free():
    joints = {'pelvis': [0., 1., 0.], 'left_hip': [-.1, 1., 0.], 'right_hip': [.1, 1., 0.],
              'left_shoulder': [-.2, 1., .5], 'right_shoulder': [.2, 1., .5],
              'neck': [0., 1., .6], 'head': [0., 1., .7],
              'spine1': [0., 1., .2], 'spine2': [0., 1., .3], 'spine3': [0., 1., .4]}
    answer = {'pelvisAndUpperBackSameSurface': True, 'torsoSurface': 'horizontal',
              'pelvis': 'stationary_support', 'upperBack': 'stationary_support',
              'pelvisContactSurface': 'floor', 'upperBackContactSurface': 'floor',
              'head': 'moving', 'leftFoot': 'moving', 'rightFoot': 'unknown'}
    base = {'jointNames': list(joints), 'frames': [{'joints': joints}],
            'sourceFootSupportEvidence': {'bodySupport': {'required': True, 'status': 'unknown'},
            'bodySupportObservation': {'status': 'observed', 'source': 'exact_source_visual_support_observation', 'sourceVideoSha256': 'fixture',
                                       'policyVersion': POLICY_VERSION, 'observation': answer}}}
    pose = {'frames': [{'joints': deepcopy(joints)} for _ in range(12)]}
    _add_direct_contact_timeline(base['sourceFootSupportEvidence']['bodySupportObservation'], pose,
        {'pelvis': 'floor', 'left_shoulder': 'floor', 'right_shoulder': 'floor'})
    assert body_support_source_readiness(pose)['ready']
    accepted = deepcopy(base)
    materialize_body_support(accepted, pose)
    support = accepted['sourceFootSupportEvidence']['bodySupport']
    assert support['status'] == 'confirmed'
    assert support['stationaryJoints'] == ['pelvis', 'left_shoulder', 'right_shoulder']
    for index, frame in enumerate(pose['frames']):
        frame['joints']['pelvis'][0] += index*.1
    rejected = deepcopy(base)
    materialize_body_support(rejected, pose)
    assert rejected['sourceFootSupportEvidence']['bodySupport']['status'] == 'unknown'
    readiness = body_support_source_readiness(pose)
    assert not readiness['ready']
    from exercise_motion_pkg.bake_and_rank import exact_source_phase_validation_rejection_reasons, exact_source_validation_effectively_passed
    validation = {'passed': True, 'required': True, 'sourceBodySupportReadiness': readiness}
    assert not exact_source_validation_effectively_passed(validation)
    assert exact_source_phase_validation_rejection_reasons(validation) == ['source_cut_supported_body_stationarity_unresolved']
    unknown = deepcopy(base)
    unknown['sourceFootSupportEvidence']['bodySupportObservation']['observation']['pelvis'] = 'unknown'
    materialize_body_support(unknown, {'frames': [{'joints': joints} for _ in range(12)]})
    assert unknown['sourceFootSupportEvidence']['bodySupport']['status'] == 'unknown'


def test_ground_sole_requires_observed_surface_and_full_selected_cycle():
    from exercise_motion_pkg.body_support_observation import materialize_stationary_sole_support
    from exercise_motion_pkg.loop_cycles import slice_loop_cycle

    def materialize(payload):
        payload['sourceFootSupportEvidence'] = materialize_stationary_sole_support(payload)

    fixture = json.loads((Path(__file__).parent/'fixtures/sequence_stabilization_stance.json').read_text())
    joints = fixture['joints']
    payload = {'jointNames': list(joints), 'fps': 30., 'renderFloorY': fixture['renderFloorY'],
               'frames': [{'timeSec': i/30., 'joints': deepcopy(joints)} for i in range(12)],
               'sourceFootSupportEvidence': {
                   'contacts': [{'jointName': 'left_foot', 'contactState': 'full_sole',
                                 'contactMotion': 'stationary', 'startFrame': 2, 'endFrame': 11}],
                   'bodySupportObservation': {'status': 'observed', 'source': 'exact_source_visual_support_observation', 'sourceVideoSha256': 'fixture',
                   'policyVersion': POLICY_VERSION,
                       'observation': {'leftFoot': 'stationary_full_sole', 'leftFootSurface': 'ground'}}}}
    materialize(payload)
    assert 'bodySupport' not in payload['sourceFootSupportEvidence']
    corroborated = deepcopy(payload)
    evidence = corroborated['sourceFootSupportEvidence']
    evidence['temporalResolutionSufficient'] = True
    evidence['footContactCandidates'] = [{'jointName': 'left_ankle',
        'contactMotion': 'stationary', 'startRatio': 0., 'endRatio': 1.}]
    evidence['footPatchEvidence'] = {'available': True, 'feet': {'left': {
        'states': ['unknown']*2+['full_sole']*10}}, 'contacts': [
            {'jointName': 'left_foot', 'contactState': 'full_sole',
             'contactMotion': 'stationary', 'startRatio': 0., 'endRatio': 1.}
        ]}
    for contradiction in ['release', 'partial_tracking']:
        incomplete = deepcopy(corroborated)
        if contradiction == 'release':
            incomplete['sourceFootSupportEvidence']['footPatchEvidence']['feet']['left']['states'][0] = 'airborne'
        else:
            incomplete['sourceFootSupportEvidence']['footContactCandidates'][0]['startRatio'] = .1
        materialize(incomplete)
        assert 'bodySupport' not in incomplete['sourceFootSupportEvidence']
    materialize(corroborated)
    assert 'bodySupport' not in corroborated['sourceFootSupportEvidence']
    corroborated['sourceFootSupportEvidence']['footPatchEvidence']['feet']['left'][
        'states'
    ] = ['full_sole'] * 12
    materialize(corroborated)
    assert corroborated['sourceFootSupportEvidence']['bodySupport']['stationaryJoints'] == ['left_ankle', 'left_foot']
    cycle = slice_loop_cycle(payload, {'startFrame': 2, 'stopFrameExclusive': 12})
    for surface in ['raised_surface', 'unknown']:
        unsupported = deepcopy(cycle)
        unsupported['sourceFootSupportEvidence']['bodySupportObservation']['observation']['leftFootSurface'] = surface
        materialize(unsupported)
        assert 'bodySupport' not in unsupported['sourceFootSupportEvidence']
    unresolved = deepcopy(cycle)
    unresolved['sourceFootSupportEvidence']['bodySupport'] = {'required': True, 'status': 'unknown'}
    materialize(unresolved)
    assert unresolved['sourceFootSupportEvidence']['bodySupport']['status'] == 'unknown'
    materialize(cycle)
    support = cycle['sourceFootSupportEvidence']['bodySupport']
    assert support['stationaryJoints'] == ['left_ankle', 'left_foot']
    assert support['soleContacts'][0]['joints'] == ['left_knee', 'left_ankle', 'left_foot']

    # The selected cycle can be wholly inside a stance that did not cover its
    # parent clip. Upgrading an observed toe must preserve unrelated supports.
    partial = deepcopy(payload)
    evidence = partial['sourceFootSupportEvidence']
    evidence['temporalResolutionSufficient'] = True
    evidence['footContactCandidates'] = [{'jointName': 'left_ankle', 'contactMotion': 'stationary',
                                         'startFrame': 2, 'endFrame': 11}]
    evidence['footPatchEvidence'] = {'available': True, 'feet': {'left': {
        'states': ['airborne']*2+['full_sole']*4+['unknown']*2+['full_sole']*4}}}
    evidence['bodySupport'] = {'required': True, 'status': 'confirmed',
        'stationaryJoints': ['left_foot', 'right_wrist'],
        'coplanarGroups': [{'joints': ['left_foot'], 'normal': [0, 1, 0], 'planeOffsetMeters': fixture['renderFloorY']},
                          {'joints': ['right_wrist'], 'normal': [0, 1, 0], 'planeOffsetMeters': 2.}],
        'soleContacts': [], 'nonPenetrationChains': []}
    original = deepcopy(partial)
    selected = slice_loop_cycle(partial, {'startFrame': 2, 'stopFrameExclusive': 12})
    materialize(selected)
    upgraded = selected['sourceFootSupportEvidence']['bodySupport']
    assert set(upgraded['stationaryJoints']) == {'left_ankle', 'left_foot', 'right_wrist'}
    assert len(upgraded['stationaryJoints']) == 3
    assert upgraded['soleContacts'][0]['joints'] == ['left_knee', 'left_ankle', 'left_foot']
    assert upgraded['coplanarGroups'][0]['joints'] == ['right_wrist']
    assert upgraded['coplanarGroups'][0]['planeOffsetMeters'] == 2.
    assert partial == original


def test_fit_support_materialization_removes_stale_full_clip_foot_anchors():
    from exercise_motion_pkg.body_support_observation import materialize_stationary_sole_support

    joints = {
        'left_hip': [.4, .8, 0.], 'right_hip': [.6, .8, 0.],
        'left_shoulder': [.35, 1.2, 0.], 'right_shoulder': [.65, 1.2, 0.],
        'left_ankle': [.4, .05, 0.], 'left_foot': [.4, 0., .1],
        'right_ankle': [.6, .05, 0.], 'right_foot': [.6, 0., .1],
    }
    contacts = [
        {'jointName': 'left_foot', 'supportKind': 'observed_foot_patch',
         'contactState': 'full_sole', 'contactMotion': 'stationary',
         'startFrame': 1, 'endFrame': 3},
        {'jointName': 'left_foot', 'supportKind': 'observed_foot_patch',
         'contactState': 'toe_only', 'contactMotion': 'stationary',
         'startFrame': 4, 'endFrame': 5},
    ]
    payload = {
        'jointNames': list(joints), 'fps': 30., 'renderFloorY': 0.,
        'frames': [{'timeSec': i / 30., 'joints': deepcopy(joints)} for i in range(12)],
        'sourceFootSupportEvidence': {
            'bodySupport': {
                'required': True, 'status': 'confirmed',
                'source': 'exact_source_contacts_and_stationary_pose_tracks',
                'stationaryJoints': ['left_foot', 'right_foot'],
                'coplanarGroups': [
                    {'joints': ['left_foot', 'right_foot'], 'normal': [0., 1., 0.],
                     'planeOffsetMeters': 0.},
                ],
                'nonPenetrationChains': [], 'soleContacts': [],
            },
            'bodySupportObservation': {
                'status': 'observed',
                'source': 'exact_source_visual_support_observation', 'sourceVideoSha256': 'fixture',
                'policyVersion': POLICY_VERSION,
                'observation': {
                    'leftFoot': 'stationary_full_sole', 'leftFootSurface': 'ground',
                    'rightFoot': 'stationary_full_sole', 'rightFootSurface': 'ground',
                },
            },
            'temporalResolutionSufficient': True,
            'footPatchEvidence': {
                'available': True,
                'feet': {
                    'left': {'states': ['full_sole'] * 4 + ['toe_only'] + ['unknown'] * 7},
                    'right': {'states': ['unknown'] * 12},
                },
            },
            'footContactCandidates': [
                {'jointName': 'left_ankle', 'contactMotion': 'stationary',
                 'startRatio': 0., 'endRatio': 1.},
                {'jointName': 'right_ankle', 'contactMotion': 'stationary',
                 'startRatio': 0., 'endRatio': 1.},
            ],
            'contacts': deepcopy(contacts),
        },
    }
    original = deepcopy(payload)

    materialized = materialize_stationary_sole_support(payload)

    assert 'bodySupport' not in materialized
    assert materialized['contacts'] == contacts
    assert payload == original

    # Later fit and pre-render geometry gates must use the same filtered view,
    # rather than re-reading the stale full-clip anchors from the source cache.
    moving_candidate = deepcopy(payload)
    for frame_index, frame in enumerate(moving_candidate['frames']):
        frame['joints']['left_foot'][0] += frame_index * .01
    from exercise_motion_pkg.support_geometry import validate_support_geometry
    support = validate_support_geometry(moving_candidate)
    assert support['required'] and not support['passed']
    assert support['unresolvedSides'] == ['right']
    assert moving_candidate['sourceFootSupportEvidence']['bodySupport'] == (
        payload['sourceFootSupportEvidence']['bodySupport']
    )


def test_lying_press_does_not_require_moving_shoulder_anchors():
    joints = {
        'pelvis': [0.5, 0.6, 0.0],
        'left_shoulder': [0.3, 0.4, 0.0],
        'right_shoulder': [0.7, 0.4, 0.0],
    }
    pose = {'frames': [{'joints': deepcopy(joints)} for _ in range(12)]}
    for index, frame in enumerate(pose['frames']):
        frame['joints']['right_shoulder'] = [0.7 + index * 0.01, 0.4, 0.0]
    contract = {
        'startPoseConstraints': {'supportMode': 'lying'},
        'referenceRegions': ['torso'],
        'primaryMovingRegions': ['elbows', 'shoulders'],
        'observableMotionSpec': {
            'primaryMovingRegions': ['elbows', 'shoulders'],
            'referenceRegions': ['torso'],
        },
    }
    readiness = body_support_source_readiness(pose, contract)
    assert readiness['requiredAnchors'] == ['pelvis']
    assert readiness['ready']
    assert readiness['unresolvedAnchors'] == []
    blocked = body_support_source_readiness(pose)
    assert 'right_shoulder' in blocked['unresolvedAnchors']
    joints_full = {
        **joints,
        'left_hip': [0.4, 0.6, 0.0],
        'right_hip': [0.6, 0.6, 0.0],
        'neck': [0.5, 0.35, 0.0],
        'spine1': [0.5, 0.55, 0.0],
        'spine2': [0.5, 0.5, 0.0],
        'spine3': [0.5, 0.45, 0.0],
    }
    answer = {
        'pelvisAndUpperBackSameSurface': True,
        'torsoSurface': 'horizontal',
        'pelvis': 'stationary_support',
        'upperBack': 'stationary_support',
        'pelvisContactSurface': 'floor',
        'upperBackContactSurface': 'floor',
        'head': 'moving',
        'leftFoot': 'moving',
        'rightFoot': 'unknown',
    }
    base = {
        'jointNames': list(joints_full),
        'frames': [{'joints': deepcopy(joints_full)}],
        'sourceFootSupportEvidence': {
            'bodySupport': {'required': True, 'status': 'unknown'},
            'bodySupportObservation': {
                'status': 'observed',
                'source': 'exact_source_visual_support_observation',
                'sourceVideoSha256': 'fixture',
                'policyVersion': POLICY_VERSION,
                'observation': answer,
            },
        },
    }
    _add_direct_contact_timeline(base['sourceFootSupportEvidence']['bodySupportObservation'], pose,
        {'pelvis': 'floor', 'left_shoulder': 'floor', 'right_shoulder': 'floor'})
    blocked_payload = deepcopy(base)
    materialize_body_support(blocked_payload, pose)
    assert blocked_payload['sourceFootSupportEvidence']['bodySupport']['status'] == 'unknown'
    accepted = deepcopy(base)
    materialize_body_support(accepted, pose, contract)
    support = accepted['sourceFootSupportEvidence']['bodySupport']
    assert support['status'] == 'confirmed'
    assert support['stationaryJoints'] == ['pelvis', 'left_shoulder']
    assert support['coplanarGroups'][0]['joints'] == ['pelvis', 'left_shoulder']
    from exercise_motion_pkg.bake_and_rank import (
        exact_source_phase_validation_rejection_reasons,
        exact_source_validation_effectively_passed,
    )
    validation = {
        'required': True,
        'passed': True,
        'sourceBodySupportReadiness': readiness,
    }
    assert exact_source_validation_effectively_passed(validation)
    assert exact_source_phase_validation_rejection_reasons(validation) == []


def test_russian_twist_v4_observation_cannot_create_support_or_clear_unknown_contacts():
    from exercise_motion_pkg.body_support_observation import (
        observed_body_support_contacts, remove_unobserved_torso_support,
        validated_body_support_answer,
    )
    from exercise_motion_pkg.support_geometry import support_contact_readiness

    observation = {
        'status': 'observed', 'source': 'exact_source_visual_support_observation',
        'sourceVideoSha256': '41a025927187df995dae36088a9c3e0ad7d27cfb06fa66a972eea59a8de06388',
        'policyVersion': 4,
        'observation': {
            'torsoSurface': 'horizontal', 'pelvisAndUpperBackSameSurface': True,
            'pelvis': 'stationary_support', 'upperBack': 'stationary_support',
            'pelvisContactSurface': 'floor', 'upperBackContactSurface': 'floor',
            'head': 'moving', 'headContactSurface': 'none',
            'leftFoot': 'stationary_full_sole', 'leftFootSurface': 'ground',
            'rightFoot': 'stationary_full_sole', 'rightFootSurface': 'ground',
            'leftHand': 'stationary_support', 'rightHand': 'stationary_support',
            'handsSameHorizontalSurface': False,
            'observations': 'Seated upright; feet claimed planted.',
        },
    }
    assert validated_body_support_answer(observation) is None
    assert not observed_body_support_contacts(observation)
    # Exercise the retained false claims under today's schema too. Schema
    # validity only qualifies structured claims; the independent temporal patch
    # must still prevent cropped shoes from becoming full-cycle foot anchors.
    current_observation = deepcopy(observation)
    current_observation['policyVersion'] = POLICY_VERSION
    assert validated_body_support_answer(current_observation) is not None
    evidence = {
        'bodySupportObservation': current_observation,
        'footPatchEvidence': {'available': True, 'feet': {
            'left': {'states': ['unknown'] * 81},
            'right': {'states': ['unknown'] * 81},
        }},
        'bodySupport': {
            'required': True, 'status': 'confirmed',
            'source': 'exact_source_contacts_and_stationary_pose_tracks',
            'stationaryJoints': ['pelvis', 'left_shoulder', 'right_shoulder',
                                 'left_ankle', 'left_foot', 'right_ankle', 'right_foot'],
            'coplanarGroups': [
                {'joints': ['pelvis', 'left_shoulder', 'right_shoulder'],
                 'normal': [0., 1., 0.]},
                {'joints': ['left_foot'], 'normal': [0., 1., 0.], 'planeOffsetMeters': 0.},
                {'joints': ['right_foot'], 'normal': [0., 1., 0.], 'planeOffsetMeters': 0.},
            ],
            'nonPenetrationChains': [],
            'soleContacts': [
                {'joints': ['left_knee', 'left_ankle', 'left_foot'], 'normal': [0., 1., 0.]},
                {'joints': ['right_knee', 'right_ankle', 'right_foot'], 'normal': [0., 1., 0.]},
            ],
        },
    }
    remove_unobserved_torso_support(evidence)
    assert 'bodySupport' not in evidence
    readiness = support_contact_readiness({'sourceFootSupportEvidence': evidence})
    assert not readiness['passed']
    assert readiness['unresolvedSides'] == ['left', 'right']
    assert readiness['rejectionReasons'] == ['source_support_contact_evidence_incomplete']
    assert not {'left_ankle', 'left_foot', 'right_ankle', 'right_foot'}.intersection(
        (evidence.get('bodySupport') or {}).get('stationaryJoints') or [])
    # The structured torso claim remains unproven by this parser; this regression
    # specifically verifies the independently visible foot-contact blocker.


def test_support_observation_schema_rejects_non_string_enum_values():
    from exercise_motion_pkg.body_support_observation import validated_body_support_answer

    observed = {
        'status': 'observed', 'source': 'exact_source_visual_support_observation',
        'sourceVideoSha256': '41a025927187df995dae36088a9c3e0ad7d27cfb06fa66a972eea59a8de06388',
        'policyVersion': POLICY_VERSION,
        'observation': {'leftFoot': ['stationary_full_sole'], 'leftFootSurface': 'ground'},
    }
    assert validated_body_support_answer(observed) is None


def test_v4_support_cache_is_not_reused_without_reobservation(tmp_path):
    from exercise_motion_pkg.body_support_observation import observe_body_support

    video = tmp_path / 'selected.mp4'
    video.write_bytes(b'exact selected clip')
    digest = __import__('hashlib').sha256(video.read_bytes()).hexdigest()
    cache = tmp_path / 'body_support'
    cache.mkdir()
    (cache / f'body-support-{digest}-v4.json').write_text(json.dumps({
        'status': 'observed', 'policyVersion': 4,
        'sourceVideoSha256': digest, 'observation': {'leftFoot': 'stationary_full_sole'},
    }))
    result = observe_body_support(video, None, cache)
    assert result['status'] == 'unknown'
    assert result['reason'] == 'support_observer_unavailable'


def test_confirmed_ground_sole_refreshes_stale_plane_without_duplicate_contacts():
    import numpy as np
    from exercise_motion_pkg.body_support_observation import add_ground_sole_contacts

    fixture = json.loads((Path(__file__).parent / 'fixtures/sequence_stabilization_stance.json').read_text())
    medians = {name: np.asarray(value) for name, value in fixture['joints'].items()}
    payload = {'renderFloorY': fixture['renderFloorY']}
    support = {'stationaryJoints': [], 'coplanarGroups': [
        {'joints': ['right_wrist'], 'normal': [0, 1, 0], 'planeOffsetMeters': 2.}],
        'soleContacts': []}
    add_ground_sole_contacts(payload, support, medians, ['left', 'right'], evidence={})
    expected = deepcopy(support)
    support['coplanarGroups'][1]['planeOffsetMeters'] += .032
    add_ground_sole_contacts(payload, support, medians, ['left', 'right'], evidence={})
    assert support == expected
    assert len(support['soleContacts']) == 2
    assert {tuple(group['joints']) for group in support['coplanarGroups']} == {
        ('right_wrist',), ('left_foot',), ('right_foot',),
    }


def test_contact_timeline_selects_known_sole_with_unresolved_stationarity():
    from exercise_motion_pkg.body_support_observation import _contact_timeline_candidates

    times = [0., .5, 1.]
    pose = {'coordinateSpace': 'normalized_image_xy', 'frames': [
        {'sourceTimeSec': time,
         'joints': {'left_ankle': [.4, .8], 'left_heel': [.38, .82], 'left_toe': [.46, .82]},
         'jointConfidence': {'left_ankle': .95, 'left_heel': .9, 'left_toe': .9}}
        for time in times
    ]}
    contact = {'jointName': 'left_foot', 'contactState': 'full_sole',
               'contactMotion': 'unknown', 'startRatio': 0., 'endRatio': 1.}
    evidence = {
        'contacts': [contact],
        'footPatchEvidence': {'sourceTimesSec': times, 'sourceTimeBasis': 'absolute_source_video',
                             'feet': {'left': {'states': ['full_sole'] * 3}}},
        'feet': {'left': {'contactIntervals': [{
            'contactMotion': 'stationary', 'sourceTimeBasis': 'absolute_source_video',
            'sourceStartTimeSec': 0., 'sourceEndTimeSec': 1.,
        }]}},
    }
    assert [row['sourceTimeSec'] for row in _contact_timeline_candidates(pose, evidence)] == times
    contact['contactMotion'] = 'stationary'
    assert _contact_timeline_candidates(pose, evidence) == []


def test_contact_timeline_uses_source_matched_foot_patch_landmarks_without_pose_heel_toe():
    from exercise_motion_pkg.body_support_observation import _contact_timeline_candidates

    times = [0., .5, 1.]
    pose = {'coordinateSpace': 'normalized_image_xy', 'imageWidth': 854, 'imageHeight': 480, 'frames': [
        {'sourceTimeSec': time, 'joints': {'left_ankle': [.4, .8]},
         'jointConfidence': {'left_ankle': .95}}
        for time in times
    ]}
    evidence = {
        'footPatchEvidence': {
            'sourceTimesSec': times, 'sourceTimeBasis': 'absolute_source_video',
            'feet': {'left': {
                'states': ['unknown'] * 3,
                'heelImageObservations': [
                    {'sourceTimeSec': time, 'heelImagePoint': [.38 * 854 / 480, .82],
                     'toeImagePoint': [.46 * 854 / 480, .82], 'heelConfidence': .95,
                     'toeConfidence': .94}
                    for time in times
                ],
            }},
        },
        'feet': {'left': {'contactIntervals': [{
            'contactMotion': 'stationary', 'sourceTimeBasis': 'absolute_source_video',
            'sourceStartTimeSec': 0., 'sourceEndTimeSec': 1.,
        }]}},
    }

    candidates = _contact_timeline_candidates(pose, evidence)
    assert [row['sourceTimeSec'] for row in candidates] == times
    assert candidates[1]['point'] == pytest.approx([.42, .82])
    assert candidates[1]['heel'] == pytest.approx([.38, .82])
    assert candidates[1]['toe'] == pytest.approx([.46, .82])
    evidence['footPatchEvidence']['feet']['left']['states'] = ['unknown'] * 3
    evidence['feet']['left']['contactIntervals'][0]['contactMotion'] = 'moving'
    assert _contact_timeline_candidates(pose, evidence) == []


def test_contact_timeline_targets_coarse_stationary_knee_claims():
    from exercise_motion_pkg.body_support_observation import (
        _contact_timeline_candidates, _contact_timeline_response_schema)

    frames = []
    for index in range(12):
        frames.append({'sourceTimeSec': index / 10,
                       'joints': {'left_knee': [.4, .8], 'left_ankle': [.4, .9],
                                  'pelvis': [.5, .5], 'head': [.5, .1]},
                       'jointConfidence': {'left_knee': .95, 'left_ankle': .95}})
    pose = {'coordinateSpace': 'normalized_image_xy', 'frames': frames}
    evidence = {
        'bodySupportObservation': {
            'status': 'observed', 'source': 'exact_source_visual_support_observation',
            'sourceVideoSha256': 'fixture', 'sourceClock': 'video_frame_zero_seconds',
            'policyVersion': POLICY_VERSION,
            'observation': {'leftKnee': 'stationary_support',
                            'leftKneeContactSurface': 'floor'},
        },
        'footPatchEvidence': {'sourceTimesSec': [index / 10 for index in range(12)],
                              'sourceTimeBasis': 'absolute_source_video', 'feet': {}},
    }
    candidates = _contact_timeline_candidates(pose, evidence)
    knees = [row for row in candidates if row.get('landmark') == 'knee']
    assert len(knees) == 2
    schema = _contact_timeline_response_schema(
        [row['sampleId'] for row in knees], candidates=knees)
    assert all('direct_contact' in schema['properties'][row['sampleId']]['enum']
               for row in knees)


def test_contact_timeline_targets_all_claimed_stationary_support_anchors(tmp_path, monkeypatch):
    import cv2
    import numpy as np
    from exercise_motion_pkg.body_support_observation import (
        _contact_timeline_candidates, observe_foot_contact_timeline)

    points = {'pelvis': [.5, .6], 'left_shoulder': [.4, .4],
              'right_shoulder': [.6, .4], 'left_wrist': [.2, .5]}
    pose = {'coordinateSpace': 'normalized_image_xy', 'frames': [
        {'sourceTimeSec': index / 10., 'joints': deepcopy(points),
         'jointConfidence': {joint: .95 for joint in points}}
        for index in range(12)]}
    evidence = {'bodySupportObservation': {
        'status': 'observed', 'source': 'exact_source_visual_support_observation',
        'sourceVideoSha256': 'fixture', 'policyVersion': POLICY_VERSION,
        'observation': {'pelvis': 'stationary_support', 'pelvisContactSurface': 'floor',
                        'upperBack': 'stationary_support', 'upperBackContactSurface': 'bench',
                        'leftHand': 'stationary_support', 'leftHandContactSurface': 'fixed_bar'}}}
    candidates = _contact_timeline_candidates(pose, evidence)
    assert {row['jointName'] for row in candidates} == set(points)
    assert all(row['expectedSurface'] in {'floor', 'bench', 'fixed_bar'} for row in candidates)
    assert len(candidates) == 2 * len(points)
    assert len({row['sampleId'] for row in candidates}) == len(candidates)
    assert {row['contactRegion'] for row in candidates if row['jointName'].endswith('_shoulder')} == {'upper_back'}

    video = tmp_path / 'source.mp4'
    video.write_bytes(b'code-bound contact observation')
    digest = __import__('hashlib').sha256(video.read_bytes()).hexdigest()
    evidence['bodySupportObservation']['sourceVideoSha256'] = digest
    evidence['sourceVideoSha256'] = digest

    class Capture:
        def get(self, prop):
            return {cv2.CAP_PROP_FPS: 10., cv2.CAP_PROP_FRAME_COUNT: 12}.get(prop, 0.)
        def set(self, *_): pass
        def read(self): return True, np.zeros((240, 320, 3), dtype=np.uint8)
        def release(self): pass

    monkeypatch.setattr(cv2, 'VideoCapture', lambda _: Capture())
    calls = []
    def caption(**kwargs):
        assert set(kwargs['response_schema']['properties']) == {'choice'}
        calls.append(kwargs['prompt'])
        return json.dumps({'choice': 'direct_contact'})

    timeline = observe_foot_contact_timeline(
        video, {'sourceVideoSha256': digest, 'pose': pose}, evidence, caption, tmp_path / 'cache')
    assert len(calls) == len(candidates)
    assert {row['sampleId'] for row in timeline['samples']} == {row['sampleId'] for row in candidates}
    assert all(row['contactState'] == 'direct_contact' for row in timeline['samples'])
    assert any('upper back body surface' in prompt for prompt in calls)


def test_coarse_body_support_requires_timed_contact_before_authorizing_anchors():
    from exercise_motion_pkg.body_support_observation import observed_body_support_contacts

    digest = 'fixture'
    observation = {'status': 'observed', 'source': 'exact_source_visual_support_observation',
        'sourceVideoSha256': digest, 'sourceClock': 'video_frame_zero_seconds',
        'policyVersion': POLICY_VERSION,
        'observation': {'pelvis': 'stationary_support', 'upperBack': 'stationary_support',
                        'pelvisAndUpperBackSameSurface': True, 'torsoSurface': 'horizontal',
                        'pelvisContactSurface': 'floor', 'upperBackContactSurface': 'floor'}}
    assert observed_body_support_contacts(observation) == set()

    samples = []
    for joint, side in (('pelvis', 'center'), ('left_shoulder', 'left'),
                        ('right_shoulder', 'right')):
        for index in (0, 10):
            samples.append({'sampleId': f'{joint}-{index}', 'sourceTimeSec': index / 10.,
                'sourceFrameIndex': index, 'sourceFps': 10., 'sourcePoseFrameIndex': index,
                'side': side, 'landmark': 'joint', 'jointName': joint,
                'contactState': 'direct_contact', 'surface': 'floor', 'visible': True,
                'sourceTrackStationary': True})
    observation['contactTimeline'] = {
        'schemaVersion': 1, 'policyVersion': CONTACT_TIMELINE_POLICY_VERSION,
        'source': 'exact_source_visual_contact_timeline', 'sourceVideoSha256': digest,
        'sourceClock': 'video_frame_zero_seconds', 'status': 'observed', 'samples': samples}
    assert observed_body_support_contacts(observation) == {
        'pelvis', 'left_shoulder', 'right_shoulder'}
    observation['contactTimeline']['samples'][-1]['surface'] = 'bench'
    assert observed_body_support_contacts(observation) == {'pelvis', 'left_shoulder'}


def test_timed_visual_contact_observation_binds_code_selected_side_time_and_video(tmp_path, monkeypatch):
    import cv2
    import numpy as np
    from exercise_motion_pkg.body_support_observation import (
        observe_foot_contact_timeline, validated_body_support_contact_timeline,
    )

    video = tmp_path / 'selected.mp4'
    video.write_bytes(b'exact selected source')
    digest = __import__('hashlib').sha256(video.read_bytes()).hexdigest()

    class Capture:
        def __init__(self, _path):
            self.position = 0

        def get(self, prop):
            return {cv2.CAP_PROP_FPS: 30., cv2.CAP_PROP_FRAME_COUNT: 151}.get(prop, 0.)

        def set(self, prop, value):
            assert prop == cv2.CAP_PROP_POS_FRAMES
            self.position = int(value)
            return True

        def read(self):
            frame = np.zeros((240, 320, 3), dtype=np.uint8)
            frame[:8, :8] = [0, 0, 255]  # Outside every selected foot crop.
            return True, frame

        def release(self):
            pass

    monkeypatch.setattr(cv2, 'VideoCapture', Capture)
    pose = {
        'coordinateSpace': 'normalized_image_xy',
        'sourceTimeOriginSec': 0.,
        'frames': [
            {'sourceTimeSec': float(index) * .5,
             'joints': {'left_ankle': [.35, .82], 'right_ankle': [.65, .82],
                            'left_heel': [.33, .84], 'left_toe': [.39, .84],
                            'right_heel': [.63, .84], 'right_toe': [.69, .84],
                        'left_hip': [.4, .5], 'right_hip': [.6, .5], 'nose': [.5, .1]},
                 'jointConfidence': {'left_ankle': .95, 'right_ankle': .95,
                                     'left_heel': .9, 'left_toe': .9,
                                     'right_heel': .9, 'right_toe': .9}}
            for index in range(9)
        ],
    }
    patch_times = [float(index) * .5 for index in range(9)]
    evidence = {
        'sourceVideoSha256': digest,
        'footPatchEvidence': {
            'sourceVideoSha256': digest,
            'sourceTimeBasis': 'absolute_source_video',
            'sourceTimeOriginSec': 0.,
            'sourceTimesSec': patch_times,
            'feet': {'left': {'states': ['unknown'] * len(patch_times)}},
        },
        'feet': {'left': {'contactIntervals': [
            {'contactMotion': 'stationary', 'sourceTimeBasis': 'absolute_source_video',
             'sourceStartTimeSec': 0., 'sourceEndTimeSec': 1.},
            {'contactMotion': 'stationary', 'sourceTimeBasis': 'absolute_source_video',
             'sourceStartTimeSec': 1.5, 'sourceEndTimeSec': 2.5},
            {'contactMotion': 'stationary', 'sourceTimeBasis': 'absolute_source_video',
             'sourceStartTimeSec': 3., 'sourceEndTimeSec': 4.},
        ]}},
    }
    calls = []

    def caption_images(*, frame_paths, response_schema, **_kwargs):
        calls.append((frame_paths, response_schema))
        atlas = cv2.imread(str(frame_paths[0]))
        assert np.array_equal(atlas[8, 8], [0, 0, 255])
        return json.dumps({sample_id: 'full_sole_ground'
                           for sample_id in response_schema['properties']})

    cache_dir = tmp_path / 'cache'
    pose_reference = {'sourceVideoSha256': digest, 'pose': pose}
    timeline = observe_foot_contact_timeline(
        video, pose_reference, evidence, caption_images, cache_dir)
    assert timeline['status'] == 'observed'
    assert timeline['sourceVideoSha256'] == digest
    assert timeline['sourceClock'] == 'video_frame_zero_seconds'
    assert len(calls) == 2 and all(len(paths) == 1 for paths, _schema in calls)
    sample_ids = [sample_id for _paths, schema in calls for sample_id in schema['properties']]
    assert len(sample_ids) == len(set(sample_ids)) == 9
    atlas = cv2.imread(str(calls[0][0][0]))
    assert atlas is not None and atlas.shape[0] > 3 * 50 and atlas.shape[1] > 3 * 50
    rows = validated_body_support_contact_timeline(timeline, expected_video_sha256=digest)
    assert len(rows) == 9
    assert all(row['side'] == 'left' and row['sourceTrackStationary'] is True for row in rows)
    assert all(row['sourceTimeSec'] == row['sourceFrameIndex'] / row['sourceFps'] for row in rows)
    assert all(path.is_file() for path in calls[0][0])

    cached = observe_foot_contact_timeline(
        video, pose_reference, evidence, caption_images, cache_dir)
    assert cached == timeline
    assert len(calls) == 2

    pose['frames'][0]['joints']['left_ankle'][0] += .02
    changed_crop = observe_foot_contact_timeline(
        video, pose_reference, evidence, caption_images, cache_dir)
    assert changed_crop['status'] == 'observed'
    assert len(calls) == 4  # Changed target crop cannot reuse the prior visual approval.

    pose['frames'][3]['joints']['left_ankle'][0] += .02

    def malformed_caption(*, frame_paths, response_schema, **_kwargs):
        calls.append((frame_paths, response_schema))
        return json.dumps({'samples': []})

    unresolved = observe_foot_contact_timeline(
        video, pose_reference, evidence, malformed_caption, cache_dir)
    assert unresolved['status'] == 'unknown'
    assert unresolved['reason'] == 'support_timeline_response_invalid'
    assert validated_body_support_contact_timeline(unresolved) is None
    unresolved_cached = observe_foot_contact_timeline(
        video, pose_reference, evidence, caption_images, cache_dir)
    assert unresolved_cached['status'] == 'observed'
    assert len(calls) == 8  # Protocol failure is retryable; visual uncertainty stays evidence.

    pose['frames'][6]['joints']['left_ankle'][0] += .02

    def partial_caption(*, frame_paths, response_schema, **_kwargs):
        ids = list(response_schema['properties'])
        calls.append((frame_paths, response_schema))
        return json.dumps({'samples': [
            {'sampleId': ids[0], 'contactState': 'full_sole',
             'surface': 'ground', 'visible': True},
            {'sampleId': ids[1], 'contactState': 'airborne',
             'surface': 'unknown', 'visible': False},
        ]})

    partial = observe_foot_contact_timeline(
        video, pose_reference, evidence, partial_caption, cache_dir)
    assert partial['retryable'] is True
    assert len(partial['samples']) == 2
    retained = partial['samples']
    repair_start = len(calls)
    repaired = observe_foot_contact_timeline(
        video, pose_reference, evidence, caption_images, cache_dir)
    assert repaired['retryable'] is False
    assert all(row in repaired['samples'] for row in retained)
    assert len(repaired['samples']) == 9
    requested = {sample_id for _paths, schema in calls[repair_start:] for sample_id in schema['properties']}
    assert not requested.intersection(row['sampleId'] for row in retained)
    assert len(requested) == 7
    assert partial['rawResponse'] in repaired['priorResponses']

    evidence['bodySupportObservation'] = {
        'status': 'observed', 'source': 'exact_source_visual_support_observation',
        'sourceVideoSha256': digest, 'contactTimeline': repaired,
    }
    evidence['footPatchEvidence']['feet']['right'] = {'states': ['unknown'] * len(patch_times)}
    evidence['feet']['right'] = {'contactIntervals': [{
        'contactMotion': 'stationary', 'sourceTimeBasis': 'absolute_source_video',
        'sourceStartTimeSec': 0., 'sourceEndTimeSec': 1.,
    }]}
    expanded = observe_foot_contact_timeline(video, pose_reference, evidence, caption_images, cache_dir)
    assert len(expanded['samples']) == 12
    assert all(sample in expanded['samples'] for sample in repaired['samples'])
    assert len(calls[-1][1]['properties']) == 3
    assert all('right' in sample_id for sample_id in calls[-1][1]['properties'])
    assert repaired['rawResponse'] in expanded['priorResponses']



def test_timed_visual_contact_materializes_only_explicit_ground_sample_frames():
    from exercise_motion_pkg.body_support_observation import (
        materialize_timed_visual_contact_points, validated_body_support_contact_timeline,
    )

    digest = 'b' * 64
    timeline = {
        'schemaVersion': 1, 'policyVersion': CONTACT_TIMELINE_POLICY_VERSION,
        'source': 'exact_source_visual_contact_timeline',
        'sourceVideoSha256': digest, 'sourceClock': 'video_frame_zero_seconds',
        'status': 'observed', 'requestSha256': 'request', 'responseSha256': 'response',
        'samples': [
            {'sampleId': 'contact-left-pose-1', 'sourceTimeSec': .5,
             'sourceFrameIndex': 15, 'sourceFps': 30., 'sourcePoseFrameIndex': 1,
             'side': 'left', 'contactState': 'forefoot', 'surface': 'ground',
             'visible': True, 'sourceTrackStationary': True},
            {'sampleId': 'contact-left-pose-2', 'sourceTimeSec': 1.,
             'sourceFrameIndex': 30, 'sourceFps': 30., 'sourcePoseFrameIndex': 2,
             'side': 'left', 'contactState': 'unknown', 'surface': 'unknown',
             'visible': False, 'sourceTrackStationary': True},
        ],
    }
    observed = {'status': 'observed', 'source': 'exact_source_visual_support_observation',
                'sourceVideoSha256': digest, 'contactTimeline': timeline}
    assert validated_body_support_contact_timeline(observed) is not None
    evidence = {'bodySupportObservation': observed, 'sourceVideoSha256': digest}
    frames = [{'sourceTimeSec': 0.}, {'sourceTimeSec': .5},
              {'sourceTimeSec': 1.}, {'sourceTimeSec': 1.5}]
    lineage = [
        {'selectedFrameIndex': index, 'selectedFrameTimeSec': index / 30.,
         'parentSourceFrameIndex': 211 + index,
         'parentSourceTimeSec': (211 + index) / (30000. / 1001.)}
        for index in range(16)
    ]
    evidence.update({
        'footPatchEvidence': {'sourceVideoSha256': digest},
        '_fitSourceTimelineMapping': {
            'schemaVersion': 1, 'verified': True,
            'mappingKind': 'selected_segment_to_parent_source',
            'selectedSegmentSha256': digest, 'parentSourceSha256': 'a' * 64,
            'selectedStartSeconds': 7.,
            'selectedFrameClockReceiptSha256': 'c' * 64,
            'parentSourceFps': 30000. / 1001.,
            'selectedFrameLineage': lineage,
        },
    })
    frames = [{'sourceTimeSec': (211 + index) / (30000. / 1001.)}
              for index in range(16)]
    materialize_timed_visual_contact_points(evidence, frames, ['left_foot'])
    contacts = evidence['supportContacts']
    assert len(contacts) == 1
    assert contacts[0]['contactTimelineSampleId'] == 'contact-left-pose-1'
    assert contacts[0]['jointName'] == 'left_foot'
    assert contacts[0]['contactState'] == 'toe_only'
    assert contacts[0]['_fitFrameBounds'] == [15, 15]
    assert contacts[0]['sourceTimeSec'] == 226 / (30000. / 1001.)
    assert contacts[0]['contactTimelineSourceTimeSec'] == .5
    assert contacts[0]['contactTimelineSourceVideoSha256'] == digest

    materialize_timed_visual_contact_points(
        evidence, frames, ['left_foot'], ground_contact_mode='none')
    assert evidence['supportContacts'] == []
    assert validated_body_support_contact_timeline(observed) is not None


    evidence['_fitSourceTimelineMapping']['selectedFrameLineage'] = [
        {'selectedFrameIndex': index, 'selectedFrameTimeSec': index / 30.,
         'parentSourceFrameIndex': 212 + index,
         'parentSourceTimeSec': (212 + index) / (30000. / 1001.)}
        for index in range(16)
    ]
    moved_frames = [{'sourceTimeSec': (212 + index) / (30000. / 1001.)}
                    for index in range(16)]
    materialize_timed_visual_contact_points(evidence, moved_frames, ['left_foot'])
    assert len(evidence['supportContacts']) == 1
    assert evidence['supportContacts'][0]['sourceTimeSec'] == 227 / (30000. / 1001.)
    assert evidence['supportContacts'][0]['_fitFrameBounds'] == [15, 15]

    evidence['bodySupportObservation']['contactTimeline']['status'] = 'unknown'
    materialize_timed_visual_contact_points(evidence, moved_frames, ['left_foot'])
    assert evidence['supportContacts'] == []

    from exercise_motion_pkg.contact_constraints import contact_frame_bounds
    evidence['bodySupportObservation']['contactTimeline']['status'] = 'observed'
    source_readiness_evidence = {'bodySupportObservation': observed,
                                 'sourceVideoSha256': digest,
                                 'footPatchEvidence': {'sourceVideoSha256': digest}}
    materialize_timed_visual_contact_points(source_readiness_evidence)
    assert len(source_readiness_evidence['supportContacts']) == 1
    assert contact_frame_bounds(source_readiness_evidence['supportContacts'][0], 10) == (0, -1)

    stale = deepcopy(observed)
    stale['contactTimeline']['sourceVideoSha256'] = 'different-video'
    assert validated_body_support_contact_timeline(stale) is None


def test_timed_visual_contact_requires_exposure_lineage_for_selected_cut():
    from exercise_motion_pkg.body_support_observation import materialize_timed_visual_contact_points

    digest = '9' * 64
    evidence = {
        'sourceVideoSha256': digest,
        'footPatchEvidence': {'sourceVideoSha256': digest},
        'bodySupportObservation': {
            'source': 'exact_source_visual_support_observation', 'status': 'observed',
            'sourceVideoSha256': digest,
            'contactTimeline': {
                'schemaVersion': 1, 'policyVersion': CONTACT_TIMELINE_POLICY_VERSION,
                'source': 'exact_source_visual_contact_timeline',
                'sourceVideoSha256': digest, 'sourceClock': 'video_frame_zero_seconds',
                'status': 'observed', 'requestSha256': 'req', 'responseSha256': 'resp',
                'samples': [{
                    'sampleId': 'first-cut-frame', 'sourceTimeSec': 0.,
                    'sourceFrameIndex': 0, 'sourceFps': 30000. / 1001.,
                    'sourcePoseFrameIndex': 0, 'side': 'left',
                    'contactState': 'full_sole', 'surface': 'ground',
                    'visible': True, 'sourceTrackStationary': True,
                }],
            },
        },
        '_fitSourceTimelineMapping': {
            'schemaVersion': 1, 'verified': True,
            'mappingKind': 'selected_segment_to_parent_source',
            'selectedSegmentSha256': digest, 'parentSourceSha256': '8' * 64,
            'selectedStartSeconds': 7.01,
            'selectedFrameClockReceiptSha256': '7' * 64,
            'parentSourceFps': 30000. / 1001.,
            'selectedFrameLineage': [{
                'selectedFrameIndex': 0, 'selectedFrameTimeSec': 0.,
                'parentSourceFrameIndex': 211,
                'parentSourceTimeSec': 211. / (30000. / 1001.),
            }],
        },
    }
    frames = [{'sourceTimeSec': 210. / (30000. / 1001.)},
              {'sourceTimeSec': 211. / (30000. / 1001.)}]
    materialize_timed_visual_contact_points(evidence, frames, ['left_foot'])
    assert len(evidence['supportContacts']) == 1
    contact = evidence['supportContacts'][0]
    assert contact['_fitFrameBounds'] == [1, 1]
    assert contact['sourceTimeSec'] == 211. / (30000. / 1001.)
    assert contact['sourceTimeSec'] != 7.01

    evidence['_fitSourceTimelineMapping'].pop('selectedFrameLineage')
    materialize_timed_visual_contact_points(evidence, frames, ['left_foot'])
    assert evidence['supportContacts'] == []


def test_unobserved_heel_keeps_timed_fullsole_review_as_forefoot_only_constraint():
    from exercise_motion_pkg.body_support_observation import materialize_timed_visual_contact_points

    digest = '6' * 64
    def materialize(pitch_reference):
        patch_side = {'states': ['toe_only'], 'pitchReferenceSource': pitch_reference}
        if pitch_reference is None:
            patch_side.pop('pitchReferenceSource')
        evidence = {
            'sourceVideoSha256': digest,
            'footPatchEvidence': {'sourceVideoSha256': digest, 'feet': {'left': patch_side}},
            'bodySupportObservation': {
                'source': 'exact_source_visual_support_observation', 'status': 'observed',
                'sourceVideoSha256': digest,
                'contactTimeline': {
                    'schemaVersion': 1, 'policyVersion': CONTACT_TIMELINE_POLICY_VERSION,
                    'source': 'exact_source_visual_contact_timeline',
                    'sourceVideoSha256': digest, 'sourceClock': 'video_frame_zero_seconds',
                    'status': 'observed', 'requestSha256': 'req', 'responseSha256': 'resp',
                    'samples': [{
                        'sampleId': 'fullsole-frame', 'sourceTimeSec': 0.,
                        'sourceFrameIndex': 0, 'sourceFps': 30., 'sourcePoseFrameIndex': 0,
                        'side': 'left', 'contactState': 'full_sole', 'surface': 'ground',
                        'visible': True, 'sourceTrackStationary': True,
                    }],
                },
            },
            '_fitSourceTimelineMapping': {
                'schemaVersion': 1, 'verified': True,
                'mappingKind': 'selected_segment_to_parent_source',
                'selectedSegmentSha256': digest, 'parentSourceSha256': '5' * 64,
                'selectedStartSeconds': 0., 'selectedFrameClockReceiptSha256': '4' * 64,
                'parentSourceFps': 30.,
                'selectedFrameLineage': [{
                    'selectedFrameIndex': 0, 'selectedFrameTimeSec': 0.,
                    'parentSourceFrameIndex': 0, 'parentSourceTimeSec': 0.,
                }],
            },
        }
        materialize_timed_visual_contact_points(evidence, [{'sourceTimeSec': 0.}], ['left_foot'])
        return evidence['supportContacts']

    unknown_heel = materialize('heel_unobserved')
    assert len(unknown_heel) == 1 and unknown_heel[0]['contactState'] == 'toe_only'
    assert unknown_heel[0]['jointName'] == 'left_foot'
    assert 'ankleAnchorGroupId' not in unknown_heel[0]
    # Calibrated or missing provenance retains the original full-sole semantics.
    assert materialize('relative_stance')[0]['contactState'] == 'full_sole'
    assert materialize(None)[0]['contactState'] == 'full_sole'


def test_contact_timeline_crop_marks_selected_ankle_and_keeps_label_outside_source():
    import cv2
    import numpy as np
    from exercise_motion_pkg.body_support_observation import (
        _assemble_contact_timeline_atlas, _render_contact_timeline_crop,
    )

    frame = np.full((200, 320, 3), 100, dtype=np.uint8)
    candidate = {'side': 'left', 'sampleId': 'contact-left-pose-10',
                 'ankle': [.5, .75]}
    rendered, marker, bounds, header_height = _render_contact_timeline_crop(
        cv2, frame, candidate)
    x0, y0, x1, y1 = bounds
    left_padding = marker[0] - (160 - x0)

    assert rendered.shape[0] == header_height + (y1 - y0)
    assert rendered.shape[1] > (x1 - x0)  # Long label gets its own full-width header.
    assert marker == (left_padding + 160 - x0, header_height + 150 - y0)
    _, _, wider_bounds, _ = _render_contact_timeline_crop(
        cv2, frame, {**candidate, 'knee': [.8, .5]}, mark_target=False)
    assert wider_bounds[0] < x0 and wider_bounds[2] > x1
    assert wider_bounds[1] < y0 and wider_bounds[3] >= y1
    # A source pixel away from the tiny crosshair remains unchanged below the header.
    assert np.array_equal(rendered[header_height + 2, left_padding + 2], [100, 100, 100])
    # The exact target location has the high-contrast yellow center marker.
    assert np.all(rendered[marker[1], marker[0]] >= [0, 250, 250])

    sole_crop, sole_marker, _, _ = _render_contact_timeline_crop(cv2, frame, {
        'side': 'left', 'sampleId': 'sole-midpoint', 'landmark': 'foot',
        'point': [.42, .82], 'heel': [.38, .82], 'toe': [.46, .82]})
    assert np.all(sole_crop[sole_marker[1], sole_marker[0]] >= [0, 250, 250])

    ids = [f'contact-left-pose-{index}' for index in range(9)]
    tiles = [_render_contact_timeline_crop(
        cv2, frame, {'side': 'left', 'sampleId': sample_id,
                     'ankle': [.35 + index * .03, .75]})[0]
             for index, sample_id in enumerate(ids)]
    atlas_data = _assemble_contact_timeline_atlas(tiles, ids)
    assert atlas_data is not None
    atlas, positions = atlas_data
    assert len(positions) == 9
    for tile, (x, y, width, height) in zip(tiles, positions):
        assert np.array_equal(atlas[y:y + height, x:x + width], tile)
    assert _assemble_contact_timeline_atlas(tiles, ['duplicate'] * 9) is None

def test_current_support_observation_retains_timed_evidence_over_coarse_cache(tmp_path):
    import hashlib
    from exercise_motion_pkg.body_support_observation import (
        observe_body_support, validated_body_support_contact_timeline,
    )

    video = tmp_path / 'source.mp4'
    video.write_bytes(b'exact source bytes')
    digest = hashlib.sha256(video.read_bytes()).hexdigest()
    coarse = {'status': 'observed', 'source': 'exact_source_visual_support_observation',
              'policyVersion': POLICY_VERSION, 'sourceVideoSha256': digest,
              'observation': {'leftFoot': 'stationary_full_sole', 'leftFootSurface': 'ground'}}
    cache = tmp_path / f'body-support-{digest}-v{POLICY_VERSION}.json'
    cache.write_text(json.dumps(coarse))
    current = deepcopy(coarse)
    current['contactTimeline'] = {
        'schemaVersion': 1, 'policyVersion': CONTACT_TIMELINE_POLICY_VERSION, 'status': 'observed',
        'source': 'exact_source_visual_contact_timeline', 'sourceVideoSha256': digest,
        'sourceClock': 'video_frame_zero_seconds', 'samples': [{
            'sampleId': 'left-contact', 'side': 'left', 'sourceTimeSec': 0.,
            'sourceFrameIndex': 0, 'sourcePoseFrameIndex': 0, 'sourceFps': 30.,
            'sourceTrackStationary': True, 'contactState': 'full_sole',
            'surface': 'ground', 'visible': True,
        }],
    }
    before = deepcopy(current)
    result = observe_body_support(video, None, tmp_path, existing_observation=current)
    assert validated_body_support_contact_timeline(result) == current['contactTimeline']['samples']
    assert current == before
    current['sourceVideoSha256'] = 'another video'
    result = observe_body_support(video, None, tmp_path, existing_observation=current)
    assert 'contactTimeline' not in result
    assert result['sourceVideoSha256'] == digest


def test_invalid_support_response_cache_is_reobserved_with_schema(tmp_path, monkeypatch):
    import hashlib
    import cv2
    import numpy as np
    from exercise_motion_pkg.body_support_observation import observe_body_support, POLICY_VERSION

    video = tmp_path / 'source.mp4'
    video.write_bytes(b'retained exact source')
    digest = hashlib.sha256(video.read_bytes()).hexdigest()
    cache = tmp_path / f'body-support-{digest}-v{POLICY_VERSION}.json'
    cache.write_text(json.dumps({'status':'unknown', 'reason':'support_observation_schema_invalid',
                                'policyVersion':POLICY_VERSION, 'sourceVideoSha256':digest}))
    class Capture:
        def get(self, _): return 5
        def set(self, *_): pass
        def read(self): return True, np.zeros((16, 16, 3), dtype=np.uint8)
        def release(self): pass
    monkeypatch.setattr(cv2, 'VideoCapture', lambda _: Capture())
    calls = []
    def caption(**kwargs):
        calls.append(kwargs)
        return json.dumps({'leftFoot':'stationary_full_sole', 'leftFootSurface':'ground'})
    result = observe_body_support(video, caption, tmp_path)
    assert result['status'] == 'observed'
    assert calls[0]['response_schema']['additionalProperties'] is False
    assert observe_body_support(video, caption, tmp_path) == result
    assert len(calls) == 1

    legacy = {'status': 'observed', 'source': 'exact_source_visual_support_observation',
              'sourceVideoSha256': digest, 'policyVersion': POLICY_VERSION,
              'observation': {'leftHand': 'stationary_support',
                              'leftFoot': 'stationary_full_sole', 'leftFootSurface': 'ground'}}
    cache.write_text(json.dumps(legacy))
    safe_cached = observe_body_support(video, None, tmp_path)
    assert 'leftHand' not in safe_cached['observation']
    assert safe_cached['observation']['leftFoot'] == 'stationary_full_sole'
    assert observe_body_support(video, caption, tmp_path)['status'] == 'observed'
    assert len(calls) == 2


def test_required_support_fields_refresh_incomplete_cache_and_preserve_conflicts(tmp_path, monkeypatch):
    import hashlib
    import cv2
    import numpy as np
    from exercise_motion_pkg.body_support_observation import observe_body_support, POLICY_VERSION, _review_model_identity

    video = tmp_path / 'source.mp4'
    video.write_bytes(b'exact source for required support cache refresh')
    digest = hashlib.sha256(video.read_bytes()).hexdigest()
    cache = tmp_path / f'body-support-{digest}-v{POLICY_VERSION}.json'
    previous = {
        'status': 'observed', 'source': 'exact_source_visual_support_observation',
        'sourceVideoSha256': digest, 'policyVersion': POLICY_VERSION,
        'reviewIdentity': _review_model_identity(None),
        'observation': {
            'leftKnee': 'stationary_support', 'leftKneeContactSurface': 'floor',
            'rightKnee': 'stationary_support', 'rightKneeContactSurface': 'floor',
            'leftHand': 'stationary_support', 'leftHandContactSurface': 'fixed_bar',
            'rightHand': 'unknown',
        },
    }
    cache.write_text(json.dumps(previous))

    class Capture:
        def get(self, _): return 5
        def set(self, *_): pass
        def read(self): return True, np.zeros((16, 16, 3), dtype=np.uint8)
        def release(self): pass

    monkeypatch.setattr(cv2, 'VideoCapture', lambda _: Capture())
    calls = []

    def caption(**kwargs):
        calls.append(kwargs)
        return json.dumps({
            'leftKnee': 'stationary_support', 'leftKneeContactSurface': 'floor',
            'rightKnee': 'stationary_support', 'rightKneeContactSurface': 'floor',
            'leftHand': 'moving', 'leftHandContactSurface': 'none',
            'rightHand': 'stationary_support', 'rightHandContactSurface': 'fixed_bar',
        })

    required = {'leftHand', 'leftHandContactSurface', 'rightHand', 'rightHandContactSurface'}
    result = observe_body_support(video, caption, tmp_path, required_observation_fields=required)
    assert len(calls) == 1
    assert result['observation']['leftHand'] == 'unknown'
    assert result['observation']['rightHand'] == 'stationary_support'
    assert result['observationConflicts']['leftHand'] == ['stationary_support', 'moving']
    assert result['previousObservations'][0]['observation']['leftHand'] == 'stationary_support'
    assert observe_body_support(video, caption, tmp_path, required_observation_fields=required) == result
    assert len(calls) == 1

    unknown_video = tmp_path / 'unknown-source.mp4'
    unknown_video.write_bytes(b'exact source with explicit unknown support')
    unknown_digest = hashlib.sha256(unknown_video.read_bytes()).hexdigest()
    unknown_cache = tmp_path / f'body-support-{unknown_digest}-v{POLICY_VERSION}.json'
    unknown_cache.write_text(json.dumps({
        'status': 'observed', 'source': 'exact_source_visual_support_observation',
        'sourceVideoSha256': unknown_digest, 'policyVersion': POLICY_VERSION,
        'reviewIdentity': _review_model_identity(None),
        'observation': {
            'leftHand': 'unknown', 'leftHandContactSurface': 'unknown',
            'rightHand': 'unknown', 'rightHandContactSurface': 'unknown',
        },
    }))
    reused_unknown = observe_body_support(
        unknown_video, caption, tmp_path, required_observation_fields=required)
    assert all(reused_unknown['observation'][field] == 'unknown' for field in required)
    assert len(calls) == 1


def test_reviewer_identity_matches_callable_instance_and_bound_method(monkeypatch):
    from types import SimpleNamespace
    from exercise_motion_pkg import bake_and_rank
    from exercise_motion_pkg.body_support_observation import _review_model_identity

    monkeypatch.setattr(
        bake_and_rank,
        'source_review_model_identity',
        lambda settings: {key: value for key, value in vars(settings).items()
                          if key.startswith('llama_cpp_')} if settings is not None else {},
    )

    class Captioner:
        def __init__(self, settings):
            self.settings = settings

        def __call__(self, **_kwargs):
            return '{}'

    settings = SimpleNamespace(
        llama_cpp_model='model-a.gguf',
        llama_cpp_mmproj='vision-a.gguf',
        llama_cpp_ctx_size=49152,
    )
    captioner = Captioner(settings)
    assert _review_model_identity(captioner) == _review_model_identity(captioner.__call__)

    changed = Captioner(SimpleNamespace(
        llama_cpp_model='model-b.gguf',
        llama_cpp_mmproj='vision-a.gguf',
        llama_cpp_ctx_size=49152,
    ))
    assert _review_model_identity(changed) != _review_model_identity(captioner)


def test_contradictory_torso_claim_preserves_independent_foot_evidence():
    from exercise_motion_pkg.body_support_observation import POLICY_VERSION, validated_body_support_answer
    observed = {'status':'observed', 'source':'exact_source_visual_support_observation',
                'sourceVideoSha256':'source', 'policyVersion':POLICY_VERSION,
                'observation':{'pelvis':'moving', 'upperBack':'moving',
                               'pelvisContactSurface':'bench', 'upperBackContactSurface':'bench',
                               'pelvisAndUpperBackSameSurface':True,
                               'leftFoot':'stationary_full_sole', 'leftFootSurface':'ground'}}
    answer = validated_body_support_answer(observed)
    assert answer['leftFoot'] == 'stationary_full_sole'
    assert 'pelvisAndUpperBackSameSurface' not in answer
    assert observed['observation']['pelvisAndUpperBackSameSurface'] is True


def test_contradictory_foot_claim_does_not_authorize_that_foot():
    from exercise_motion_pkg.body_support_observation import POLICY_VERSION, validated_body_support_answer
    observed = {'status':'observed', 'source':'exact_source_visual_support_observation',
                'sourceVideoSha256':'source', 'policyVersion':POLICY_VERSION,
                'observation':{'leftFoot':'unknown', 'leftFootSurface':'ground',
                               'rightFoot':'stationary_full_sole', 'rightFootSurface':'ground'}}
    answer = validated_body_support_answer(observed)
    assert 'leftFoot' not in answer
    assert 'leftFootSurface' not in answer
    assert answer['rightFoot'] == 'stationary_full_sole'


def test_stationary_contact_state_requires_every_frame_and_independent_motion():
    from exercise_motion_pkg.body_support_observation import _stance_from_frame_contacts as classify
    facts = {'0': 'full_sole_ground', '1': 'full_sole_ground',
             'heelMotion': 'stationary', 'forefootMotion': 'stationary'}
    ids = ['0', '1']
    assert classify(facts, ids) == 'stationary_full_sole_ground'
    assert classify({**facts, '1': 'forefoot_ground'}, ids) == 'stationary_forefoot_ground'
    assert classify({**facts, 'heelMotion': 'moving'}, ids) == 'stationary_forefoot_ground'
    assert classify({**facts, 'heelMotion': 'not_visible'}, ids) == 'stationary_forefoot_ground'
    for value in ('heel_only_ground', 'airborne'):
        assert classify({**facts, '1': value}, ids) == 'moving_or_releasing'
    assert classify({**facts, 'forefootMotion': 'moving'}, ids) == 'moving_or_releasing'
    for value in ('unresolved', 'full_sole_raised_surface'):
        assert classify({**facts, '1': value}, ids) == 'insufficient_evidence'
    assert classify({**facts, 'forefootMotion': 'not_visible'}, ids) == 'insufficient_evidence'
    assert classify({**facts, '0': []}, ids) is None
    assert classify({key: value for key, value in facts.items() if key != '1'}, ids) is None
    assert classify({**facts, 'extra': 'full_sole_ground'}, ids) is None


def test_targeted_knee_refresh_does_not_reuse_legacy_unknown(tmp_path):
    import hashlib
    import json
    from exercise_motion_pkg import body_support_observation as module
    video = tmp_path / 'video.mp4'
    video.write_bytes(b'fixture')
    digest = hashlib.sha256(video.read_bytes()).hexdigest()
    cache = tmp_path / f'body-support-{digest}-v{POLICY_VERSION}.json'
    retained = {'status': 'unknown', 'reason': 'legacy_support_capability_unavailable',
                'policyVersion': POLICY_VERSION, 'sourceVideoSha256': digest}
    cache.write_text(json.dumps(retained))
    assert module.observe_body_support(video, None, tmp_path) == retained
    assert module.observe_body_support(video, None, tmp_path, require_knee_observation=True) == {
        'status': 'unknown', 'reason': 'support_observer_unavailable'}
    retained['reason'] = 'support_source_frame_unavailable'
    cache.write_text(json.dumps(retained))
    assert module.observe_body_support(video, None, tmp_path, require_knee_observation=True) == retained


def test_stationary_knee_requests_contact_observation_without_claiming_contact():
    from exercise_motion_pkg.body_support_observation import source_support_observation_needed

    pose = {'coordinateSpace': 'normalized_image_xy', 'frames': [
        {'joints': {'left_knee': [.5, .8], 'nose': [.2 + i * .05, .1]}}
        for i in range(8)]}
    evidence = {}
    assert source_support_observation_needed(pose, evidence)
    assert evidence == {}
    moving = deepcopy(pose)
    for i, frame in enumerate(moving['frames']):
        frame['joints']['left_knee'][0] += i * .05
    assert not source_support_observation_needed(moving, evidence)
    assert not source_support_observation_needed(None, evidence)


def test_body_contact_crop_includes_region_above_locator_without_painting_source():
    import cv2
    import numpy as np
    from exercise_motion_pkg.body_support_observation import _render_contact_timeline_crop

    frame = np.full((240, 320, 3), 100, dtype=np.uint8)
    # A visible hand/bar interface lies above the wrist center.
    frame[38:43, 145:175] = [30, 80, 190]
    rendered, marker, bounds, header = _render_contact_timeline_crop(cv2, frame, {
        'side': 'left', 'sampleId': 'hand-start', 'landmark': 'joint',
        'jointName': 'left_wrist', 'contactRegion': 'hand', 'point': [.5, .25],
    }, mark_target=False)
    x0, y0, x1, y1 = bounds
    assert y0 <= 38 < 43 <= y1
    left_padding = marker[0] - (160 - x0)
    np.testing.assert_array_equal(
        rendered[header:, left_padding:left_padding + x1 - x0], frame[y0:y1, x0:x1])
    assert rendered[marker[1], marker[0]].tolist() == frame[60, 160].tolist()


def test_legacy_contact_timeline_is_invalidated_when_crop_policy_changes():
    from exercise_motion_pkg.body_support_observation import (
        CONTACT_TIMELINE_POLICY_VERSION, validated_body_support_contact_timeline)

    assert CONTACT_TIMELINE_POLICY_VERSION > 1
    legacy = {
        'schemaVersion': 1, 'policyVersion': 1,
        'source': 'exact_source_visual_contact_timeline',
        'sourceVideoSha256': 'same-source-video',
        'sourceClock': 'video_frame_zero_seconds', 'status': 'observed',
        'samples': [{
            'sampleId': 'contact-left-pose-0', 'sourceTimeSec': 0.0,
            'side': 'left', 'contactState': 'unknown', 'surface': 'unknown',
            'visible': False, 'sourceTrackStationary': True,
            'sourcePoseFrameIndex': 0, 'sourceFrameIndex': 0, 'sourceFps': 30.0,
        }],
    }

    assert validated_body_support_contact_timeline(
        legacy, expected_video_sha256='same-source-video') is None


def test_labeled_support_components_bind_categories_without_anatomical_side_guessing(tmp_path, monkeypatch):
    import hashlib
    import cv2
    import numpy as np
    from exercise_motion_pkg import body_support_observation as module, foot_contact_observation as foot
    video = tmp_path/'source.mp4'
    video.write_bytes(b'exact source with source-coded component identities')
    digest = hashlib.sha256(video.read_bytes()).hexdigest()
    old = {'status': 'observed', 'source': 'exact_source_visual_support_observation',
           'sourceVideoSha256': digest, 'policyVersion': module.POLICY_VERSION,
           'observation': {'leftFoot': 'stationary_full_sole', 'leftFootSurface': 'raised_surface',
                           'rightFoot': 'stationary_full_sole', 'rightFootSurface': 'ground',
                           'pelvis': 'moving', 'pelvisContactSurface': 'bench'}}
    cache = tmp_path/f'body-support-{digest}-v{module.POLICY_VERSION}.json'
    cache.write_text(json.dumps(old))
    original_bytes = cache.read_bytes()
    landmarks = {'available': True, 'sourceVideoSha256': digest, 'frames': [
        {'timeSeconds': float(i), 'joints': {
            'left_ankle': {'image': [.2, .8], 'confidence': .99},
            'right_ankle': {'image': [.8, .5], 'confidence': .99},
            'left_hip': {'image': [.4, .4], 'confidence': .99},
            'right_hip': {'image': [.6, .4], 'confidence': .99}}} for i in range(5)]}
    monkeypatch.setattr(foot, 'load_cached_foot_landmarks', lambda path: landmarks)
    class Capture:
        def get(self, prop): return 5 if prop == cv2.CAP_PROP_FRAME_COUNT else 1.
        def set(self, *_): pass
        def read(self): return True, np.zeros((64, 64, 3), dtype=np.uint8)
        def release(self): pass
    monkeypatch.setattr(cv2, 'VideoCapture', lambda path: Capture())
    calls = []
    def caption(**kwargs):
        calls.append(kwargs)
        assert 'A' in kwargs['response_schema']['properties']
        assert 'leftFoot' not in kwargs['response_schema']['properties']
        assert '"leftFoot"' not in kwargs['prompt']
        assert all('-labeled' in path.name for path in kwargs['frame_paths'])
        return json.dumps({'A': 'stationary_full_sole', 'ASurface': 'ground',
                           'B': 'supported_dorsum', 'BSurface': 'raised_surface',
                           'P': 'moving', 'PContactSurface': 'none'})
    result = module.observe_body_support(video, caption, tmp_path, existing_observation=old,
                                         require_labeled_identity=True)
    assert result['observation']['leftFootSurface'] == 'ground'
    assert result['observation']['rightFoot'] == 'supported_dorsum'
    assert result['observation']['rightFootSurface'] == 'raised_surface'
    assert result['observation']['pelvisContactSurface'] == 'none'
    assert result['identityMarkers']['fieldMap']['A'] == 'leftFoot'
    assert result['identityMarkers']['fieldMap']['B'] == 'rightFoot'
    assert result['identityMarkers']['frames'][0]['components']['A']['sourceJoint'] == 'left_ankle'
    assert cache.read_bytes() == original_bytes
    assert module.observe_body_support(video, caption, tmp_path, require_labeled_identity=True) == result
    assert len(calls) == 1
    landmarks['sourceVideoSha256'] = 'other source'
    unknown = module.observe_body_support(video, caption, tmp_path, require_labeled_identity=True)
    assert unknown['status'] == 'unknown'
    assert unknown['reason'] == 'support_source_identity_unavailable'


def test_uncalibrated_foot_patch_keeps_reviewed_surface_without_valid_body_answer():
    import numpy as np
    from exercise_motion_pkg.foot_contact_observation import _materialize_foot_patch_contacts

    contacts = _materialize_foot_patch_contacts(
        side='left', states=['toe_only'] * 3, valid=np.ones(3, dtype=bool),
        toe_valid=np.ones(3, dtype=bool), heel_points=np.zeros((3, 2)),
        toe_points=np.array([[0., 0.], [.001, 0.], [.002, 0.]]),
        foot_sizes=np.ones(3), image_pitch=np.zeros(3), world_pitch=np.zeros(3),
        image_only_toe=np.zeros(3, dtype=bool),
        unresolved_heel_recontact=np.zeros(3, dtype=bool), references=[0., 0.],
        tolerances=[.1, .1], uncalibrated_toe=True,
        uncalibrated_surface_kind='ground', support_contacts=[],
    )

    assert contacts[0]['surfaceKind'] == 'ground'


def test_unsupported_stationary_joint_is_not_a_support_candidate():
    from exercise_motion_pkg.body_support_observation import (
        _contact_timeline_candidates, validated_body_support_answer,
    )
    pose = {'coordinateSpace': 'normalized_image_xy', 'frames': [
        {'sourceTimeSec': i / 10., 'joints': {
            'left_knee': [.4, .6], 'left_hip': [.4, .4], 'nose': [.5, .1]},
         'jointConfidence': {'left_knee': .95}} for i in range(6)]}
    observed = {'status': 'observed', 'source': 'exact_source_visual_support_observation',
                'sourceVideoSha256': 'a' * 64, 'policyVersion': POLICY_VERSION,
                'observation': {'leftKnee': 'unsupported', 'leftKneeContactSurface': 'none'}}
    evidence = {'bodySupportObservation': observed}
    assert validated_body_support_answer(observed)['leftKnee'] == 'unsupported'
    assert _contact_timeline_candidates(pose, evidence) == []
    observed['observation']['leftKneeContactSurface'] = 'bench'
    assert validated_body_support_answer(observed) is None
    observed['observation']['leftKnee'] = 'stationary_support'
    assert len(_contact_timeline_candidates(pose, evidence)) == 2


def test_stationary_foot_claim_can_request_review_without_an_inferred_ground_interval():
    from exercise_motion_pkg.body_support_observation import _contact_timeline_candidates
    times = [i / 10. for i in range(6)]
    pose = {'coordinateSpace': 'normalized_image_xy', 'imageWidth': 854, 'imageHeight': 480,
            'frames': [{'sourceTimeSec': time, 'joints': {
                'right_ankle': [.4, .8], 'right_hip': [.4, .5], 'nose': [.5, .1]},
                'jointConfidence': {'right_ankle': .95}} for time in times]}
    evidence = {'bodySupportObservation': {
        'status': 'observed', 'source': 'exact_source_visual_support_observation',
        'sourceVideoSha256': 'a' * 64, 'policyVersion': POLICY_VERSION,
        'observation': {'rightFoot': 'stationary_full_sole', 'rightFootSurface': 'ground'}},
        'footPatchEvidence': {'sourceTimesSec': times, 'sourceTimeBasis': 'absolute_source_video',
            'feet': {'right': {'states': ['unknown'] * 6, 'heelImageObservations': [
                {'sourceTimeSec': time, 'heelImagePoint': [.38 * 854 / 480, .82],
                 'toeImagePoint': [.46 * 854 / 480, .82], 'heelConfidence': .95,
                 'toeConfidence': .95} for time in times]}}},
        'contacts': []}
    original = deepcopy(evidence)
    rows = _contact_timeline_candidates(pose, evidence)
    assert [row['sourceTimeSec'] for row in rows] == [times[i] for i in (0, 3, 5)]
    assert evidence == original  # Review proposals never create contact authority.
    evidence['bodySupportObservation']['observation']['rightFoot'] = 'moving'
    rows = _contact_timeline_candidates(pose, evidence)
    assert [row['sourceTimeSec'] for row in rows] == [times[i] for i in (0, 3, 5)]
    assert all(row['reviewOnly'] and row['sourceTrackStationary'] is False for row in rows)


def test_source_pose_midpoint_confidence_propagates_only_from_two_observed_keypoints():
    from exercise_motion_pkg.bake_and_rank import source_pose_skeleton_payload_for_window
    from exercise_motion_pkg.body_support_observation import _contact_timeline_candidates
    from exercise_motion_pkg.segment_detection import DetectionWindow

    keypoints = {
        'left_hip': [.42, .62, .91], 'right_hip': [.58, .62, .84],
        'left_shoulder': [.40, .40, .77], 'right_shoulder': [.60, .40, .72],
        'nose': [.50, .20, .95],
    }

    def produce(points):
        payload = {'dominantPoseSamples': [
            {'timeSeconds': index / 10., 'keypoints': deepcopy(points)} for index in range(6)],
            'sampleFps': 10., 'dominantPoseSampleCoordinateSpace': 'normalized_image_xy'}
        return source_pose_skeleton_payload_for_window(
            payload, candidate_window=DetectionWindow(index=0, start_seconds=0., end_seconds=.5))

    pose = produce(keypoints)
    frame = pose['frames'][0]
    assert frame['joints']['pelvis'] == pytest.approx([.5, .62, 0.])
    assert frame['joints']['hips'] == pytest.approx(frame['joints']['pelvis'])
    assert frame['joints']['shoulders'] == pytest.approx([.5, .4, 0.])
    assert frame['jointConfidence']['pelvis'] == pytest.approx(.84)
    assert frame['jointConfidence']['hips'] == pytest.approx(.84)
    assert frame['jointConfidence']['shoulders'] == pytest.approx(.72)

    evidence = {'bodySupportObservation': {
        'status': 'observed', 'source': 'exact_source_visual_support_observation',
        'sourceVideoSha256': 'a' * 64, 'policyVersion': POLICY_VERSION,
        'observation': {'pelvis': 'stationary_support', 'pelvisContactSurface': 'bench'}}}
    candidates = _contact_timeline_candidates(pose, evidence)
    assert [row['sourceTimeSec'] for row in candidates] == [0., .5]
    assert {row['jointName'] for row in candidates} == {'pelvis'}

    low_confidence = deepcopy(keypoints)
    low_confidence['right_hip'][2] = .3
    low_pose = produce(low_confidence)
    assert low_pose['frames'][0]['jointConfidence']['pelvis'] == pytest.approx(.3)
    assert _contact_timeline_candidates(low_pose, evidence) == []

    one_sided = deepcopy(keypoints)
    del one_sided['right_hip']
    one_sided_pose = produce(one_sided)
    assert one_sided_pose['frames'][0]['joints']['pelvis'] == pytest.approx(
        one_sided_pose['frames'][0]['joints']['left_hip'])
    assert 'pelvis' not in one_sided_pose['frames'][0]['jointConfidence']
    assert _contact_timeline_candidates(one_sided_pose, evidence) == []

    missing_confidence = deepcopy(keypoints)
    missing_confidence['left_hip'] = missing_confidence['left_hip'][:2]
    no_confidence_pose = produce(missing_confidence)
    assert 'pelvis' not in no_confidence_pose['frames'][0]['jointConfidence']
    assert _contact_timeline_candidates(no_confidence_pose, evidence) == []


def test_contact_timeline_keeps_code_owned_surface_and_rejects_contradictory_answers():
    from exercise_motion_pkg.body_support_observation import (
        _contact_timeline_response_schema, _validated_contact_timeline_response)

    candidate = {'sampleId': 'hand', 'landmark': 'joint', 'jointName': 'left_wrist',
                 'side': 'left', 'expectedSurface': 'fixed_bar', 'sourceTimeSec': .5,
                 'poseFrameIndex': 1, 'sourceFrameIndex': 15, 'sourceFps': 30.}
    schema = _contact_timeline_response_schema(['hand'], candidates=[candidate])
    assert schema['properties']['hand']['enum'] == ['direct_contact', 'no_contact', 'unresolved']
    rows = _validated_contact_timeline_response(json.dumps({'hand': 'direct_contact'}), [candidate])
    assert rows[0]['surface'] == 'fixed_bar'
    assert rows[0]['contactState'] == 'direct_contact'
    assert rows[0]['sourceFrameIndex'] == 15
    contradictory = {'samples': [{'sampleId': 'hand', 'contactState': 'direct_contact',
                                   'surface': 'other', 'visible': True}]}
    assert _validated_contact_timeline_response(json.dumps(contradictory), [candidate]) is None
    assert _validated_contact_timeline_response(
        json.dumps({'hand': 'direct_contact_other'}), [candidate]) is None
    foot = {**candidate, 'sampleId': 'foot', 'landmark': 'foot'}
    rows = _validated_contact_timeline_response(json.dumps({'foot': 'full_sole_ground'}), [foot])
    assert rows[0]['contactState'] == 'full_sole'
    assert rows[0]['surface'] == 'ground'


def test_contact_timeline_alias_batches_resume_and_reuse_exact_legacy_rows(tmp_path, monkeypatch):
    import cv2
    import hashlib
    import numpy as np
    import pytest
    from exercise_motion_pkg.body_support_observation import (
        POLICY_VERSION, _assemble_contact_timeline_atlas,
        _contact_timeline_candidates, _contact_timeline_request_fingerprint,
        _nonfoot_contact_timeline_prompt, _render_contact_timeline_crop,
        _review_model_identity, _write_contact_timeline_batch,
        observe_foot_contact_timeline, validated_body_support_contact_timeline,
    )

    video = tmp_path / 'selected.mp4'
    video.write_bytes(b'exact selected source for batch resume')
    digest = hashlib.sha256(video.read_bytes()).hexdigest()

    class Capture:
        def __init__(self, _path):
            self.position = 0

        def get(self, prop):
            return {cv2.CAP_PROP_FPS: 10., cv2.CAP_PROP_FRAME_COUNT: 6}.get(prop, 0.)

        def set(self, _prop, value):
            self.position = int(value)

        def read(self):
            return True, np.zeros((120, 160, 3), dtype=np.uint8)

        def release(self):
            pass

    monkeypatch.setattr(cv2, 'VideoCapture', Capture)
    pose = {
        'coordinateSpace': 'normalized_image_xy',
        'imageWidth': 160, 'imageHeight': 120,
        'frames': [
            {'sourceTimeSec': index / 10., 'joints': {'pelvis': [.5, .5]},
             'jointConfidence': {'pelvis': .95}}
            for index in range(6)
        ],
    }
    evidence = {
        'sourceVideoSha256': digest,
        'bodySupportObservation': {
            'status': 'observed', 'source': 'exact_source_visual_support_observation',
            'sourceVideoSha256': digest, 'policyVersion': POLICY_VERSION,
            'observation': {'pelvis': 'stationary_support', 'pelvisContactSurface': 'floor'},
        },
    }
    pose_reference = {'sourceVideoSha256': digest, 'pose': pose}
    cache_dir = tmp_path / 'timeline-cache'
    cache_dir.mkdir()
    candidates = _contact_timeline_candidates(pose, evidence)
    assert [row['sampleId'] for row in candidates] == [
        'contact-pelvis-pose-0', 'contact-pelvis-pose-5']

    caption_calls = []

    def caption(*, response_schema, **_kwargs):
        caption_calls.append(tuple(response_schema['properties']))
        raise RuntimeError('simulated interruption before new batch response')

    # Seed one exact pre-alias single-sample batch; its input digest and parser remain unchanged.
    review_identity = _review_model_identity(caption)
    request_sha = _contact_timeline_request_fingerprint(candidates, digest, review_identity)
    candidate = dict(candidates[0])
    frame_index = int(round(candidate['sourceTimeSec'] * 10.))
    candidate['sourceFrameIndex'] = frame_index
    candidate['sourceFps'] = 10.
    candidate['sourceTimeSec'] = frame_index / 10.
    frame = np.zeros((120, 160, 3), dtype=np.uint8)
    crop, _marker, _bounds, _header = _render_contact_timeline_crop(
        cv2, frame, candidate, mark_target=False)
    scene = cv2.resize(frame, (crop.shape[1], max(1, round(
        frame.shape[0] * crop.shape[1] / frame.shape[1]))))
    atlas, _ = _assemble_contact_timeline_atlas(
        [cv2.vconcat([scene, crop])], [candidate['sampleId']])
    legacy_atlas = cache_dir / f'{request_sha}-contact-0.png'
    assert cv2.imwrite(str(legacy_atlas), atlas)
    raw_legacy = json.dumps({'choice': 'direct_contact'})
    old_schema = {'type': 'object', 'additionalProperties': False, 'required': ['choice'],
                  'properties': {'choice': {'type': 'string', 'enum': [
                      'direct_contact', 'no_contact', 'unresolved']}}}
    old_identity = {
        'schemaVersion': 1, 'policyVersion': 8,
        'requestSha256': request_sha, 'sourceVideoSha256': digest,
        'reviewIdentity': review_identity, 'batchIndex': 0,
        'sampleIds': [candidate['sampleId']],
        'atlasSha256': hashlib.sha256(legacy_atlas.read_bytes()).hexdigest(),
        'promptSha256': hashlib.sha256(_nonfoot_contact_timeline_prompt(candidate).encode()).hexdigest(),
        'responseSchemaSha256': hashlib.sha256(json.dumps(
            old_schema, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest(),
        'maxTokens': 160,
    }
    old_key = hashlib.sha256(json.dumps(
        old_identity, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
    _write_contact_timeline_batch(cache_dir / f'{request_sha}-batch-{old_key}.json', {
        **old_identity, 'rawResponse': raw_legacy,
        'responseSha256': hashlib.sha256(raw_legacy.encode()).hexdigest(),
    })

    with pytest.raises(RuntimeError, match='simulated interruption'):
        observe_foot_contact_timeline(video, pose_reference, evidence, caption, cache_dir)
    assert caption_calls == [('A',)]  # only the unreviewed source sample was requested

    missing_alias_calls = []

    def missing_alias(*, response_schema, **_kwargs):
        missing_alias_calls.append(tuple(response_schema['properties']))
        return '{}'

    partial = observe_foot_contact_timeline(
        video, pose_reference, evidence, missing_alias, cache_dir)
    assert missing_alias_calls == [('A',)]
    assert partial['retryable'] is True
    assert [row['sampleId'] for row in partial['samples']] == ['contact-pelvis-pose-0']
    partial_rows = validated_body_support_contact_timeline(
        partial, expected_video_sha256=digest)
    assert {row['sampleId'] for row in partial_rows} == {'contact-pelvis-pose-0'}
    assert 'contact-pelvis-pose-5' not in {row['sampleId'] for row in partial_rows}

    resumed_calls = []

    def resumed_caption(*, response_schema, **_kwargs):
        resumed_calls.append(tuple(response_schema['properties']))
        return json.dumps({'A': 'direct_contact'})

    resumed = observe_foot_contact_timeline(
        video, pose_reference, evidence, resumed_caption, cache_dir)
    assert resumed['status'] == 'observed'
    assert resumed['retryable'] is False
    assert resumed_calls == [('A',)]
    rows = validated_body_support_contact_timeline(resumed, expected_video_sha256=digest)
    assert rows is not None
    assert {row['sampleId'] for row in rows} == {
        'contact-pelvis-pose-0', 'contact-pelvis-pose-5'}
    assert {row['sampleId']: row['sourceFrameIndex'] for row in rows} == {
        'contact-pelvis-pose-0': 0, 'contact-pelvis-pose-5': 5}
