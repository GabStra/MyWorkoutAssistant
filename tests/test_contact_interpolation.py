import numpy as np
import pytest

from exercise_motion_pkg.contact_interpolation import (
    build_contact_foot_tracks,
    sample_contact_foot_tracks,
)


def _two_bone_frame(toe, pitch, *, hip, thigh, shin, pole):
    toe = np.asarray(toe, dtype=float)
    direction = np.array([0., np.sin(pitch), np.cos(pitch)])
    ankle = toe - .2 * direction
    reach = ankle - hip
    distance = np.linalg.norm(reach)
    axis = reach / distance
    along = (thigh**2 - shin**2 + distance**2) / (2. * distance)
    bend = pole - axis * np.dot(pole, axis)
    knee = hip + axis * along + bend / np.linalg.norm(bend) * np.sqrt(thigh**2 - along**2)
    return knee, ankle, toe


def test_contact_foot_tracks_hold_toe_preserve_pitch_and_leg_chain_with_c1_transitions():
    names = ['pelvis', 'left_hip', 'left_knee', 'left_ankle', 'left_foot']
    hip = np.array([0., 1.2, 0.])
    pole = np.array([1., 0., 0.])
    first = _two_bone_frame([0., 0., .2], 0., hip=hip, thigh=.65, shin=.65, pole=pole)
    toe1 = np.array([0., 0., .2])
    frame1 = _two_bone_frame(toe1, 0., hip=hip, thigh=.65, shin=.65, pole=pole)
    frame2 = _two_bone_frame(toe1, .25, hip=hip, thigh=.65, shin=.65, pole=pole)
    frame3 = _two_bone_frame([.1, 0., .2], .25, hip=hip, thigh=.65, shin=.65, pole=pole)
    keypoints = np.asarray([
        [np.zeros(3), hip, *first],
        [np.zeros(3), hip, *frame1],
        [np.zeros(3), hip, *frame2],
        [np.zeros(3), hip, *frame3],
    ], dtype=float)
    # Tuple expansion above is (pelvis, hip, knee, ankle, toe), matching `names`.
    pinned = np.zeros((len(keypoints), len(names)), dtype=bool)
    pinned[1:3, names.index('left_foot')] = True
    builder_rig = type('RigNames', (), {'names': names})()
    tracks = build_contact_foot_tracks(builder_rig, keypoints, pinned)
    ankle_only = np.zeros_like(pinned)
    ankle_only[1, names.index('left_ankle')] = True
    assert build_contact_foot_tracks(builder_rig, keypoints, ankle_only)['left']['active'][1] is False

    offsets = np.zeros((len(names), 3), dtype=float)
    offsets[names.index('left_knee')] = [0., -.65, 0.]
    offsets[names.index('left_ankle')] = [0., -.65, 0.]
    offsets[names.index('left_foot')] = [0., 0., .2]
    rig = {
        'jointNames': names,
        'coordinates': np.zeros((len(keypoints), 3)),
        'offsets': offsets,
        'interpolation': 'limited_quaternion_hermite_v2',
        'contactFootTracks': tracks,
    }

    def raw_samples(cursors):
        cursors = np.asarray(cursors, dtype=float)
        lower = np.floor(cursors).astype(int)
        upper = np.minimum(lower + 1, len(keypoints) - 1)
        alpha = cursors - lower
        raw = keypoints[lower] * (1. - alpha[:, None, None]) + keypoints[upper] * alpha[:, None, None]
        # Model the renderer's inter-key toe drift while retaining exact key poses.
        raw[:, names.index('left_foot'), 0] += .02 * np.sin(np.pi * cursors)
        return raw

    queries = np.array([.5, 1., 1.5, 2., 2.5])
    raw = raw_samples(queries)
    repaired = sample_contact_foot_tracks(rig, queries, raw)
    toe_index, ankle_index, knee_index, hip_index = [
        names.index(f'left_{part}') for part in ('foot', 'ankle', 'knee', 'hip')]

    # The source-confirmed anchor removes mid-interval renderer drift.
    assert raw[0, toe_index, 0] > .015
    assert abs(repaired[0, toe_index, 0]) < abs(raw[0, toe_index, 0])
    assert repaired[2, toe_index, 0] == pytest.approx(0., abs=1e-10)
    # Exact keyframes remain untouched, including the source's heel/pitch motion.
    np.testing.assert_array_equal(repaired[[1, 3]], raw[[1, 3]])
    foot_direction = repaired[2, toe_index] - repaired[2, ankle_index]
    assert foot_direction[1] > 0.
    assert np.linalg.norm(foot_direction) == pytest.approx(.2, abs=1e-10)
    assert not np.allclose(repaired[2, knee_index], raw[2, knee_index])
    assert np.linalg.norm(repaired[2, knee_index] - repaired[2, hip_index]) == pytest.approx(.65, abs=1e-8)
    assert np.linalg.norm(repaired[2, ankle_index] - repaired[2, knee_index]) == pytest.approx(.65, abs=1e-8)
    old_axis = raw[2, ankle_index] - raw[2, hip_index]
    old_pole = raw[2, knee_index] - raw[2, hip_index]
    old_pole -= old_axis * np.dot(old_pole, old_axis) / np.dot(old_axis, old_axis)
    new_axis = repaired[2, ankle_index] - repaired[2, hip_index]
    new_pole = repaired[2, knee_index] - repaired[2, hip_index]
    new_pole -= new_axis * np.dot(new_pole, new_axis) / np.dot(new_axis, new_axis)
    assert np.dot(old_pole, new_pole) > 0.

    # Activation and release blend with zero endpoint slope, preserving C1 toe motion.
    epsilon = 1e-4
    for boundary in (1., 2.):
        samples = sample_contact_foot_tracks(
            rig, [boundary - epsilon, boundary, boundary + epsilon],
            raw_samples([boundary - epsilon, boundary, boundary + epsilon]))
        for joint in (toe_index, ankle_index, knee_index):
            incoming = (samples[1, joint] - samples[0, joint]) / epsilon
            outgoing = (samples[2, joint] - samples[1, joint]) / epsilon
            np.testing.assert_allclose(incoming, outgoing, atol=1e-2, rtol=1e-2)

    legacy_points = raw_samples([.5])
    np.testing.assert_array_equal(
        sample_contact_foot_tracks({**rig, 'contactFootTracks': None}, [.5], legacy_points),
        legacy_points)


def test_contact_track_key_preservation_can_be_disabled_for_solver_samples():
    names = ['pelvis', 'left_hip', 'left_knee', 'left_ankle', 'left_foot']
    hip = np.array([0., 1.2, 0.])
    point = _two_bone_frame(
        [0., 0., .2], 0., hip=hip, thigh=.65, shin=.65, pole=np.array([1., 0., 0.]))
    keypoints = np.asarray([[np.zeros(3), hip, *point] for _ in range(3)])
    pinned = np.zeros((3, len(names)), dtype=bool)
    pinned[:, names.index('left_foot')] = True
    tracks = build_contact_foot_tracks(type('RigNames', (), {'names': names})(), keypoints, pinned)
    tracks['left']['directions'][1] = [0., np.sin(.35), np.cos(.35)]
    rig = {
        'jointNames': names,
        'coordinates': np.zeros((3, 3)),
        'offsets': np.array([[0., 0., 0.], [0., 0., 0.], [0., -.65, 0.],
                             [0., -.65, 0.], [0., 0., .2]]),
        'contactFootTracks': tracks,
    }
    exact = keypoints[1:2].copy()
    exact[0, names.index('pelvis')] += [0.002, 0., 0.]
    exact[0, names.index('left_hip')] += [0.002, 0., 0.]

    preserved = sample_contact_foot_tracks(rig, [1.], exact)
    fitted = sample_contact_foot_tracks(rig, [1.], exact, preserve_keys=False)

    np.testing.assert_array_equal(preserved, exact)
    fitted_direction = fitted[0, names.index('left_foot')] - fitted[0, names.index('left_ankle')]
    assert np.arctan2(fitted_direction[1], fitted_direction[2]) == pytest.approx(.35, abs=1e-8)
    np.testing.assert_array_equal(fitted[0, names.index('left_foot')], exact[0, names.index('left_foot')])


def test_wrapped_yaw_uses_continuous_branch_across_last_to_first_key():
    names = ['pelvis', 'left_hip', 'left_knee', 'left_ankle', 'left_foot']
    hip = np.array([0., 1.2, 0.])
    knee, ankle, toe = _two_bone_frame(
        [0., 0., .2], 0., hip=hip, thigh=.65, shin=.65, pole=np.array([1., 0., 0.]))
    point = np.asarray([np.zeros(3), hip, knee, ankle, toe])
    yaw = np.deg2rad([0., 90., 180., -90.])
    directions = np.column_stack([np.sin(yaw), np.zeros(4), np.cos(yaw)])
    offsets = np.zeros((len(names), 3), dtype=float)
    offsets[names.index('left_knee')] = [0., -.65, 0.]
    offsets[names.index('left_ankle')] = [0., -.65, 0.]
    offsets[names.index('left_foot')] = [0., 0., .2]
    rig = {
        'jointNames': names,
        'coordinates': np.zeros((4, 3)),
        'offsets': offsets,
        'interpolation': 'limited_quaternion_hermite_v2',
        'contactFootTracks': {
            'version': 1,
            'left': {'active': [True] * 4, 'toes': [toe.tolist()] * 4,
                     'directions': directions.tolist()},
        },
    }
    sampled = sample_contact_foot_tracks(rig, [3.75], point[None], wrap=True)[0]
    actual_direction = sampled[names.index('left_foot')] - sampled[names.index('left_ankle')]
    actual_yaw = np.arctan2(actual_direction[0], actual_direction[2])
    assert actual_yaw == pytest.approx(np.deg2rad(-22.5), abs=1e-6)
