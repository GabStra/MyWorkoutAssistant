"""Shared exact-source fixture for observed non-foot support provenance tests."""

import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

from exercise_motion_pkg.bake_and_rank import load_verified_source_pose_reference
from exercise_motion_pkg.body_support_observation import (
    CONTACT_TIMELINE_POLICY_VERSION,
    POLICY_VERSION,
)

FPS = 10.0


def _pose_frames(frame_count, sides):
    frames = []
    for frame_index in range(frame_count):
        joints = {'nose': [.5, .2]}
        confidences = {'nose': .99}
        for offset, side in enumerate(sides):
            x = .4 + .1 * offset
            joints[f'{side}_ankle'] = [x, .8]
            joints[f'{side}_heel'] = [x - .01, .81]
            joints[f'{side}_toe'] = [x + .02, .82]
            joints[f'{side}_knee'] = [x + .05, .4]
            for joint in ('ankle', 'heel', 'toe', 'knee'):
                confidences[f'{side}_{joint}'] = .99
        frames.append({
            'sourceTimeSec': frame_index / FPS,
            'joints': joints,
            'jointConfidence': confidences,
        })
    return frames


def _contact_rows(sides, sample_frames, surface):
    return [{
        'sampleId': f'{side}-ankle-{frame_index}',
        'side': side,
        'landmark': 'joint',
        'jointName': f'{side}_ankle',
        'contactState': 'direct_contact',
        'surface': surface,
        'visible': True,
        'sourceTrackStationary': True,
        'sourceTimeSec': frame_index / FPS,
        'sourceFrameIndex': frame_index,
        'sourcePoseFrameIndex': frame_index,
        'sourceFps': FPS,
    } for side in sides for frame_index in sample_frames]


def build_nonfoot_support_fixture(
    tmp_path, *, frame_count=12, sample_frames=(0, 6), sides=('left',),
    surface='fixed_bar', observation_overrides=None, joint_names=None,
    ground_contact_mode='unknown', joint_positions=None,
):
    """Write a real video plus canonical pose reference and matching evidence."""
    workspace = tmp_path / 'workspace'
    video = workspace / 'input' / 'selected_segment.mp4'
    video.parent.mkdir(parents=True)
    writer = cv2.VideoWriter(
        str(video), cv2.VideoWriter_fourcc(*'mp4v'), FPS, (64, 48))
    assert writer.isOpened()
    for frame_index in range(frame_count):
        writer.write(np.full((48, 64, 3), frame_index, dtype=np.uint8))
    writer.release()
    digest = hashlib.sha256(video.read_bytes()).hexdigest()

    pose = {
        'coordinateSpace': 'normalized_image_xy',
        'sourceTimeOriginSec': 0.,
        'frames': _pose_frames(frame_count, sides),
    }
    for joint, position in (joint_positions or {}).items():
        for frame_index, frame in enumerate(pose['frames']):
            frame['joints'][joint] = position(frame_index)
    reference_path = workspace / 'segment_detection' / 'exact_source_pose_reference.json'
    reference_path.parent.mkdir(parents=True)
    reference_path.write_text(
        json.dumps({'sourceVideoSha256': digest, 'pose': pose}), encoding='utf-8')

    observation = {}
    for side in sides:
        observation[f'{side}Ankle'] = 'stationary_support'
        observation[f'{side}AnkleContactSurface'] = surface
    observation.update(observation_overrides or {})
    rows = _contact_rows(sides, sample_frames, surface)

    feet = {side: {'states': ['unknown'] * frame_count}
            for side in ('left', 'right')}

    observed = {
        'status': 'observed',
        'source': 'exact_source_visual_support_observation',
        'sourceVideoSha256': digest,
        'sourceClock': 'video_frame_zero_seconds',
        'policyVersion': POLICY_VERSION,
        'observation': observation,
        'contactTimeline': {
            'schemaVersion': 1,
            'policyVersion': CONTACT_TIMELINE_POLICY_VERSION,
            'source': 'exact_source_visual_contact_timeline',
            'sourceVideoSha256': digest,
            'sourceClock': 'video_frame_zero_seconds',
            'status': 'observed',
            'samples': rows,
        },
    }
    evidence = {
        'sourceVideoSha256': digest,
        'bodySupportObservation': observed,
        'supportContacts': [],
        'footPatchEvidence': {
            'available': True,
            'sourceVideoSha256': digest,
            'sourceFrameCount': frame_count,
            'sourceFps': FPS,
            'sourceTimeBasis': 'absolute_source_video',
            'sourceTimesSec': [index / FPS for index in range(frame_count)],
            'feet': feet,
        },
    }
    payload = {
        'jointNames': list(joint_names or [f'{side}_ankle' for side in sides]),
        'frames': [{'sourceTimeSec': index / FPS} for index in range(frame_count)],
        'sourceFootSupportEvidence': evidence,
        'groundContactMode': ground_contact_mode,
    }
    reference = load_verified_source_pose_reference(reference_path, video)
    assert reference and reference['sourceVideoSha256'] == digest
    return video, reference_path, reference, payload
