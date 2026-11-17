import copy

import numpy as np

from exercise_motion_pkg import foot_contact_observation as foot
from exercise_motion_pkg.pose_fidelity import _canonical_source_pose_sha256


def _source_pose():
    return {
        'sourceTimeOriginSec': 0.,
        'sourcePoseSampleBoundaryToleranceSeconds': .01,
        'imageWidth': 640,
        'imageHeight': 360,
        'frames': [{
            'sourceTimeSec': 0.,
            'joints': {
                'left_ankle': [.5, .5],
                'right_ankle': [.5, .5],
            },
        }],
    }


def _observations(video_sha):
    points = {
        'ankle': {'image': [.5, .5], 'world': [0., 0., 0.], 'confidence': .99},
        'heel': {'image': [.49, .5], 'world': [-.02, 0., 0.], 'confidence': .99},
        'toe': {'image': [.6, .5], 'world': [.2, 0., 0.], 'confidence': .99},
    }
    return {
        'available': True,
        'source': 'mediapipe_full_heel_forefoot',
        'sourceVideoSha256': video_sha,
        'imageWidth': 640,
        'imageHeight': 360,
        'fps': 30.,
        'frames': [{'timeSeconds': 0., 'joints': {
            f'{side}_{name}': copy.deepcopy(value)
            for side in ('left', 'right') for name, value in points.items()
        }}],
    }


def test_classifier_persists_recomputable_pose_binding_receipts():
    video_sha = 'a' * 64
    pose = _source_pose()
    patch = foot.classify_foot_contacts(
        _observations(video_sha), {'contacts': [], 'sourceVideoSha256': video_sha}, pose,
    )

    assert patch['policyVersion'] == foot.POLICY_VERSION
    assert foot.OBSERVATION_CACHE_VERSION == 3
    assert patch['sourcePosePayloadSha256'] == _canonical_source_pose_sha256(pose)
    assert patch['sourcePoseVideoSha256'] == video_sha
    for side in ('left', 'right'):
        ray, = patch['feet'][side]['rayObservations']
        assert ray['referenceFrameIndex'] == 0
        assert ray['referenceFrameSourceTimeSec'] == 0.
        assert ray['referenceAnkleImagePoint'] == [.5, .5]
        assert ray['sourceAnkleImagePoint'] == [.5, .5]
        assert ray['sourceToeImagePoint'] == [.6, .5]
    assert foot.foot_patch_pose_binding_failure(patch, pose) is None


def test_pose_binding_rejects_stale_pose_and_ray_receipts_but_not_native_contacts():
    video_sha = 'b' * 64
    pose = _source_pose()
    patch = foot.classify_foot_contacts(
        _observations(video_sha), {'contacts': [], 'sourceVideoSha256': video_sha}, pose,
    )

    changed_pose = copy.deepcopy(pose)
    changed_pose['frames'][0]['joints']['left_ankle'] = [.7, .5]
    assert foot.foot_patch_pose_binding_failure(patch, changed_pose) == (
        'foot_patch_source_pose_digest_mismatch')

    stale_ray = copy.deepcopy(patch)
    stale_ray['feet']['left']['rayObservations'][0]['sourceFrameIndex'] = 1
    assert foot.foot_patch_pose_binding_failure(stale_ray, pose) == (
        'foot_patch_ray_observation_clock_mismatch')

    native = {'available': True, 'source': 'native_visual_contact', 'policyVersion': -1}
    assert foot.foot_patch_pose_binding_failure(native, None) is None


def test_binding_validator_recomputes_ankle_disagreement_from_bound_pose():
    video_sha = 'c' * 64
    pose = _source_pose()
    patch = foot.classify_foot_contacts(
        _observations(video_sha), {'contacts': [], 'sourceVideoSha256': video_sha}, pose,
    )
    ray = patch['feet']['left']['rayObservations'][0]
    # Simulate a newly canonical source pose whose digest and stored reference
    # point were updated, but whose ankle no longer agrees with the cached ray.
    changed_pose = copy.deepcopy(pose)
    changed_pose['frames'][0]['joints']['left_ankle'] = [.61, .5]
    patch = copy.deepcopy(patch)
    patch['sourcePosePayloadSha256'] = _canonical_source_pose_sha256(changed_pose)
    ray = patch['feet']['left']['rayObservations'][0]
    ray['referenceAnkleImagePoint'] = [.61, .5]
    association = foot._source_pose_ankle_association(
        ray['sourceAnkleImagePoint'], ray['sourceToeImagePoint'], [.61, .5], [640., 360.],
    )
    ray['ankleAssociationDistanceNormalized'] = association['normalizedDistance']
    ray['ankleAssociationDistancePixels'] = association['pixelDistance']

    assert foot.foot_patch_pose_binding_failure(patch, changed_pose) == (
        'foot_patch_ray_source_ankle_disagreement')


def _source_pose_clock(sample_count=18):
    interval = 4.0 / 29.97002997002997
    return {
        'sourceTimeOriginSec': 0.,
        # Requested 8 fps on a 29.97 fps cut: the nominal half step is smaller
        # than the real half cell of every fourth delivered frame.
        'sourcePoseSampleBoundaryToleranceSeconds': 0.5 / 8.0,
        'frames': [
            {'sourceTimeSec': index * interval, 'joints': {}}
            for index in range(sample_count)
        ],
    }


def test_source_pose_clock_uses_actual_cells_without_bridging_gaps_or_release():
    pose = _source_pose_clock()
    interval = 4.0 / 29.97002997002997
    tolerance, source = foot.source_pose_sample_boundary_tolerance_details(pose)
    # The delivered cadence, not the requested 8 fps, owns the time-match cell.
    assert source == 'actual_sample_interval'
    assert abs(tolerance - interval * .5) <= 1e-9

    # A frame exactly at the midpoint of a delivered cell still resolves to the
    # nearest observed sample instead of becoming a periodic unknown.
    midpoint = 8 * interval + interval * .5
    match = foot._source_pose_frame_at_time(pose, midpoint)
    assert match is not None and match['frameIndex'] == 8

    # A genuine uncovered gap is still refused.
    assert foot._source_pose_frame_at_time(pose, 17 * interval + 4 * interval) is None

    # An explicit contract limit stays authoritative.
    explicit = copy.deepcopy(pose)
    explicit['sourcePoseSampleBoundaryToleranceSource'] = 'explicit_contract'
    explicit['sourcePoseSampleBoundaryToleranceSeconds'] = .02
    assert foot.source_pose_sample_boundary_tolerance_seconds(explicit) == .02
    assert foot._source_pose_frame_at_time(explicit, midpoint) is None

    # Materializing a stance never bridges an observed gap or a release, and a
    # unified stance may only be corroborated by an independently stationary
    # ankle support covering the whole run.
    count = 12
    states = ['toe_only'] * 4 + ['unknown'] * 4 + ['airborne'] * 4
    # Accumulated image drift that alone would exceed the local spread limit.
    toe_points = np.stack([np.arange(count) * .004, np.zeros(count)], axis=1)
    foot_sizes = np.full(count, .03)
    stationary_ankle = {
        'jointName': 'right_ankle', 'supportKind': 'foot', 'contactMotion': 'stationary',
        'startFrame': 0, 'endFrame': 11, 'startRatio': 0., 'endRatio': 1.,
    }
    contacts = foot._materialize_foot_patch_contacts(
        side='right', states=states, valid=np.ones(count, dtype=bool),
        toe_valid=np.ones(count, dtype=bool), heel_points=np.zeros((count, 2)),
        toe_points=toe_points, foot_sizes=foot_sizes, image_pitch=np.zeros(count),
        world_pitch=np.zeros(count), image_only_toe=np.zeros(count, dtype=bool),
        unresolved_heel_recontact=np.zeros(count, dtype=bool),
        references=(0., 0.), tolerances=(np.deg2rad(8), np.deg2rad(8)),
        uncalibrated_toe=True, uncalibrated_surface_kind='ground',
        support_contacts=[stationary_ankle],
    )
    assert states[4:8] == ['unknown'] * 4
    assert states[8:] == ['airborne'] * 4
    assert [(contact['contactState'], contact['startRatio'], contact['endRatio'])
            for contact in contacts] == [('toe_only', 0., 3 / 11)]
