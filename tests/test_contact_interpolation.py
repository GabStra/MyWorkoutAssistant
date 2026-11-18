import numpy as np
import pytest

from exercise_motion_pkg.contact_interpolation import (
    ContactFootIKUnreachable,
    build_contact_foot_tracks,
    sample_contact_foot_tracks,
)


def test_nested_same_anchor_stance_episodes_resolve_to_exact_ownership():
    import json
    from pathlib import Path
    from exercise_motion_pkg.contact_interpolation import build_native_foot_contact_tracks

    fixture = json.loads((Path(__file__).parent.parent / '.scratch'
                          / 'goal-contact-continuation' / 'native-foot-contact-owner-v270'
                          / 'native_material_contact_tracks_v2.json').read_text())
    names = ['left_hip', 'right_hip', 'left_ankle', 'left_foot']
    count = 6
    points = np.asarray([
        [[-.1, 1., 0.], [.1, 1., 0.], [0., .1, 0.],
         [0., .1, 0.13402119093912526]],
    ] * count)
    pinned = np.zeros((count, len(names)), dtype=bool)
    pinned[:, names.index('left_foot')] = True
    side_axes = {'left': np.asarray([[1., 0., 0.]] * count)}

    def stance(state, bounds):
        return {
            'jointName': 'left_foot', 'contactState': state,
            'contactMotion': 'stationary', 'verticalOnly': False,
            'surfaceKind': 'ground', 'supportKind': 'observed_source_stance_interval',
            'anchorGroupId': 'left:reviewed-stance:toe',
            '_fitFrameBounds': bounds, '_fitFrameCount': count,
        }

    evidence = {'contacts': [stance('toe_only', [0, 5]),
                             stance('full_sole', [2, 3])]}
    tracks, owned = build_native_foot_contact_tracks(
        {'jointNames': names}, points, pinned, side_axes, evidence,
        fixture['nativeFootGeometry'], floor=0.)
    foot = names.index('left_foot')
    np.testing.assert_array_equal(owned[:, foot], np.ones(count, dtype=bool))
    roles = {index: episode['regionRole']
             for episode in tracks['left']['episodes']
             for index in range(episode['startFrame'], episode['endFrame'] + 1)}
    assert roles == {0: 'forefoot', 1: 'forefoot', 2: 'full_sole',
                     3: 'full_sole', 4: 'forefoot', 5: 'forefoot'}

    conflicting = {'contacts': [
        stance('toe_only', [0, 5]),
        {**stance('full_sole', [2, 3]), 'anchorGroupId': 'left:other-stance'},
    ]}
    with pytest.raises(ValueError, match='episodes overlap'):
        build_native_foot_contact_tracks(
            {'jointNames': names}, points, pinned, side_axes, conflicting,
            fixture['nativeFootGeometry'], floor=0.)


def test_native_knee_ik_stays_continuous_through_near_zero_target_change():
    from exercise_motion_pkg.contact_interpolation import _solve_knee

    hip = np.array([[0., 0., 0.]])
    knee = np.array([[.5, np.sqrt(.75), 0.]])
    ankle = np.array([[1., 0., 0.]])
    deltas = np.array([-0.5e-9, 0., 0.5e-9, 1e-9, 1.5e-9, 2e-9])
    solved = np.asarray([
        _solve_knee(hip, knee, ankle, ankle + [[0., delta, 0.]], 1., 1., 'right')[0]
        for delta in deltas
    ])

    # Crossing the former 1e-9 no-op threshold must not jump back to the raw
    # knee pose when its source bend plane is well-defined.
    assert np.max(np.linalg.norm(np.diff(solved, axis=0), axis=1)) < 1e-9


def test_native_knee_ik_keeps_degenerate_pole_noop_and_fail_closed_move():
    from exercise_motion_pkg.contact_interpolation import _solve_knee

    hip = np.array([[0., 0., 0.]])
    knee = np.array([[.5, 0., 0.]])
    ankle = np.array([[1., 0., 0.]])
    np.testing.assert_array_equal(
        _solve_knee(hip, knee, ankle, ankle, .5, .5, 'right'), knee)
    with pytest.raises(ValueError, match='undefined source knee pole'):
        _solve_knee(
            hip, knee, ankle, ankle + [[0., 2e-9, 0.]], .5, .5, 'right')


def test_source_contact_tracks_do_not_bridge_distinct_or_unknown_anchors():
    from exercise_motion_pkg.contact_interpolation import _sample_leg_track, _validated_side_track

    track = {'active': [True] * 4, 'toes': [[0., 0., 0.]] * 4,
             'directions': [[0., 0., 1.]] * 4,
             'anchorIds': ['first', 'first', 'second', None]}
    _, _, weights = _sample_leg_track(
        _validated_side_track(track, 4, 'left'), np.array([0, 1, 2, 3]),
        np.array([1, 2, 3, 3]), np.full(4, .5), wrap=False, smooth_limiter=True)
    np.testing.assert_array_equal(weights, [1., 0., 0., 0.])
    track['anchorIds'] = ['first']
    with pytest.raises(ValueError, match='anchor identities'):
        _validated_side_track(track, 4, 'left')


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


def test_interpolated_contact_projects_sub_tolerance_reach_overflow_only():
    """Between-key contact targets may overshoot reach by less than the dense gate.

    Stored keys stay exact. The rigid foot rotates about the unchanged contact
    toe so the ankle reaches the sphere without moving the contact or shortening
    a bone; the existing playback/material gate then measures only the original
    interpolation residual. A larger overshoot still raises the typed error.
    """
    names = ['pelvis', 'left_hip', 'left_knee', 'left_ankle', 'left_foot']
    hip = np.array([0., .798, 0.])
    knee, ankle, toe = _two_bone_frame(
        [0., 0., .2], 0., hip=hip, thigh=.4, shin=.4, pole=np.array([1., 0., 0.]))
    keypoints = np.asarray(
        [[np.zeros(3), hip, knee, ankle, toe]] * 3, dtype=float)
    pinned = np.zeros((len(keypoints), len(names)), dtype=bool)
    pinned[:, names.index('left_foot')] = True
    tracks = build_contact_foot_tracks(
        type('RigNames', (), {'names': names})(), keypoints, pinned)
    rig = {
        'jointNames': names,
        'coordinates': np.zeros((len(keypoints), 3)),
        'offsets': np.array([[0., 0., 0.], [0., 0., 0.], [0., -.4, 0.],
                             [0., -.4, 0.], [0., 0., .2]]),
        'contactFootTracks': tracks,
    }
    hip_i, knee_i = names.index('left_hip'), names.index('left_knee')
    ankle_i, toe_i = names.index('left_ankle'), names.index('left_foot')

    target_hip_overflow = keypoints[:1].copy()
    target_hip_overflow[0, hip_i] += [0., .004, 0.]
    repaired = sample_contact_foot_tracks(rig, [.5], target_hip_overflow)
    assert np.linalg.norm(repaired[0, ankle_i] - target_hip_overflow[0, hip_i]) \
        == pytest.approx(.8, abs=1e-9)
    assert np.linalg.norm(repaired[0, toe_i] - repaired[0, ankle_i]) \
        == pytest.approx(.2, abs=1e-9)
    assert np.linalg.norm(repaired[0, toe_i] - keypoints[0, toe_i]) \
        == pytest.approx(0., abs=1e-9)
    assert np.linalg.norm(repaired[0, knee_i] - repaired[0, hip_i]) \
        == pytest.approx(.4, abs=1e-9)
    assert np.linalg.norm(repaired[0, ankle_i] - repaired[0, knee_i]) \
        == pytest.approx(.4, abs=1e-9)

    exact_key = sample_contact_foot_tracks(rig, [1.], keypoints[1:2])
    np.testing.assert_array_equal(exact_key, keypoints[1:2])

    excessive = keypoints[:1].copy()
    excessive[0, hip_i] += [0., .008, 0.]
    with pytest.raises(ContactFootIKUnreachable):
        sample_contact_foot_tracks(rig, [.5], excessive)


def test_pose_change_refreshes_track_geometry_without_changing_source_contact():
    from copy import deepcopy
    from exercise_motion_pkg.contact_interpolation import refresh_contact_foot_tracks

    rig = {'jointNames': ['left_hip', 'left_knee', 'left_ankle', 'left_foot']}
    points = np.array([[[0., 1., 0.], [0., .5, .2], [0., 0., 0.], [0., 0., .2]]] * 3)
    pins = np.zeros((3, 4), dtype=bool)
    pins[:, 3] = True
    identities = np.full((3, 4), None, dtype=object)
    identities[:, 3] = 'observed-anchor'
    tracks = build_contact_foot_tracks(rig, points, pins, anchor_ids=identities)
    original = deepcopy(tracks)
    points[:, 2, 1] = .01
    refreshed = refresh_contact_foot_tracks(rig, points, tracks)
    assert tracks == original
    assert refreshed['left']['active'] == original['left']['active']
    assert refreshed['left']['anchorIds'] == original['left']['anchorIds']
    np.testing.assert_allclose(refreshed['left']['toes'], points[:, 3])
    expected = points[:, 3] - points[:, 2]
    expected /= np.linalg.norm(expected, axis=1)[:, None]
    np.testing.assert_allclose(refreshed['left']['directions'], expected)


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


def test_native_legacy_projection_reaches_preserved_key_as_weight_vanishes():
    """Zero-weight legacy projection must be the stored key pose, not a rotated foot.

    The native material track may intentionally point the foot away from the raw
    bone direction. The off-key correction still has to meet the exact stored key
    continuously when its weight envelope reaches zero.
    """
    import json
    from pathlib import Path
    from exercise_motion_pkg.foot_geometry import shoe_vertices
    from exercise_motion_pkg.material_region_support import shoe_triangles
    from exercise_motion_pkg.native_foot_geometry import native_foot_bone_frame
    from exercise_motion_pkg.rig_interpolation import frame_boundary_velocity_jump

    fixture = json.loads((Path(__file__).parent / 'fixtures'
                          / 'native_foot_geometry_v1.json').read_text())
    geometry = fixture['reference']
    names = ['left_hip', 'left_knee', 'left_ankle', 'left_foot']
    hip = np.array([0., 1., 0.])
    key_pose = np.asarray(_two_bone_frame(
        [0., 0., .2], .1, hip=hip, thigh=.65, shin=.65, pole=[1., 0., 0.]))
    points = np.concatenate((hip[None, :], key_pose))[None, :, :]
    ankle, foot = points[0, 2], points[0, 3]
    foot_scale = .2
    raw_direction = foot - ankle
    raw_direction /= np.linalg.norm(raw_direction)
    # Intended material contact orientation differs from the raw foot bone,
    # reproducing the captured repair candidate's divergent contact track.
    yaw = np.deg2rad(10.)
    track_direction = np.array([
        np.cos(yaw) * raw_direction[0] + np.sin(yaw) * raw_direction[2],
        raw_direction[1],
        -np.sin(yaw) * raw_direction[0] + np.cos(yaw) * raw_direction[2],
    ])
    track_direction /= np.linalg.norm(track_direction)
    side_axis = np.array([1., 0., 0.])
    side_axis -= track_direction * np.dot(side_axis, track_direction)
    side_axis /= np.linalg.norm(side_axis)

    triangles = shoe_triangles()
    triangle_index = 11
    barycentric = np.asarray([.2, .3, .5])
    reference_length = geometry['sides']['left']['ankleToFootJointLengthMeters']
    mesh = shoe_vertices(ankle, ankle + track_direction * foot_scale, side_axis,
                         None, foot_scale, native_geometry=geometry['sides']['left'])
    target = barycentric @ mesh[triangles[triangle_index]]
    forward, lateral, up, length = native_foot_bone_frame(
        ankle, ankle + track_direction * foot_scale, side_axis)
    delta = target - ankle
    local = np.array([delta @ forward, delta @ lateral, delta @ up])
    local *= reference_length / float(length[0])
    episode = {
        'startFrame': 0, 'endFrame': 2, 'anchorId': 'left-key-anchor',
        'regionRole': 'forefoot', 'mode': 'stationary',
        'primitiveId': 'wearShoe:left_ankle->left_foot',
        'triangleIndex': triangle_index, 'barycentric': barycentric.tolist(),
        'materialOffsetLocalMeters': local.tolist(),
        'referenceLengthMeters': reference_length,
        'targetWorld': target.tolist(), 'surfaceNormal': [0., 1., 0.],
        'planeOffsetMeters': float(target[1]),
    }
    tracks = {'version': 2, 'left': {
        'active': [True] * 3,
        'directions': [track_direction.tolist()] * 3,
        'sideAxes': [side_axis.tolist()] * 3,
        'anchorIds': ['left-key-anchor'] * 3,
        'episodes': [episode],
    }}
    offsets = np.zeros((len(names), 3))
    offsets[1], offsets[2] = key_pose[0] - hip, key_pose[1] - key_pose[0]
    offsets[names.index('left_foot')] = foot - ankle
    rig = {'jointNames': names, 'coordinates': np.zeros((3, 1)).tolist(),
           'offsets': offsets.tolist(), 'interpolation': 'limited_quaternion_hermite_v1',
           'contactFootTracks': tracks}

    def sample(cursors):
        cursors = np.asarray(cursors, dtype=float).reshape(-1)
        raw = np.repeat(points, len(cursors), axis=0)
        return sample_contact_foot_tracks(
            rig, cursors, raw, native_foot_geometry=geometry, foot_scale=foot_scale)

    # The exact keys remain the stored poses.
    np.testing.assert_array_equal(sample([0., 1., 2.]), np.repeat(points, 3, axis=0))
    # Off-key samples converge to those keys as the projection weight vanishes.
    assert frame_boundary_velocity_jump(sample, [1.], 30.) < 1e-3
    near = sample([1. - 1e-4, 1. + 1e-4])
    np.testing.assert_allclose(near, np.repeat(points, 2, axis=0), atol=1e-6)
    # Full-weight material contact still uses the intended track orientation
    # and preserves the fixed bone lengths.
    full = sample([.5])[0]
    direction = full[3] - full[2]
    np.testing.assert_allclose(direction / np.linalg.norm(direction),
                               track_direction, atol=1e-9)
    assert np.linalg.norm(direction) == pytest.approx(foot_scale, abs=1e-10)
    material = full[2] + (forward * local[0] + lateral * local[1] + up * local[2]) * (
        foot_scale / reference_length)
    np.testing.assert_allclose(material, target, atol=1e-9)
    assert np.arccos(np.clip(np.dot(track_direction, raw_direction), -1., 1.)) > .1


@pytest.mark.parametrize('mode,role', [('stationary', 'full_sole'),
                                       ('verticalOnly', 'forefoot')])
def test_native_material_track_preserves_pose_basis_and_constraints(mode, role):
    from copy import deepcopy
    import json
    from pathlib import Path
    from exercise_motion_pkg.contact_interpolation import _sample_track_directions
    from exercise_motion_pkg.foot_geometry import shoe_vertices
    from exercise_motion_pkg.material_region_support import shoe_triangles
    from exercise_motion_pkg.native_foot_geometry import native_foot_bone_frame
    from exercise_motion_pkg.rig_interpolation import hermite_samples

    fixture = json.loads((Path(__file__).parent / 'fixtures'
                          / 'native_foot_geometry_v1.json').read_text())
    native_geometry = fixture['reference']

    names = ['left_hip', 'left_knee', 'left_ankle', 'left_foot']
    hip = np.array([0., 1.0, 0.])
    pitches = np.asarray([.1, .55, 1.45])
    frames = [_two_bone_frame([0., 0., .2], pitch, hip=hip,
                              thigh=.65, shin=.65, pole=[1., 0., 0.])
              for pitch in pitches]
    points = np.asarray([[hip, *frame] for frame in frames], dtype=float)
    foot_scale = .20
    directions = points[:, 3] - points[:, 2]
    directions /= np.linalg.norm(directions, axis=1)[:, None]
    twists = np.radians([0., 20., 35.])
    side_axes = np.column_stack((
        np.cos(twists), -np.sin(twists) * np.cos(pitches),
        np.sin(twists) * np.sin(pitches)))
    np.testing.assert_allclose(np.sum(directions * side_axes, axis=1), 0., atol=1e-12)
    triangle_index = 11
    barycentric = np.asarray([.2, .3, .5])
    triangle = shoe_triangles()[triangle_index]
    mesh = shoe_vertices(points[0, 2], points[0, 3], side_axes[0], None,
                         foot_scale, native_geometry=native_geometry['sides']['left'])
    target_point = barycentric @ mesh[triangle]
    forward, lateral, up, length = native_foot_bone_frame(
        points[0, 2], points[0, 3], side_axes[0])
    delta = target_point - points[0, 2]
    reference_length = native_geometry['sides']['left']['ankleToFootJointLengthMeters']
    local = np.asarray([np.dot(delta, forward), np.dot(delta, lateral), np.dot(delta, up)])
    local *= reference_length / float(length[0])
    normal = np.asarray([0., 1., 0.])
    # Keep the stored key valid but slightly inside the existing contact
    # tolerance, so between-key projection has a measurable endpoint delta.
    target_point = target_point + normal * .0005
    plane_offset = float(target_point @ normal)
    episode = {
        'startFrame': 0, 'endFrame': 2, 'anchorId': 'same-native-anchor',
        'regionRole': role, 'mode': mode,
        'primitiveId': 'wearShoe:left_ankle->left_foot', 'triangleIndex': triangle_index,
        'barycentric': barycentric.tolist(),
        'materialOffsetLocalMeters': local.tolist(), 'referenceLengthMeters': reference_length,
        'surfaceNormal': normal.tolist(), 'planeOffsetMeters': plane_offset,
    }
    if mode == 'stationary':
        episode['targetWorld'] = target_point.tolist()
    tracks = {'version': 2, 'left': {
        'active': [True] * 3, 'directions': directions.tolist(),
        'sideAxes': side_axes.tolist(), 'anchorIds': ['same-native-anchor'] * 3,
        'episodes': [episode],
    }}
    rig = {'jointNames': names, 'coordinates': np.zeros((3, 1)).tolist(),
           'offsets': [[0., 0., 0.], [.65, 0., 0.], [.65, 0., 0.], [.2, 0., 0.]],
           'interpolation': 'limited_quaternion_hermite_v1',
           'contactFootTracks': tracks}
    cursor = 1.5
    sampled = sample_contact_foot_tracks(
        rig, [cursor], points[1:2], native_foot_geometry=native_geometry,
        foot_scale=foot_scale)[0]
    expected_direction = _sample_track_directions(
        directions, np.asarray([1]), np.asarray([2]), np.asarray([.5]),
        wrap=False, smooth_limiter=False)[0]
    np.testing.assert_allclose(
        (sampled[3] - sampled[2]) / np.linalg.norm(sampled[3] - sampled[2]),
        expected_direction, atol=1e-9)
    lateral_sample = hermite_samples(side_axes, np.asarray([1]), np.asarray([2]),
                                     np.asarray([.5]), wrap=False,
                                     smooth_limiter=False)[0]
    lateral_sample -= expected_direction * np.dot(lateral_sample, expected_direction)
    lateral_sample /= np.linalg.norm(lateral_sample)
    up_sample = np.cross(lateral_sample, expected_direction)
    offset = (expected_direction * local[0] + lateral_sample * local[1]
              + up_sample * local[2]) * (.2 / reference_length)
    material = sampled[2] + offset
    if mode == 'stationary':
        np.testing.assert_allclose(material, target_point, atol=1e-9)
    else:
        assert abs(float(material @ normal) - plane_offset) <= 1e-9
        assert np.linalg.norm((material - target_point)
                              - np.dot(material - target_point, normal) * normal) > 1e-5
    assert np.linalg.norm(sampled[2] - hip) <= 1.3

    from exercise_motion_pkg.rig_interpolation import frame_boundary_velocity_jump
    from exercise_motion_pkg.rig_playback import PLAYBACK_CONTACT_LIMIT_METERS

    boundary_rig = deepcopy(rig)
    direction = directions[0].copy()
    axis = side_axes[0].copy()
    boundary_track = boundary_rig['contactFootTracks']['left']
    boundary_track['directions'] = np.repeat(direction[None, :], 3, axis=0).tolist()
    boundary_track['sideAxes'] = np.repeat(axis[None, :], 3, axis=0).tolist()

    def sample_boundary(query):
        query = np.asarray(query, dtype=float).reshape(-1)
        raw = np.repeat(points[:1], len(query), axis=0)
        return sample_contact_foot_tracks(
            boundary_rig, query, raw, native_foot_geometry=native_geometry,
            foot_scale=foot_scale)

    exact_keys = sample_boundary([0., 1.])
    np.testing.assert_array_equal(exact_keys, np.repeat(points[:1], 2, axis=0))
    assert frame_boundary_velocity_jump(sample_boundary, [1.], 30.) < 1e-3

    query = np.asarray([0., .0001, .25, .5, .75, .9999, 1.])
    raw = np.repeat(points[:1], len(query), axis=0)
    boundary, boundary_axes = sample_contact_foot_tracks(
        boundary_rig, query, raw, native_foot_geometry=native_geometry,
        foot_scale=foot_scale, return_side_axes=True)
    boundary_shoes = shoe_vertices(
        boundary[:, 2], boundary[:, 3], boundary_axes['left'], None,
        foot_scale, native_geometry=native_geometry['sides']['left'])
    material_points = np.asarray([
        barycentric @ shoe[triangle] for shoe in boundary_shoes])
    if mode == 'stationary':
        errors = np.linalg.norm(material_points - target_point, axis=1)
    else:
        errors = np.abs(material_points @ normal - plane_offset)
    assert float(np.max(errors)) <= PLAYBACK_CONTACT_LIMIT_METERS

    invalid = deepcopy(rig)
    invalid['contactFootTracks']['left']['episodes'][0]['materialOffsetLocalMeters'][0] += .01
    with pytest.raises(ValueError, match='cache differs from its mesh binding'):
        sample_contact_foot_tracks(
            invalid, [cursor], points[1:2], native_foot_geometry=native_geometry,
            foot_scale=foot_scale)


@pytest.mark.parametrize('full_fk', [False, True])
def test_unilateral_native_contact_retraction_mirrors_chain_and_shoe_axis(tmp_path, full_fk):
    from scipy.spatial.transform import Rotation
    import json
    from copy import deepcopy
    from pathlib import Path

    from exercise_motion_pkg.foot_geometry import (
        foot_scale_from_pose, sample_material_foot_points, shoe_vertices,
    )
    from exercise_motion_pkg.material_region_support import shoe_triangles
    from exercise_motion_pkg.native_foot_geometry import (
        native_foot_bone_frame, native_foot_marker_world,
    )
    from exercise_motion_pkg.rig_playback import (
        _native_sampling_rig, decode_rig, sample_rig,
    )

    fixture = json.loads((Path(__file__).parent / 'fixtures'
                          / 'native_foot_geometry_v1.json').read_text())
    native_geometry = fixture['reference']
    names = ['pelvis', 'left_hip', 'right_hip', 'left_knee', 'right_knee',
             'left_ankle', 'right_ankle', 'left_foot', 'right_foot']
    parent_names = [None, 'pelvis', 'pelvis', 'left_hip', 'right_hip',
                    'left_knee', 'right_knee', 'left_ankle', 'right_ankle']
    parents = [-1] + [names.index(parent) for parent in parent_names[1:]]
    offsets = np.asarray([
        [0., 0., 0.], [-.12, 1., 0.], [.12, 1., 0.],
        [-.1, -.408656, 0.], [.1, -.408656, 0.],
        [.1, -.4, 0.], [-.1, -.4, 0.], [0., 0., .2], [0., 0., .2],
    ])
    rig = {
        'jointNames': names, 'parents': parents, 'order': list(range(len(names))),
        'rotationJointNames': [], 'coordinates': np.zeros((3, 3)).tolist(),
        'offsets': offsets.tolist(), 'interpolation': 'limited_quaternion_hermite_v1',
    }
    points = decode_rig(rig, rig['coordinates'])
    scale = foot_scale_from_pose(points[0], names)
    triangles = shoe_triangles()
    triangle_index, bary = 11, np.asarray([.2, .3, .5])
    tracks = {'version': 2}

    def side_track(side, active):
        ankle, foot = names.index(f'{side}_ankle'), names.index(f'{side}_foot')
        axis = np.asarray([1., 0., 0.])
        mesh = shoe_vertices(points[0, ankle], points[0, foot], axis, None,
                             scale, native_geometry=native_geometry['sides'][side])
        target = bary @ mesh[triangles[triangle_index]]
        forward, lateral, up, length = native_foot_bone_frame(
            points[0, ankle], points[0, foot], axis)
        delta = target - points[0, ankle]
        reference = native_geometry['sides'][side]['ankleToFootJointLengthMeters']
        local = np.asarray([delta @ forward, delta @ lateral, delta @ up])
        local *= reference / float(length[0])
        episode = {
            'startFrame': 0, 'endFrame': 2, 'anchorId': f'{side}:anchor',
            'regionRole': 'forefoot', 'mode': 'verticalOnly',
            'primitiveId': f'wearShoe:{side}_ankle->{side}_foot',
            'triangleIndex': triangle_index, 'barycentric': bary.tolist(),
            'materialOffsetLocalMeters': local.tolist(),
            'referenceLengthMeters': reference,
            'surfaceNormal': [0., 1., 0.],
            'planeOffsetMeters': float(target[1] + .01),
        }
        return {
            'active': [active] * 3,
            'directions': [[0., 0., 1.]] * 3,
            'sideAxes': [axis.tolist()] * 3,
            'anchorIds': [f'{side}:anchor' if active else None] * 3,
            'episodes': [episode] if active else [],
        }

    tracks['right'] = side_track('right', True)
    tracks['left'] = side_track('left', False)
    rig['contactFootTracks'] = tracks
    frames = [{'joints': {name: points[index, joint].tolist()
                          for joint, name in enumerate(names)}}
              for index in range(3)]
    payload = {
        'jointNames': names, 'frames': frames, 'fixedRig': rig,
        'nativeFootGeometry': native_geometry,
        'canonicalExecution': {'legs': 'mirrored'}, 'fps': 30.,
    }

    if full_fk:
        rig['materialFrames'] = {'version': 1, 'referenceCoordinates': deepcopy(rig['coordinates']),
            'referenceBoneSides': {f'{side}_ankle->{side}_foot': [[1., 0., 0.]]*3
                                   for side in ('left', 'right')}}
    cursor = np.asarray([1.5])
    sampling_rig = _native_sampling_rig(payload)
    sampled, axes = sample_rig(sampling_rig, cursor, return_side_axes=True)
    sampled_default = sample_rig(sampling_rig, cursor)
    assert isinstance(sampled_default, np.ndarray)
    np.testing.assert_allclose(sampled_default, sampled, atol=1e-12)
    np.testing.assert_array_equal(rig['contactFootTracks']['left']['active'], [False] * 3)
    assert rig['contactFootTracks']['left']['anchorIds'] == [None] * 3
    key_samples = sample_rig(sampling_rig, np.arange(3, dtype=float))
    np.testing.assert_allclose(key_samples, points, atol=1e-12)

    # The right material constraint remains the physical driver, while the
    # unconstrained left chain and its model axis follow the same reflection.
    normal = np.asarray([1., 0., 0.])
    for part in ('knee', 'ankle', 'foot'):
        left_i, right_i = names.index(f'left_{part}'), names.index(f'right_{part}')
        right_parent = {'knee': 'right_hip', 'ankle': 'right_knee', 'foot': 'right_ankle'}[part]
        right_offset = sampled[0, right_i] - sampled[0, names.index(right_parent)]
        left_parent = {'knee': 'left_hip', 'ankle': 'left_knee', 'foot': 'left_ankle'}[part]
        left_offset = sampled[0, left_i] - sampled[0, names.index(left_parent)]
        reflected = right_offset - 2. * np.dot(right_offset, normal) * normal
        np.testing.assert_allclose(left_offset, reflected, atol=1e-9)
    expected_left_axis = axes['right'][0] - 2. * np.dot(axes['right'][0], normal) * normal
    expected_left_axis *= -1.
    expected_left_axis /= np.linalg.norm(expected_left_axis)
    np.testing.assert_allclose(axes['left'][0], expected_left_axis, atol=1e-9)

    # The production material shoe sampler uses that transported axis.
    shoe = sample_material_foot_points(payload, cursor)['left']
    np.testing.assert_allclose(shoe['sideAxis'], axes['left'], atol=1e-9)
    left_i, ankle_i = names.index('left_foot'), names.index('left_ankle')
    left_marker = native_foot_marker_world(
        sampled[:, ankle_i], sampled[:, left_i], shoe['sideAxis'],
        native_geometry['sides']['left'])
    np.testing.assert_allclose(shoe['heel'], left_marker[0], atol=1e-9)
    np.testing.assert_allclose(shoe['toe'], left_marker[1], atol=1e-9)

    # A preserved key can differ slightly from perfect bilateral reflection.
    # Both its rigid chain and serialized material frame must remain the limit.
    asymmetric = deepcopy(payload)
    asymmetric_offsets = np.asarray(asymmetric['fixedRig']['offsets'])
    turn = Rotation.from_rotvec([0., .015, 0.])
    for part in ('knee', 'ankle', 'foot'):
        index = names.index(f'left_{part}')
        asymmetric_offsets[index] = turn.apply(asymmetric_offsets[index])
    asymmetric['fixedRig']['offsets'] = asymmetric_offsets.tolist()
    original = decode_rig(asymmetric['fixedRig'], asymmetric['fixedRig']['coordinates'])
    original_axis = Rotation.from_rotvec([0., 0., .2]).apply([1., 0., 0.])
    for index, frame in enumerate(asymmetric['frames']):
        frame['joints'] = dict(zip(names, original[index].tolist()))
        frame['boneSides'] = {f'{side}_ankle->{side}_foot': original_axis.tolist()
                             for side in ('left', 'right')}
    if full_fk:
        asymmetric['fixedRig']['materialFrames']['referenceBoneSides'] = {
            f'{side}_ankle->{side}_foot': [original_axis.tolist()]*3 for side in ('left', 'right')}
    from exercise_motion_pkg.foot_geometry import _sample_material_foot_geometry
    asym_rig = _native_sampling_rig(asymmetric)
    previous = None
    for epsilon in (1e-3, 1e-4):
        queries = np.asarray([1. - epsilon, 1., 1. + epsilon])
        poses, sample_axes = sample_rig(asym_rig, queries, return_side_axes=True)
        np.testing.assert_allclose(poses[1], original[1], atol=1e-12)
        for joint, parent in enumerate(parents):
            if parent >= 0:
                np.testing.assert_allclose(np.linalg.norm(poses[:, joint] - poses[:, parent], axis=1),
                                           np.linalg.norm(asymmetric_offsets[joint]), atol=1e-12)
        material = _sample_material_foot_geometry(
            asymmetric, queries, poses, side_axes_override=sample_axes)
        errors = [np.linalg.norm(poses[[0, 2]] - poses[1], axis=-1).max()]
        for side in ('left', 'right'):
            ankle_index, foot_index = (names.index(f'{side}_{part}') for part in ('ankle', 'foot'))
            mesh = shoe_vertices(poses[:, ankle_index], poses[:, foot_index], material[side]['lateral'],
                                 None, scale, native_geometry=native_geometry['sides'][side])
            errors.append(np.linalg.norm(mesh[[0, 2]] - mesh[1], axis=-1).max())
        errors = np.asarray(errors)
        if previous is not None:
            assert np.all(errors < previous * .02), (previous, errors)
        previous = errors

    partial_points, partial_axes = sample_rig(asym_rig, [1.25], return_side_axes=True)
    right_ankle, right_foot = names.index('right_ankle'), names.index('right_foot')
    partial_mesh = shoe_vertices(partial_points[:, right_ankle], partial_points[:, right_foot],
                                partial_axes['right'], None, scale,
                                native_geometry=native_geometry['sides']['right'])
    actual_material = bary @ partial_mesh[0, triangles[triangle_index]]
    raw_material = original[1, right_ankle] + actual_material - partial_points[0, right_ankle]
    expected_material = raw_material.copy()
    expected_material[1] += (16 * .25**2 * .75**2) * (
        tracks['right']['episodes'][0]['planeOffsetMeters'] - raw_material[1])
    np.testing.assert_allclose(actual_material, expected_material, atol=1e-10)

    # Exercise the generated browser kernel on the same asymmetric material frame.
    import shutil
    import subprocess
    from exercise_motion_pkg.preview import _build_html
    node = shutil.which('node')
    three = Path(__file__).resolve().parents[1] / 'build/exercise_motion/web-assets/three.module.0.169.0.js'
    if node and three.is_file():
        html = _build_html({'title': 'mirror continuity', 'frames': [], 'jointNames': names})
        kernel = (
            html[html.index('    function wearValidateNativeFootGeometry('):html.index('    let activeNativeFootGeometry =')]
            + 'let activeNativeFootGeometry = wearValidateNativeFootGeometry(input.nativeFootGeometry);\n'
            + html[html.index('    let wearStableBodyProportions = null;'):html.index('    const perspectiveCamera = new THREE.PerspectiveCamera(')]
            + html[html.index('    function limitedRigTangent('):html.index('    function getInterpolatedFrame()')]
            + html[html.index('    function interpolateShoeOrientation('):html.index('    function interpolateFrameSourceMapping(')])
        (tmp_path / 'kernel.js').write_text(kernel, encoding='utf-8')
        queries = [0., .0001, .9999, 1., 1.0001, 1.25, 1.5]
        browser_input = {**asymmetric, 'queries': queries}
        browser_input['fixedRig'] = {**asymmetric['fixedRig'],
                                    '_canonicalExecutionForSampling': {'legs': 'mirrored'}}
        (tmp_path / 'input.json').write_text(json.dumps(browser_input), encoding='utf-8')
        (tmp_path / 'sample.mjs').write_text('''
import fs from 'node:fs';
const THREE = await import('data:text/javascript;base64,' + fs.readFileSync(process.argv[2]).toString('base64'));
const input = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const playbackState = {loopable:false, frames:input.frames};
const sample = new Function('THREE', 'playbackState', 'input', fs.readFileSync(process.argv[4], 'utf8')
  + ';return interpolateFixedRig;')(THREE, playbackState, input);
console.log(JSON.stringify(input.queries.map(q => {
  const first = Math.floor(q), last = Math.min(first + 1, input.frames.length - 1);
  const pose = sample(input.fixedRig, first, last, q - first);
  return {joints:pose, axes:pose.contactSideAxes};
})));
''', encoding='utf-8')
        browser = json.loads(subprocess.check_output(
            [node, str(tmp_path / 'sample.mjs'), str(three), str(tmp_path / 'input.json'),
             str(tmp_path / 'kernel.js')], text=True, timeout=30))
        expected_points, expected_axes = sample_rig(asym_rig, queries, return_side_axes=True)
        actual_points = np.asarray([[row['joints'][name] for name in names] for row in browser])
        np.testing.assert_allclose(actual_points, expected_points, atol=1e-9)
        for index, query in enumerate(queries):
            if full_fk or query != int(query):
                np.testing.assert_allclose(browser[index]['axes']['left_ankle->left_foot'],
                                           expected_axes['left'][index], atol=1e-9)
                np.testing.assert_allclose(browser[index]['axes']['right_ankle->right_foot'],
                                           expected_axes['right'][index], atol=1e-9)

    for protected_part in ('knee', 'ankle'):
        protected_payload = deepcopy(asymmetric)
        protected_payload['fixedRig']['supportJointTracks'] = {
            'version': 1, 'source': 'validated_stationary_body_support',
            'joints': {f'left_{protected_part}': {'episodeIds': ['support'] * 3}}}
        protected_pose = sample_rig(_native_sampling_rig(protected_payload), [.5])
        unchanged = ['left_knee'] if protected_part == 'knee' else [
            'left_knee', 'left_ankle', 'left_foot']
        for joint in unchanged:
            np.testing.assert_allclose(protected_pose[0, names.index(joint)],
                                       original[0, names.index(joint)], atol=1e-12)
    right_ankle, right_foot = names.index('right_ankle'), names.index('right_foot')
    right_mesh = shoe_vertices(
        sampled[:, right_ankle], sampled[:, right_foot], axes['right'], None, scale,
        native_geometry=native_geometry['sides']['right'])
    right_contact = bary @ right_mesh[:, triangles[triangle_index]]
    assert float(right_contact[0, 1]) == pytest.approx(
        tracks['right']['episodes'][0]['planeOffsetMeters'], abs=1e-8)

    # Both-active symmetric support leaves both independently solved targets intact.
    both = deepcopy(payload)
    both['fixedRig']['contactFootTracks']['left'] = side_track('left', True)
    both_points, both_axes = sample_rig(
        _native_sampling_rig(both), cursor, return_side_axes=True)
    for part in ('knee', 'ankle', 'foot'):
        li, ri = names.index(f'left_{part}'), names.index(f'right_{part}')
        np.testing.assert_allclose(both_points[0, li, 1:], both_points[0, ri, 1:], atol=1e-8)
    assert np.isfinite(both_axes['left']).all() and np.isfinite(both_axes['right']).all()


@pytest.mark.parametrize('explicit_ankle', [False, True])
def test_native_material_owner_suppresses_only_implicit_full_sole_ankle_pin(explicit_ankle):
    from exercise_motion_pkg.contact_interpolation import suppress_native_foot_pins
    from exercise_motion_pkg.sequence_stabilization import contact_mask

    names = ['left_ankle', 'left_foot']
    foot_contact = {'jointName': 'left_foot', 'contactState': 'full_sole',
                    'contactMotion': 'stationary', 'verticalOnly': False,
                    '_fitFrameBounds': [1, 3], '_fitFrameCount': 5}
    contacts = [foot_contact]
    if explicit_ankle:
        contacts.append({'jointName': 'left_ankle', 'contactState': 'full_sole',
                         'contactMotion': 'stationary', 'verticalOnly': False,
                         '_fitFrameBounds': [1, 3], '_fitFrameCount': 5})
    evidence = {'contacts': contacts}
    pinned = contact_mask({}, names, 5, support_evidence=evidence)
    track = {'version': 2, 'left': {
        'active': [False, True, True, True, False],
        'directions': [[0., 0., 1.]] * 5,
        'sideAxes': [[-1., 0., 0.]] * 5,
        'anchorIds': [None, 'left:sole:0', 'left:sole:0', 'left:sole:0', None],
        'episodes': [{
            'startFrame': 1, 'endFrame': 3, 'anchorId': 'left:sole:0',
            'regionRole': 'full_sole', 'mode': 'stationary',
            'primitiveId': 'wearShoe:left_ankle->left_foot',
            'triangleIndex': 12, 'barycentric': [.25, .5, .25],
            'materialOffsetLocalMeters': [.1, .01, 0.],
            'referenceLengthMeters': .2, 'targetWorld': [0., 0., 0.],
            'surfaceNormal': [0., 1., 0.], 'planeOffsetMeters': 0.,
        }],
    }}

    result = suppress_native_foot_pins(
        pinned, names, track, support_evidence=evidence)
    np.testing.assert_array_equal(result[:, names.index('left_foot')], np.zeros(5, dtype=bool))
    np.testing.assert_array_equal(
        result[:, names.index('left_ankle')],
        [False, explicit_ankle, explicit_ankle, explicit_ankle, False])


def test_native_contact_binding_pre_rig_uses_joint_name_context():
    import json
    from pathlib import Path
    from exercise_motion_pkg.contact_interpolation import build_native_foot_contact_tracks

    fixture = json.loads((Path(__file__).parent.parent / '.scratch'
                          / 'goal-contact-continuation' / 'native-foot-contact-owner-v270'
                          / 'native_material_contact_tracks_v2.json').read_text())
    names = ['left_hip', 'right_hip', 'left_ankle', 'left_foot']
    points = np.asarray([
        [[-.1, 1., 0.], [.1, 1., 0.], [0., .1, 0.],
         [0., .1, .13402119093912526]],
    ] * 2)
    pinned = np.zeros((2, len(names)), dtype=bool)
    pinned[:, names.index('left_foot')] = True
    side_axes = {'left': np.asarray([[1., 0., 0.]] * 2)}
    evidence = {'contacts': [{
        'jointName': 'left_foot', 'contactState': 'full_sole',
        'contactMotion': 'stationary', 'verticalOnly': False,
        'surfaceKind': 'ground', '_fitFrameBounds': [0, 1], '_fitFrameCount': 2,
    }]}
    tracks, owned = build_native_foot_contact_tracks(
        {'jointNames': names}, points, pinned, side_axes, evidence,
        fixture['nativeFootGeometry'], floor=0.)
    assert tracks['version'] == 2
    np.testing.assert_array_equal(owned[:, names.index('left_foot')], [True, True])


def test_native_contact_reselects_forefoot_point_after_corrected_orientation():
    import copy
    import json
    from pathlib import Path
    from exercise_motion_pkg.contact_interpolation import (
        reselect_native_material_episode_at_pose,
    )
    from exercise_motion_pkg.foot_geometry import shoe_vertices
    from exercise_motion_pkg.material_region_support import shoe_triangles

    fixture = json.loads((Path(__file__).parent.parent / '.scratch'
                          / 'goal-contact-continuation' / 'native-foot-contact-owner-v270'
                          / 'native_material_contact_tracks_v2.json').read_text())
    geometry = fixture['nativeFootGeometry']
    names = ['right_ankle', 'right_foot']
    pose = np.asarray([
        [-0.4323607135131624, -0.3668031489591078, 0.20551202042933472],
        [-0.5345013875674767, -0.4492445884914334, 0.17432655870431743],
    ])
    side_axis = np.asarray([-0.6116300263779256, 0.7872881914925897,
                            -0.0780129115548511])
    frame = 67
    active = [True] * (frame + 1)
    direction = pose[1] - pose[0]
    direction /= np.linalg.norm(direction)
    episode = {
        'startFrame': 0, 'endFrame': frame, 'anchorId': 'right-foot-stationary-0',
        'regionRole': 'forefoot', 'mode': 'stationary',
        'primitiveId': 'wearShoe:right_ankle->right_foot',
        'triangleIndex': 26, 'barycentric': [0., 0., 1.],
        'materialOffsetLocalMeters': [.1813713, -.0012584, .0090296],
        'referenceLengthMeters': geometry['sides']['right']['ankleToFootJointLengthMeters'],
        'targetWorld': [-0.5686098393361795, -0.49793051381351106,
                        0.17250596628982107],
        'surfaceNormal': [0., 1., 0.], 'planeOffsetMeters': -0.49793051381351106,
    }
    tracks = {'version': 2, 'right': {
        'active': active,
        'directions': [direction.tolist()] * len(active),
        'sideAxes': [side_axis.tolist()] * len(active),
        'anchorIds': ['right-foot-stationary-0'] * len(active),
        'episodes': [episode],
    }}
    observed_contact = {
        'jointName': 'right_foot', 'contactState': 'toe_only',
        'contactMotion': 'stationary', 'surfaceKind': 'ground',
    }
    original_contact = copy.deepcopy(observed_contact)
    original_barycentric = list(episode['barycentric'])
    rebound, changed = reselect_native_material_episode_at_pose(
        tracks, 'right', names, pose, side_axis, geometry, .17835098143407824, frame)
    assert changed is True
    updated = rebound['right']['episodes'][0]
    assert updated['triangleIndex'] == 22
    assert updated['barycentric'] == [0., 0., 1.]
    assert updated['regionRole'] == 'forefoot'
    assert updated['mode'] == 'stationary'
    assert updated['anchorId'] == episode['anchorId']
    assert updated['startFrame'] == episode['startFrame']
    assert updated['endFrame'] == episode['endFrame']
    assert updated['targetWorld'] == episode['targetWorld']
    assert observed_contact == original_contact
    assert rebound is tracks
    mesh = shoe_vertices(pose[0], pose[1], side_axis, None,
                         .17835098143407824,
                         native_geometry=geometry['sides']['right'])
    triangles = shoe_triangles()
    point = np.asarray(updated['barycentric']) @ mesh[triangles[updated['triangleIndex']]]
    target = np.asarray(updated['targetWorld'])
    translated_mesh = mesh + (target - point)
    assert np.min(translated_mesh[:, 1]) >= updated['planeOffsetMeters'] - 1e-8
    old_point = np.asarray(original_barycentric) @ mesh[triangles[26]]
    old_mesh_at_target = mesh + (target - old_point)
    assert np.min(old_mesh_at_target[:, 1]) < updated['planeOffsetMeters'] - .02
