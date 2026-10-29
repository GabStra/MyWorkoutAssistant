import numpy as np
from copy import deepcopy
from scipy.sparse import csr_matrix
from scipy.spatial.transform import Rotation

from exercise_motion_pkg.trajectory_restoration import (
    temporal_gate_metrics_and_jacobian,
)


def test_coupled_temporal_admission_preserves_native_articulation_authority():
    from exercise_motion_pkg.controlled_motion import contact_tangent_temporal_repair_eligible

    report = {
        'checks': {'contacts': True, 'anatomy': True, 'jerk': False,
                   'jointShake': False, 'relativeJointShake': False,
                   'sourceFootContactArticulation': False},
        'playback': {'passed': True},
        'sourceFootContactArticulation': {
            'nativeHeelPhase': {'passed': True},
            'sourceFootDirection': {'passed': True},
            'materialHeelTrajectory': {'passed': True},
            'regressions': [{'feature': 'left_ankle_raw_contact_state_episode_excursion'}],
        },
    }
    assert contact_tangent_temporal_repair_eligible(report)
    native_failure = deepcopy(report)
    native_failure['sourceFootContactArticulation']['materialHeelTrajectory']['passed'] = False
    assert not contact_tangent_temporal_repair_eligible(native_failure)
    knee_failure = deepcopy(report)
    knee_failure['sourceFootContactArticulation']['regressions'] = [
        {'feature': 'left_knee_bend_direction'}]
    assert not contact_tangent_temporal_repair_eligible(knee_failure)
    contact_failure = deepcopy(report)
    contact_failure['checks']['contacts'] = False
    assert not contact_tangent_temporal_repair_eligible(contact_failure)


class LinearRig:
    names = [
        'pelvis', 'left_knee', 'left_ankle', 'left_foot',
        'right_knee', 'right_ankle', 'right_foot',
    ]
    width = len(names) * 3

    def decode(self, coordinates):
        return np.asarray(coordinates).reshape(-1, len(self.names), 3)

    def fk_jacobian(self, coordinates):
        return csr_matrix(np.eye(np.asarray(coordinates).size))


def _trajectory():
    rig = LinearRig()
    points = np.zeros((8, len(rig.names), 3), dtype=float)
    for frame in range(len(points)):
        t = float(frame)
        pelvis = np.asarray([.006 * t * t, 1. + .004 * t, .003 * np.sin(.6 * t)])
        points[frame, 0] = pelvis
        points[frame, 1] = pelvis + np.asarray([-.10, -.29 + .004 * np.sin(.8 * t), .01])
        points[frame, 2] = points[frame, 1] + np.asarray([.01, -.30 + .003 * np.cos(.5 * t), .01])
        left_pitch = .48 + .07 * np.sin(.72 * t) + .009 * t
        points[frame, 3] = points[frame, 2] + np.asarray([
            .20 * np.cos(left_pitch), -.20 * np.sin(left_pitch), .025 + .002 * t,
        ])
        points[frame, 4] = pelvis + np.asarray([.10, -.30 + .003 * np.cos(.7 * t), -.01])
        points[frame, 5] = points[frame, 4] + np.asarray([-.01, -.30 + .003 * np.sin(.4 * t), -.01])
        right_pitch = .45 + .05 * np.sin(.61 * t + .2) + .006 * t
        points[frame, 6] = points[frame, 5] + np.asarray([
            .19 * np.cos(right_pitch), -.19 * np.sin(right_pitch), -.02 + .001 * t,
        ])
    return rig, points.reshape(len(points), -1)


def _metrics(coordinates, rig, d3, episode):
    names, violations, _ = temporal_gate_metrics_and_jacobian(
        coordinates, rig, world_d3=d3, jerk_limit=.003,
        joint_shake_limits={'left_ankle': .02, 'right_knee': .02},
        relative_shake_limits={'pelvis': .02, 'left_ankle': .02},
        ankle_episodes=[episode],
    )
    return names, violations


def test_temporal_gate_gradients_match_finite_differences_and_keep_passing_rows():
    rig, coordinates = _trajectory()
    frame_count = len(coordinates)
    d3 = csr_matrix(np.diff(np.eye(frame_count), n=3, axis=0))
    episode = {
        'side': 'left', 'startFrame': 0, 'stopFrame': frame_count,
        'sourceRangeRadians': .24, 'minimumPreservedRatio': .85,
        'name': 'left_ankle_raw_contact_state_episode_excursion',
    }
    names, violations, jacobian = temporal_gate_metrics_and_jacobian(
        coordinates, rig, world_d3=d3, jerk_limit=.003,
        joint_shake_limits={'left_ankle': .02, 'right_knee': .02},
        relative_shake_limits={'pelvis': .02, 'left_ankle': .02},
        ankle_episodes=[episode],
    )

    assert names == [
        'jerk', 'jointShake:left_ankle', 'jointShake:right_knee',
        'relativeJointShake:pelvis', 'relativeJointShake:left_ankle',
        'sourceFootContactArticulation:left_ankle_raw_contact_state_episode_excursion',
    ]
    assert jacobian.shape == (len(names), coordinates.size)
    assert violations[names.index('relativeJointShake:pelvis')] == -1.
    assert jacobian.getrow(names.index('relativeJointShake:pelvis')).nnz == 0

    expected = jacobian.toarray()
    step = 1e-6
    for column in range(coordinates.size):
        plus, minus = coordinates.copy(), coordinates.copy()
        plus.flat[column] += step
        minus.flat[column] -= step
        plus_names, plus_values = _metrics(plus, rig, d3, episode)
        minus_names, minus_values = _metrics(minus, rig, d3, episode)
        assert plus_names == names == minus_names
        numerical = (plus_values - minus_values) / (2. * step)
        np.testing.assert_allclose(expected[:, column], numerical, rtol=2e-4, atol=2e-6)


def test_settling_gate_matches_rotated_body_metric_and_coordinate_gradient():
    import json
    from pathlib import Path

    from exercise_motion_pkg.controlled_motion import (
        FixedRig, body_relative_points, weighted_settling_speed,
    )
    from exercise_motion_pkg.temporal_quality import body_orientation_axes

    fixture = json.loads(
        (Path(__file__).parent / 'fixtures' / 'sequence_stabilization_stance.json').read_text())
    names = list(fixture['joints'])
    points = np.tile(np.asarray(list(fixture['joints'].values()), dtype=float), (8, 1, 1))
    rig = FixedRig(points, names)
    coordinates = rig.initial.copy()
    frames = len(coordinates)

    for joint_name, angles_xyz in (
            ('pelvis', np.column_stack((.17 * np.sin(np.arange(frames) * .5),
                                        .11 * np.cos(np.arange(frames) * .4),
                                        .13 * np.sin(np.arange(frames) * .3)))),
            ('spine3', np.column_stack((.08 * np.cos(np.arange(frames) * .6),
                                        .05 * np.sin(np.arange(frames) * .5),
                                        .07 * np.cos(np.arange(frames) * .35)))),
            ('left_knee', np.column_stack((.12 * np.sin(np.arange(frames) * .7),
                                           .04 * np.cos(np.arange(frames) * .5),
                                           .06 * np.sin(np.arange(frames) * .4))))):
        slot = rig.slots[names.index(joint_name)]
        original = Rotation.from_rotvec(coordinates[:, slot:slot + 3])
        coordinates[:, slot:slot + 3] = (
            Rotation.from_euler('xyz', angles_xyz) * original).as_rotvec()
    coordinates[:, :3] += np.column_stack((
        .012 * np.sin(np.arange(frames) * .35),
        .009 * np.cos(np.arange(frames) * .45),
        .008 * np.sin(np.arange(frames) * .25),
    ))

    decoded = rig.decode(coordinates)
    relative = body_relative_points(decoded, names)
    assert np.ptp(relative[:, names.index('left_wrist'), 0]) > .02
    axes = body_orientation_axes(decoded, names)
    assert np.max(np.linalg.norm(axes - axes[:1], axis=-1)) > .05

    fps = 30.
    weights = np.ones((frames - 1, len(names), 1), dtype=float)
    weights[[1, 4], [names.index('left_hand'), names.index('right_hand')], 0] = 0.
    measured = weighted_settling_speed(decoded, names, fps, weights)
    settling_limit = measured * .98
    d3 = csr_matrix(np.diff(np.eye(frames), n=3, axis=0))
    options = dict(
        world_d3=d3, jerk_limit=.01, joint_shake_limits={},
        relative_shake_limits={}, ankle_episodes=[], settling_weights=weights,
        settling_limit=settling_limit, fps=fps,
    )
    metric_names, violations, jacobian = temporal_gate_metrics_and_jacobian(
        coordinates, rig, **options)
    settling_row = metric_names.index('settling')
    np.testing.assert_allclose(
        violations[settling_row], measured / settling_limit - 1., rtol=1e-12, atol=1e-12)

    analytic = jacobian.getrow(settling_row).toarray().ravel()
    step = 1e-6
    columns = []
    for frame in (1, 3, 5):
        for joint_name in ('pelvis', 'spine3', 'left_knee'):
            slot = rig.slots[names.index(joint_name)]
            columns.extend(frame * rig.width + slot + axis for axis in range(3))
    for column in columns:
        plus, minus = coordinates.copy(), coordinates.copy()
        plus.flat[column] += step
        minus.flat[column] -= step
        plus_speed = weighted_settling_speed(rig.decode(plus), names, fps, weights)
        minus_speed = weighted_settling_speed(rig.decode(minus), names, fps, weights)
        numerical = (plus_speed - minus_speed) / (2. * step * settling_limit)
        np.testing.assert_allclose(analytic[column], numerical, rtol=3e-3, atol=3e-5)
