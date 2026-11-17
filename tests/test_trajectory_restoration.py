import json
from pathlib import Path

import numpy as np
import pytest
from scipy.sparse import csr_matrix

from exercise_motion_pkg.controlled_motion import FixedRig
from exercise_motion_pkg.trajectory_restoration import (
    inequality_gate_restoration_step,
    temporal_gate_metrics_and_jacobian,
)


def test_gate_backtracking_finds_curved_descent_and_stops_at_stagnation():
    from exercise_motion_pkg.trajectory_restoration import representable_backtracking_trials
    # The analytic descent direction overshoots this curved objective through
    # all five formerly attempted fractions; the next fraction improves it.
    objective = lambda values: float((values[0] - .02) ** 2)
    before = np.array([0.])
    accepted = next((alpha, trial) for alpha, trial in
                    representable_backtracking_trials(before, np.array([1.]))
                    if objective(trial) < objective(before))
    assert accepted[0] == .03125
    assert not list(representable_backtracking_trials(before, before))
    before = np.array([1.])
    trials = list(representable_backtracking_trials(before, np.nextafter(before, np.inf)))
    assert len(trials) == 1
    assert not np.array_equal(trials[0][1], before)


def test_vector_norm_exchange_uses_norm_minimizing_step_on_bounded_direction():
    class LinearRig:
        width = 2

        def decode(self, coordinates):
            q = np.asarray(coordinates, dtype=float).reshape(-1, 2)
            return np.stack((q[:, 0], q[:, 1], np.zeros(len(q))), axis=1)[:, None, :]

        def fk_jacobian(self, coordinates):
            rows = np.array([[1., 0.], [0., 1.], [0., 0.]])
            return csr_matrix(rows)

    rig = LinearRig()
    base = np.zeros((1, 2))
    pinned = np.zeros((1, 1), dtype=bool)
    violations = np.array([.01, .5])
    jacobian = csr_matrix([[1., 0.], [0., 1.]])
    model = {
        'name': 'jerk', 'row_index': 0,
        'residual': np.array([1.01, 0.]),
        'apply_delta': lambda delta: np.asarray(delta, dtype=float),
        'tangent_row': lambda direction: csr_matrix(
            np.asarray(direction, dtype=float).reshape(1, 2)),
    }

    legacy, _ = inequality_gate_restoration_step(
        base, rig, pinned, violations, jacobian,
        numerical_margin=.001, max_point_shift_meters=2.)
    legacy_norm = np.linalg.norm(model['residual'] + legacy.reshape(-1))
    assert legacy_norm > 1.

    candidate, evidence = inequality_gate_restoration_step(
        base, rig, pinned, violations, jacobian,
        numerical_margin=.001, max_point_shift_meters=2.,
        vector_norm_models=[model])
    assert evidence['vectorNormModels'][0]['status'] == 'affine_norm_feasible'
    assert evidence['vectorNormModels'][0]['uncappedPredictedNorm'] <= .999 + 1e-10
    assert np.linalg.norm(model['residual'] + candidate.reshape(-1)) <= legacy_norm
    assert candidate[0, 1] < 0.

    partial, partial_evidence = inequality_gate_restoration_step(
        base, rig, pinned, violations, jacobian,
        numerical_margin=.001, max_point_shift_meters=2.,
        vector_norm_models=[model], max_vector_norm_cuts=1)
    partial_model = partial_evidence['vectorNormModels'][0]
    assert partial_model['status'] == 'affine_norm_feasible'
    assert partial_model['modelGateFeasible'] is True
    assert partial_model['uncappedModelGateFeasible'] is False
    assert partial_model['cappedPredictedNorm'] < np.linalg.norm(model['residual'])
    assert np.linalg.norm(model['residual'] + partial.reshape(-1)) <= .999 + 1e-10
    assert len(partial_evidence['normalizedViolationsBefore']) == len(violations)
    assert len(partial_evidence['normalizedViolationsAfterLinearization']) == len(violations)
    assert 'normExchangeQpMeritAfter' in partial_evidence
    assert partial_evidence['cappedNormModelMeritAfter'] < partial_evidence['cappedNormModelMeritBefore']
    assert not np.allclose(partial, legacy)

    fallback, fallback_evidence = inequality_gate_restoration_step(
        base, rig, pinned, violations, jacobian,
        numerical_margin=.001, max_point_shift_meters=2.,
        vector_norm_models=[model], max_vector_norm_cuts=0)
    fallback_model = fallback_evidence['vectorNormModels'][0]
    assert fallback_model['status'] == 'affine_norm_progress'
    assert fallback_model['lineMinimized'] is True
    assert 0. < fallback_model['lineScale'] < 1.
    assert np.linalg.norm(model['residual'] + fallback.reshape(-1)) < legacy_norm
    assert fallback_evidence['cappedNormModelMeritAfter'] < fallback_evidence['cappedNormModelMeritBefore']


def test_gate_restoration_preserves_active_chest_bound_with_analytic_gradient():
    from exercise_motion_pkg.physical_validation import CHEST_ATTACHMENT_MAX_ANGLE_RADIANS
    from scipy.sparse import vstack
    class ChestRig:
        names = ['pelvis', 'spine3', 'neck', 'left_collar', 'right_collar']
        width = 15
        def decode(self, values):
            return np.asarray(values).reshape(-1, 5, 3)
        def fk_jacobian(self, values):
            return csr_matrix(np.eye(np.asarray(values).size))
    rig = ChestRig()
    limit = CHEST_ATTACHMENT_MAX_ANGLE_RADIANS
    points = np.tile([[0., 0., 0.], [0., 1., 0.],
                      [.3*np.sin(limit), 1.+.3*np.cos(limit), 0.],
                      [-.2, 1.3, 0.], [.2, 1.3, 0.]], (6, 1, 1))
    coordinates = points.reshape(6, -1)
    options = dict(world_d3=csr_matrix(np.diff(np.eye(6), n=3, axis=0)),
                   jerk_limit=10., joint_shake_limits={}, relative_shake_limits={}, ankle_episodes=[])
    labels, values, jacobian = temporal_gate_metrics_and_jacobian(
        coordinates, rig, chest_attachment_limit_radians=limit, **options)
    row = labels.index('anatomyChestAttachment:neck:0')
    step = 1e-6
    plus, minus = coordinates.copy(), coordinates.copy()
    plus[0, 9] += step; minus[0, 9] -= step
    positive = temporal_gate_metrics_and_jacobian(plus, rig, chest_attachment_limit_radians=limit, **options)[1][row]
    negative = temporal_gate_metrics_and_jacobian(minus, rig, chest_attachment_limit_radians=limit, **options)[1][row]
    assert jacobian[row, 9] == pytest.approx((positive-negative)/(2*step), abs=1e-7)
    # Quiet-hold correction can move one collar inward. At the active chest
    # boundary it must use the other free collar too, rather than move the neck.
    objective = csr_matrix(([100.], ([0], [9])), shape=(1, coordinates.size))
    pinned = np.zeros((6, 5), dtype=bool); pinned[:, :3] = True
    unprotected, _ = inequality_gate_restoration_step(
        coordinates, rig, pinned, np.array([1.]), objective,
        numerical_margin=0., max_point_shift_meters=.001)
    protected, evidence = inequality_gate_restoration_step(
        coordinates, rig, pinned, np.r_[values, 1.], vstack([jacobian, objective]),
        numerical_margin=0., max_point_shift_meters=.001)
    def angle(value):
        pose = rig.decode(value)[0]
        a, b = pose[2]-pose[1], (pose[3]+pose[4])*.5-pose[1]
        return np.arccos(np.clip(np.dot(a,b)/(np.linalg.norm(a)*np.linalg.norm(b)), -1., 1.))
    assert angle(unprotected) > limit+1e-4
    assert evidence['applied'] and protected[0, 9] < coordinates[0, 9]
    assert angle(protected) <= limit+1e-8
    np.testing.assert_allclose(rig.decode(protected)[pinned], points[pinned], atol=1e-12)
    class TorsoRig:
        names = ['pelvis', 'left_hip', 'right_hip', 'spine1', 'spine2', 'spine3',
                 'neck', 'left_shoulder', 'right_shoulder']
        width = 27
        def decode(self, values):
            return np.asarray(values).reshape(-1, 9, 3)
        def fk_jacobian(self, values):
            return csr_matrix(np.eye(np.asarray(values).size))
    torso = TorsoRig()
    def torso_pose(degrees):
        theta = np.deg2rad(degrees)
        spine = np.array([0., 1., 0.])
        neck = spine + .5*np.array([np.sin(theta), -np.cos(theta), 0.])
        return np.tile([[0., 0., 0.], [-.2, 0., 0.], [.2, 0., 0.], spine,
                        spine+(neck-spine)/3., spine+2*(neck-spine)/3., neck,
                        neck+[-.1, 0., -.2], neck+[.1, 0., .2]], (6, 1, 1))
    reference, current = torso_pose(130.), torso_pose(129.)
    options.update(preserve_torso_bend=True, anatomy_reference=reference)
    labels, values, derivative = temporal_gate_metrics_and_jacobian(current.reshape(6,-1),torso,**options)
    for label, column in [('spine1', 18), ('shoulders', 21)]:
        row = labels.index(f'anatomyTorsoBend:{label}:0')
        assert abs(values[row]) < 1e-12  # The source-relative floor is 129°, not 145°.
        plus, minus = current.reshape(6,-1).copy(), current.reshape(6,-1).copy()
        plus[0,column] += step; minus[0,column] -= step
        high = temporal_gate_metrics_and_jacobian(plus,torso,**options)[1][row]
        low = temporal_gate_metrics_and_jacobian(minus,torso,**options)[1][row]
        assert derivative[row,column] == pytest.approx((high-low)/(2*step),abs=1e-7)
    labels, values, derivative = temporal_gate_metrics_and_jacobian(
        torso_pose(180.).reshape(6,-1),torso,**options)
    assert np.isfinite(values).all() and np.isfinite(derivative.data).all()
    for label in ('spine1', 'shoulders'):
        row = labels.index(f'anatomyTorsoBend:{label}:0')
        assert values[row] < 0.
        assert np.max(np.abs(derivative[row].toarray())) < 1e-9


def test_gate_restoration_reduces_jerk_in_key_pin_tangent_space():
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "sequence_stabilization_stance.json")
        .read_text(encoding="utf-8")
    )
    names = list(fixture["joints"])
    frame_count = 18
    points = np.tile(
        np.asarray([fixture["joints"][name] for name in names], dtype=float),
        (frame_count, 1, 1),
    )
    rig = FixedRig(points, names)
    coordinates = rig.initial.copy()
    coordinates[:, 2] += .025 * np.asarray(
        [0, 1, -1, 1, -1, 1, -1, 1, -1, 1, -1, 1, -1, 1, -1, 1, -1, 0],
        dtype=float,
    )
    pinned = np.zeros((frame_count, len(names)), dtype=bool)
    pinned[:, [names.index("left_foot"), names.index("right_foot")]] = True
    world_d3 = csr_matrix(np.diff(np.eye(frame_count), n=3, axis=0))

    def jerk_rms(values):
        decoded = rig.decode(values)
        return float(np.sqrt(np.mean((world_d3 @ decoded.reshape(frame_count, -1)) ** 2)))

    points_before = rig.decode(coordinates)
    jerk_before = jerk_rms(coordinates)
    names, violations, jacobian = temporal_gate_metrics_and_jacobian(
        coordinates, rig, world_d3=world_d3, jerk_limit=jerk_before * .9,
        joint_shake_limits={}, relative_shake_limits={}, ankle_episodes=[],
    )
    assert names == ["jerk"]
    candidate, evidence = inequality_gate_restoration_step(
        coordinates, rig, pinned, violations, jacobian,
        numerical_margin=0., max_point_shift_meters=.001,
    )

    assert evidence["applied"]
    assert evidence["maximumKeyPinTangentResidual"] < 1e-10
    assert evidence["maximumPointShiftMeters"] <= .001
    assert jerk_rms(candidate) < jerk_before
    _, violations_after, _ = temporal_gate_metrics_and_jacobian(
        candidate, rig, world_d3=world_d3, jerk_limit=jerk_before * .9,
        joint_shake_limits={}, relative_shake_limits={}, ankle_episodes=[],
    )
    assert violations_after[0] < violations[0]
    pinned_displacement = np.linalg.norm((rig.decode(candidate) - points_before)[pinned], axis=-1)
    assert float(np.max(pinned_displacement, initial=0.)) < 1e-6


class _LinearTrajectoryRig:
    names = ["root", "left_foot", "right_foot"]
    width = len(names) * 3

    def decode(self, coordinates):
        return np.asarray(coordinates, dtype=float).reshape(-1, len(self.names), 3)

    def fk_jacobian(self, coordinates):
        return csr_matrix(np.eye(np.asarray(coordinates).size))


def test_source_knee_envelope_reports_extrema_and_protects_frames_with_finite_difference_jacobian():
    class KneeRig:
        names = ["pelvis", "right_hip", "right_knee", "right_ankle"]
        width = len(names) * 3

        def decode(self, coordinates):
            return np.asarray(coordinates, dtype=float).reshape(-1, len(self.names), 3)

        def fk_jacobian(self, coordinates):
            return csr_matrix(np.eye(np.asarray(coordinates).size))

    rig = KneeRig()
    frame_count = 4
    points = np.zeros((frame_count, len(rig.names), 3), dtype=float)
    points[:, 0] = [0., 2., 0.]
    points[:, 1] = [1., 0., 0.]
    output_angles = np.deg2rad([170., 172., 174., 176.])
    points[:, 3] = np.column_stack((
        np.cos(output_angles), np.sin(output_angles), np.zeros(frame_count),
    ))
    coordinates = points.reshape(frame_count, -1)
    source_angles = np.deg2rad([160., 162., 164., 166.])
    envelope = [{
        "name": "rightKnee",
        "parent": "right_hip",
        "hinge": "right_knee",
        "child": "right_ankle",
        "sourceAnglesRadians": source_angles,
        "allowedExcessDegrees": 6.,
    }]

    names, violations, jacobian = temporal_gate_metrics_and_jacobian(
        coordinates, rig, world_d3=csr_matrix((1, frame_count)), jerk_limit=1.,
        joint_shake_limits={}, relative_shake_limits={}, ankle_episodes=[],
        joint_angle_envelopes=envelope,
    )

    assert names[:3] == [
        "jerk",
        "sourceJointAngleEnvelopeLower:rightKnee",
        "sourceJointAngleEnvelopeUpper:rightKnee",
    ]
    assert len(names) == 3 + frame_count * 2
    lower_index = names.index("sourceJointAngleEnvelopeLower:rightKnee")
    upper_index = names.index("sourceJointAngleEnvelopeUpper:rightKnee")
    assert violations[lower_index] < 0.
    assert violations[upper_index] == pytest.approx(4. / 6.)
    # The current upper extremum is frame 3. Perturb its ankle coordinates and
    # compare the exact reported covector through the rig coordinate map.
    flat = coordinates.ravel()
    column = 3 * rig.width + rig.names.index("right_ankle") * 3 + 1
    epsilon = 1e-6
    plus, minus = flat.copy(), flat.copy()
    plus[column] += epsilon
    minus[column] -= epsilon
    plus_values = temporal_gate_metrics_and_jacobian(
        plus.reshape(coordinates.shape), rig, world_d3=csr_matrix((1, frame_count)),
        jerk_limit=1., joint_shake_limits={}, relative_shake_limits={}, ankle_episodes=[],
        joint_angle_envelopes=envelope,
    )[1]
    minus_values = temporal_gate_metrics_and_jacobian(
        minus.reshape(coordinates.shape), rig, world_d3=csr_matrix((1, frame_count)),
        jerk_limit=1., joint_shake_limits={}, relative_shake_limits={}, ankle_episodes=[],
        joint_angle_envelopes=envelope,
    )[1]
    finite_difference = (plus_values[upper_index] - minus_values[upper_index]) / (2. * epsilon)
    assert float(jacobian[upper_index, column]) == pytest.approx(
        finite_difference, rel=2e-5, abs=2e-6,
    )


def test_source_knee_envelope_handles_straight_hinge_bounds_without_crashing_or_waiving():
    class KneeRig:
        names = ["pelvis", "right_hip", "right_knee", "right_ankle"]
        width = len(names) * 3

        def decode(self, coordinates):
            return np.asarray(coordinates, dtype=float).reshape(-1, len(self.names), 3)

        def fk_jacobian(self, coordinates):
            return csr_matrix(np.eye(np.asarray(coordinates).size))

    rig = KneeRig()
    frame_count = 4
    straight = np.zeros((frame_count, len(rig.names), 3), dtype=float)
    straight[:, 0] = [0., 2., 0.]
    straight[:, 1] = [1., 0., 0.]
    straight[:, 3] = [-1., 0., 0.]
    common = {
        "parent": "right_hip", "hinge": "right_knee", "child": "right_ankle",
        "allowedExcessDegrees": 6.,
    }

    def evaluate(source_angles, points=straight):
        return temporal_gate_metrics_and_jacobian(
            points.reshape(frame_count, -1), rig,
            world_d3=csr_matrix((1, frame_count)), jerk_limit=1.,
            joint_shake_limits={}, relative_shake_limits={}, ankle_episodes=[],
            joint_angle_envelopes=[{
                **common, "name": "rightKnee",
                "sourceAnglesRadians": np.asarray(source_angles, dtype=float),
            }],
        )

    passing_names, passing_violations, passing_jacobian = evaluate(
        np.full(frame_count, np.pi),
    )
    assert passing_violations[passing_names.index(
        "sourceJointAngleEnvelopeUpper:rightKnee")] < 0.
    assert np.isfinite(passing_jacobian.data).all()

    folded = straight.copy()
    folded[:, 3] = [1., 0., 0.]
    folded_names, folded_violations, folded_jacobian = evaluate(
        np.zeros(frame_count), points=folded,
    )
    assert folded_violations[folded_names.index(
        "sourceJointAngleEnvelopeLower:rightKnee")] < 0.
    assert np.isfinite(folded_jacobian.data).all()

    active_names, active_violations, active_jacobian = evaluate(
        np.full(frame_count, np.deg2rad(80.)),
    )
    upper = active_names.index("sourceJointAngleEnvelopeUpper:rightKnee")
    assert active_violations[upper] > 0.
    assert active_jacobian.getrow(upper).nnz == 0
    candidate, evidence = inequality_gate_restoration_step(
        straight.reshape(frame_count, -1), rig,
        np.zeros((frame_count, len(rig.names)), dtype=bool),
        active_violations, active_jacobian,
        numerical_margin=0., max_point_shift_meters=.001,
    )
    assert evidence["applied"] is False
    np.testing.assert_array_equal(candidate, straight.reshape(frame_count, -1))


def test_inequality_gate_step_is_bounded_and_preserves_pin_tangent():
    rig = _LinearTrajectoryRig()
    frame_count = 5
    points = np.arange(frame_count * len(rig.names) * 3, dtype=float).reshape(
        frame_count, len(rig.names), 3,
    ) / 100.
    points[:, 0, 1] += .3 * np.sin(np.arange(frame_count))
    coordinates = points.reshape(frame_count, -1)
    pinned = np.zeros((frame_count, len(rig.names)), dtype=bool)
    pinned[:, 0] = True
    row0, row1, passing_row = (np.zeros(coordinates.size) for _ in range(3))
    # Two failing metrics share one free coordinate; the third has slack but
    # opposes part of the correction, so it must participate in the QP.
    row0[1 * rig.width + 3] = 1.
    row0[2 * rig.width + 7] = .4
    row1[1 * rig.width + 3] = .3
    row1[3 * rig.width + 8] = 1.
    passing_row[:] = -row0
    jacobian = csr_matrix(np.vstack([row0, row1, passing_row]))
    violations = np.asarray([.02, .015, -.5])

    candidate, evidence = inequality_gate_restoration_step(
        coordinates, rig, pinned, violations, jacobian,
        numerical_margin=.001, max_point_shift_meters=.001,
    )

    assert evidence["applied"]
    assert evidence["maximumPointShiftMeters"] <= .001 + 1e-12
    assert evidence["maximumKeyPinTangentResidual"] == 0.
    assert evidence["trustScale"] < 1.
    after = violations + jacobian @ (candidate.ravel() - coordinates.ravel())
    assert np.all(np.maximum(after, 0.) <= np.maximum(violations, 0.) + 1e-12)
    assert after[2] < 0.
    before_merit = np.sum(np.maximum(violations + .001, 0.) ** 2)
    after_merit = np.sum(np.maximum(after + .001, 0.) ** 2)
    assert after_merit < before_merit
    np.testing.assert_allclose(
        evidence["normalizedViolationsAfterLinearization"], after,
        rtol=0., atol=1e-12,
    )
    np.testing.assert_allclose(
        rig.decode(candidate)[pinned], rig.decode(coordinates)[pinned],
        rtol=0., atol=0.,
    )


class _RotatingPointRig:
    """One-coordinate nonlinear FK used to exercise the decoded trust cap."""

    width = 1
    names = ["rotating_point"]

    def decode(self, coordinates):
        values = np.asarray(coordinates, dtype=float).reshape(-1, 1)
        return np.stack((np.sin(values), np.cos(values), np.zeros_like(values)), axis=-1)

    def fk_jacobian(self, coordinates):
        values = np.asarray(coordinates, dtype=float).reshape(-1, 1)
        rows = np.zeros((values.shape[0] * 3, values.size), dtype=float)
        rows[0::3, :] = np.diag(np.cos(values[:, 0]))
        rows[1::3, :] = np.diag(-np.sin(values[:, 0]))
        return csr_matrix(rows)


def test_inequality_gate_step_backtracks_nonlinear_fk_to_trust_cap():
    rig = _RotatingPointRig()
    coordinates = np.asarray([[0.]])
    pinned = np.zeros((1, 1), dtype=bool)
    violations = np.asarray([1.])
    jacobian = csr_matrix([[1.]])
    trust_radius = .1

    # The old two ratio-rescales still left this exact rotation chord about
    # 3e-9m over the cap, which triggered a false failed restoration step.
    uncapped_angle = 1.
    initial_scale = trust_radius / (2. * np.sin(uncapped_angle / 2.))
    first_rescaled_angle = uncapped_angle * initial_scale
    first_shift = 2. * np.sin(first_rescaled_angle / 2.)
    second_scale = trust_radius / first_shift
    twice_rescaled_angle = first_rescaled_angle * second_scale
    twice_rescaled_shift = 2. * np.sin(twice_rescaled_angle / 2.)
    assert twice_rescaled_shift > trust_radius + 1e-12

    candidate, evidence = inequality_gate_restoration_step(
        coordinates, rig, pinned, violations, jacobian,
        numerical_margin=0., max_point_shift_meters=trust_radius,
    )

    assert evidence["applied"]
    assert evidence["decodedTrustBacktracks"] >= 1
    assert evidence["trustRadiusMeters"] == trust_radius
    assert evidence["uncappedMaximumPointShiftMeters"] == pytest.approx(
        2. * np.sin(uncapped_angle / 2.)
    )
    assert evidence["finalMaximumPointShiftMeters"] <= trust_radius + 1e-12
    assert np.linalg.norm(rig.decode(candidate) - rig.decode(coordinates)) <= trust_radius + 1e-12
    assert evidence["normalizedViolationsAfterLinearization"][0] < violations[0]


def test_tied_knee_envelope_protects_each_frame_without_losing_inward_directions():
    class KneeRig:
        names = ['pelvis', 'right_hip', 'right_knee', 'right_ankle']
        width = len(names) * 3

        def decode(self, coordinates):
            return np.asarray(coordinates).reshape(-1, len(self.names), 3)

        def fk_jacobian(self, coordinates):
            return csr_matrix(np.eye(np.asarray(coordinates).size))

    rig = KneeRig()
    points = np.zeros((4, len(rig.names), 3))
    points[:, 0] = [0., 2., 0.]
    points[:, 1] = [1., 0., 0.]
    theta = np.deg2rad([176., 176., 174., 172.])
    points[:, 3] = np.column_stack([np.cos(theta), np.sin(theta), np.zeros(4)])
    options = dict(world_d3=csr_matrix((1, 4)), jerk_limit=1.,
                   joint_shake_limits={}, relative_shake_limits={}, ankle_episodes=[],
                   joint_angle_envelopes=[dict(name='rightKnee', parent='right_hip',
                       hinge='right_knee', child='right_ankle',
                       sourceAnglesRadians=np.deg2rad([164., 166., 168., 170.]),
                       allowedExcessDegrees=6.)])
    coordinates = points.reshape(4, -1)
    names, violations, jacobian = temporal_gate_metrics_and_jacobian(coordinates, rig, **options)
    direction = np.zeros_like(points)
    tangent = np.column_stack([-np.sin(theta), np.cos(theta), np.zeros(4)])
    direction[0, 3] = tangent[0]
    direction[1, 3] = -2. * tangent[1]
    predicted = np.asarray(jacobian @ direction.ravel())
    # The old averaged row says this improves; frame zero actually leaves bounds.
    assert predicted[names.index('sourceJointAngleEnvelopeUpper:rightKnee')] < 0.
    assert predicted[names.index('sourceJointAngleFrameUpper:rightKnee:0')] > 0.
    inward = np.zeros_like(points)
    inward[:, 3] = -tangent
    active = np.abs(violations) < 1e-10
    assert np.all(np.asarray(jacobian @ inward.ravel())[active] <= 0.)
    candidate, evidence = inequality_gate_restoration_step(
        coordinates, rig, np.zeros(points.shape[:2], dtype=bool), violations, jacobian,
        numerical_margin=.001, max_point_shift_meters=.001)
    assert evidence['applied']
    _, after, _ = temporal_gate_metrics_and_jacobian(candidate, rig, **options)
    assert np.max(after) <= 0.
