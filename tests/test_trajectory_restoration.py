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


def test_source_knee_envelope_uses_two_extrema_rows_with_finite_difference_jacobian():
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

    assert names == [
        "jerk",
        "sourceJointAngleEnvelopeLower:rightKnee",
        "sourceJointAngleEnvelopeUpper:rightKnee",
    ]
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
