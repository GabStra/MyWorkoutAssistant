import numpy as np

from exercise_motion_pkg.body_support_observation import (
    CONTACT_TIMELINE_POLICY_VERSION,
    POLICY_VERSION,
)
from exercise_motion_pkg.contact_constraints import (
    observed_support_contact_mask,
    verified_body_support_anchor_samples,
)
from exercise_motion_pkg.controlled_motion import (
    source_support_authority,
    trajectory_fit_evidence,
)
from exercise_motion_pkg.sequence_stabilization import contact_mask


def hanging_support_fixture(*, contact_frames=(0, 11)):
    digest = 'selected-source-sha256'
    pose = {
        'sourceVideoSha256': digest,
        'coordinateSpace': 'normalized_image_xy',
        'frames': [],
    }
    joints = {
        'left_wrist': [.35, .2], 'right_wrist': [.65, .2],
        'pelvis': [.5, .55], 'nose': [.5, .1],
    }
    for index in range(12):
        pose['frames'].append({
            'sourceTimeSec': index / 30.,
            'joints': {name: point[:] for name, point in joints.items()},
        })
    observation = {
        'status': 'observed',
        'source': 'exact_source_visual_support_observation',
        'sourceVideoSha256': digest,
        'policyVersion': POLICY_VERSION,
        'observation': {
            'leftHand': 'stationary_support',
            'rightHand': 'stationary_support',
            'leftHandContactSurface': 'fixed_bar',
            'rightHandContactSurface': 'fixed_bar',
            'handsSameHorizontalSurface': True,
        },
        'contactTimeline': {
            'schemaVersion': 1,
            'policyVersion': CONTACT_TIMELINE_POLICY_VERSION,
            'source': 'exact_source_visual_contact_timeline',
            'sourceVideoSha256': digest,
            'sourceClock': 'video_frame_zero_seconds',
            'status': 'observed',
            'samples': [
                {
                    'sampleId': f'{side}-wrist-{index}',
                    'sourceTimeSec': index / 30.,
                    'sourceFrameIndex': index,
                    'sourceFps': 30.,
                    'sourcePoseFrameIndex': index,
                    'side': side,
                    'landmark': 'joint',
                    'jointName': f'{side}_wrist',
                    'contactState': 'direct_contact',
                    'surface': 'fixed_bar',
                    'visible': True,
                    'sourceTrackStationary': True,
                }
                for side in ('left', 'right') for index in contact_frames
            ],
        },
    }
    evidence = {
        'sourceVideoSha256': digest,
        'bodySupportObservation': observation,
        'bodySupport': {
            'required': True,
            'status': 'confirmed',
            'source': 'exact_source_contacts_and_stationary_pose_tracks',
            'sourceVideoSha256': digest,
            'stationaryJoints': ['left_hand', 'right_hand'],
        },
    }
    frames = [{'sourceTimeSec': index / 30.} for index in range(12)]
    names = ['pelvis', 'left_hand', 'right_hand', 'head']
    pinned = np.zeros((12, len(names)), dtype=bool)
    return evidence, pose, frames, names, pinned


def test_hanging_hand_support_anchors_fit_trajectory_without_faking_observed_contact_counts():
    evidence, pose, frames, names, pinned = hanging_support_fixture()
    body_samples = verified_body_support_anchor_samples(evidence, names, frames, pose)
    candidate = np.zeros((len(frames), len(names), 3))
    trajectory = trajectory_fit_evidence(
        candidate, candidate, names, 1., root_index=0, pinned=pinned,
        support_evidence=evidence,
        source_projection_constraint={
            'available': True,
            'cameraAuthority': 'retained_source_correction_camera',
            'sourceFootRaySideMapping': {'left': 'left', 'right': 'right'},
        },
        source_camera={'bilateralAssignment': 'identity'},
        source_contact_mask=pinned,
        body_support_anchor_samples=body_samples,
    )

    authority = source_support_authority(
        {'groundContactMode': 'none'}, evidence, trajectory)

    assert trajectory['eligible'] is True
    assert trajectory['observedSupportAnchorSampleCount'] == 0
    assert trajectory['observedBodySupportAnchorSampleCount'] == 4
    assert authority['status'] == 'verified'
    assert authority['observedSupportAnchorSampleCount'] == 0
    assert authority['observedBodySupportAnchorSampleCount'] == 4
    assert not observed_support_contact_mask(evidence, names, len(frames)).any()
    assert not contact_mask({}, names, len(frames), support_evidence=evidence).any()


def test_body_anchor_trajectory_mask_rejects_unbound_or_unobserved_support():
    evidence, pose, frames, names, _ = hanging_support_fixture()
    wrong_source = {**evidence, 'sourceVideoSha256': 'different-source-sha256'}
    unknown = {
        **evidence,
        'bodySupportObservation': {
            **evidence['bodySupportObservation'],
            'observation': {
                **evidence['bodySupportObservation']['observation'],
                'leftHand': 'unknown', 'rightHand': 'unknown',
            },
        },
    }

    assert verified_body_support_anchor_samples(wrong_source, names, frames, pose)['sampleCount'] == 0
    assert verified_body_support_anchor_samples(unknown, names, frames, pose)['sampleCount'] == 0


def test_body_anchor_samples_reject_moving_source_tracks():
    evidence, pose, frames, names, _ = hanging_support_fixture()
    for index, frame in enumerate(pose['frames']):
        for side in ('left', 'right'):
            frame['joints'][f'{side}_wrist'][0] += index * .02

    samples = verified_body_support_anchor_samples(evidence, names, frames, pose)

    assert samples['sampleCount'] == 0


def test_body_anchor_samples_respect_retained_fit_source_interval():
    evidence, pose, frames, names, _ = hanging_support_fixture(contact_frames=(4, 11))

    outside = verified_body_support_anchor_samples(evidence, names, frames[:4], pose)
    inside = verified_body_support_anchor_samples(evidence, names, frames[3:], pose)

    assert outside['sampleCount'] == 0
    assert inside['sampleCount'] == 4


def test_body_anchor_samples_require_two_distinct_source_contact_times():
    evidence, pose, frames, names, _ = hanging_support_fixture(contact_frames=(11,))

    samples = verified_body_support_anchor_samples(evidence, names, frames, pose)

    assert samples['sampleCount'] == 0


def test_materialized_wrist_is_not_counted_when_rig_has_a_hand_endpoint():
    evidence, pose, frames, names, _ = hanging_support_fixture()
    evidence['bodySupport']['stationaryJoints'] = ['left_wrist', 'right_wrist']

    samples = verified_body_support_anchor_samples(evidence, names, frames, pose)

    assert samples['sampleCount'] == 0


def test_body_anchor_samples_reject_malformed_source_time_origin():
    evidence, pose, frames, names, _ = hanging_support_fixture()
    pose['sourceTimeOriginSec'] = 'invalid'

    samples = verified_body_support_anchor_samples(evidence, names, frames, pose)

    assert samples['sampleCount'] == 0
