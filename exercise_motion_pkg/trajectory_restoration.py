"""Small tangent-space restoration steps for fixed-rig trajectories."""
from __future__ import annotations

import numpy as np
from scipy.optimize import minimize
from scipy.sparse import csr_matrix, vstack

MAX_FK_TRUST_BACKTRACKS = 32


def _angle_point_gradient(points, frame_index, first_joint, hinge_joint, third_joint, label):
    """Gradient of the hinge angle with respect to its three point slots."""
    u = points[frame_index, first_joint] - points[frame_index, hinge_joint]
    v = points[frame_index, third_joint] - points[frame_index, hinge_joint]
    u_length, v_length = np.linalg.norm(u), np.linalg.norm(v)
    if min(u_length, v_length) <= 1e-12:
        raise ValueError(f'degenerate hinge angle geometry: {label}')
    cosine = float(np.clip(np.dot(u, v) / (u_length * v_length), -1., 1.))
    sine = float(np.sqrt(max(1. - cosine * cosine, 0.)))
    if sine <= 1e-12:
        raise ValueError(f'undefined hinge angle gradient: {label}')
    gradient_u = -(v / (u_length * v_length)
                    - cosine * u / (u_length * u_length)) / sine
    gradient_v = -(u / (u_length * v_length)
                    - cosine * v / (v_length * v_length)) / sine
    return gradient_u, -(gradient_u + gradient_v), gradient_v


def temporal_gate_metrics_and_jacobian(
        coordinates, rig, *, world_d3, jerk_limit, joint_shake_limits,
        relative_shake_limits, ankle_episodes, settling_weights=None,
        settling_limit=None, fps=None, joint_angle_envelopes=None):
    """Return normalized temporal-gate violations and their rig-coordinate gradients.

    Upper-bound metrics are positive when over their supplied gate. Ankle
    episode metrics are positive when their source-range preservation is below
    the caller-supplied gate. Knee envelope metrics use the extrema of the
    supplied source angles expanded by the caller-supplied allowance. Limits
    and episode eligibility stay caller-owned.
    """
    from .physical_validation import angles

    coordinates = np.asarray(coordinates, dtype=float).reshape(-1, rig.width)
    if not np.isfinite(coordinates).all():
        raise ValueError('coordinates must be finite')
    points = np.asarray(rig.decode(coordinates), dtype=float)
    frame_count, joint_count = points.shape[:2]
    names = list(rig.names)
    if (points.shape != (frame_count, len(names), 3)
            or frame_count < 4 or not np.isfinite(points).all()):
        raise ValueError('rig must decode finite frame-by-joint 3D points')

    fk = rig.fk_jacobian(coordinates).tocsr()
    if fk.shape != (points.size, coordinates.size):
        raise ValueError('rig FK Jacobian has an invalid shape')
    metric_names, violations, gradient_rows = [], [], []

    def append_metric(name, violation, point_gradient):
        metric_names.append(name)
        violations.append(float(violation))
        gradient_rows.append(csr_matrix(
            np.asarray(point_gradient, dtype=float).reshape(1, -1)) @ fk)

    jerk_limit = float(jerk_limit)
    world_d3 = csr_matrix(world_d3)
    if world_d3.shape[1] != points.shape[0]:
        raise ValueError('world jerk difference matrix has an invalid shape')
    jerk_samples = np.asarray(world_d3 @ points.reshape(frame_count, -1), dtype=float)
    jerk_rms = float(np.sqrt(np.mean(jerk_samples ** 2)))
    if not np.isfinite(jerk_limit) or jerk_limit <= 0. or not np.isfinite(jerk_rms):
        raise ValueError('jerk gate must be finite and positive')
    jerk_gradient = np.asarray(world_d3.T @ jerk_samples).reshape(points.shape)
    jerk_gradient /= max(jerk_samples.size * jerk_rms, 1e-15) * jerk_limit
    append_metric('jerk', jerk_rms / jerk_limit - 1., jerk_gradient)

    d2 = csr_matrix(np.diff(np.eye(frame_count), n=2, axis=0))
    acceleration = np.asarray(
        d2 @ points.reshape(frame_count, -1), dtype=float,
    ).reshape(-1, joint_count, 3)
    acceleration_count = acceleration.shape[0] * 3

    def append_acceleration(name, samples, limit, point_slots):
        limit = float(limit)
        rms = float(np.sqrt(np.mean(np.asarray(samples, dtype=float) ** 2)))
        if not np.isfinite(limit) or limit <= 0. or not np.isfinite(rms):
            raise ValueError(f'{name} gate must be finite and positive')
        point_gradient = np.zeros_like(points)
        sample_gradient = np.asarray(
            d2.T @ np.asarray(samples, dtype=float).reshape(-1, 3),
        ) / max(acceleration_count * rms, 1e-15)
        for joint_index, sign in point_slots:
            point_gradient[:, joint_index] += sign * sample_gradient
        append_metric(name, rms / limit - 1., point_gradient / limit)

    for joint_name, limit in joint_shake_limits.items():
        if joint_name not in names:
            raise ValueError(f'unknown joint in shake limits: {joint_name}')
        joint_index = names.index(joint_name)
        append_acceleration(
            f'jointShake:{joint_name}', acceleration[:, joint_index], limit,
            ((joint_index, 1.),),
        )

    if 'pelvis' not in names:
        raise ValueError('rig names must include pelvis for relative shake')
    pelvis_index = names.index('pelvis')
    relative_acceleration = acceleration - acceleration[:, pelvis_index:pelvis_index + 1]
    for joint_name, limit in relative_shake_limits.items():
        if joint_name not in names:
            raise ValueError(f'unknown joint in relative shake limits: {joint_name}')
        joint_index = names.index(joint_name)
        samples = relative_acceleration[:, joint_index]
        slots = ((joint_index, 1.),) if joint_index == pelvis_index else (
            (joint_index, 1.), (pelvis_index, -1.),
        )
        append_acceleration(f'relativeJointShake:{joint_name}', samples, limit, slots)

    for episode in ankle_episodes:
        side = str(episode['side'])
        start, stop = int(episode['startFrame']), int(episode['stopFrame'])
        source_range = float(episode['sourceRangeRadians'])
        minimum_ratio = float(episode['minimumPreservedRatio'])
        label = str(episode['name'])
        if (start < 0 or stop > frame_count or stop - start < 2
                or not np.isfinite([source_range, minimum_ratio]).all()
                or source_range <= 0. or minimum_ratio <= 0.):
            raise ValueError(f'invalid source ankle episode: {label}')
        joint_names = (f'{side}_knee', f'{side}_ankle', f'{side}_foot')
        if any(name not in names for name in joint_names):
            raise ValueError(f'invalid ankle episode joints: {label}')
        knee, ankle, foot = (names.index(name) for name in joint_names)
        episode_points = points[start:stop]
        episode_angles = angles(
            episode_points[:, knee], episode_points[:, ankle], episode_points[:, foot],
        )
        maximum, minimum = float(np.max(episode_angles)), float(np.min(episode_angles))
        max_frames = np.flatnonzero(np.isclose(episode_angles, maximum, rtol=1e-10, atol=1e-10))
        min_frames = np.flatnonzero(np.isclose(episode_angles, minimum, rtol=1e-10, atol=1e-10))
        range_gradient = np.zeros_like(points)

        def add_angle_gradient(frame_index, sign):
            gradient_first, gradient_hinge, gradient_third = _angle_point_gradient(
                points, frame_index, knee, ankle, foot, label,
            )
            range_gradient[frame_index, knee] += sign * gradient_first
            range_gradient[frame_index, ankle] += sign * gradient_hinge
            range_gradient[frame_index, foot] += sign * gradient_third

        for local_index in max_frames:
            add_angle_gradient(start + int(local_index), 1. / len(max_frames))
        for local_index in min_frames:
            add_angle_gradient(start + int(local_index), -1. / len(min_frames))
        normalization = source_range * minimum_ratio
        append_metric(
            f'sourceFootContactArticulation:{label}',
            1. - (maximum - minimum) / normalization,
            -range_gradient / normalization,
        )

    # Selector-style source angle envelopes have one global lower and upper
    # bound per joint. Keep only each current trajectory extremum active; the
    # final validator still checks every frame. This protects both sides of
    # the envelope with two rows per hinge instead of a dense frame-by-frame
    # block in the restoration QP.
    for envelope in joint_angle_envelopes or ():
        label = str(envelope['name'])
        parent_name = str(envelope['parent'])
        hinge_name = str(envelope['hinge'])
        child_name = str(envelope['child'])
        source_angles = np.asarray(envelope['sourceAnglesRadians'], dtype=float).reshape(-1)
        allowed_excess_degrees = float(envelope['allowedExcessDegrees'])
        if any(name not in names for name in (parent_name, hinge_name, child_name)):
            raise ValueError(f'unknown joint in source angle envelope: {label}')
        parent, hinge, child = (names.index(name) for name in (parent_name, hinge_name, child_name))
        allowed_excess = np.deg2rad(allowed_excess_degrees)
        if (source_angles.shape != (frame_count,) or not np.isfinite(source_angles).all()
                or not np.isfinite(allowed_excess_degrees) or allowed_excess_degrees <= 0.
                or len({parent, hinge, child}) != 3):
            raise ValueError(f'invalid source angle envelope: {label}')

        observed_angles = angles(points[:, parent], points[:, hinge], points[:, child])
        lower_bound = float(np.min(source_angles)) - allowed_excess
        upper_bound = float(np.max(source_angles)) + allowed_excess
        minimum, maximum = float(np.min(observed_angles)), float(np.max(observed_angles))
        minimum_frames = np.flatnonzero(np.isclose(
            observed_angles, minimum, rtol=1e-10, atol=1e-10,
        ))
        maximum_frames = np.flatnonzero(np.isclose(
            observed_angles, maximum, rtol=1e-10, atol=1e-10,
        ))

        def angle_gradient(frame_index):
            try:
                gradient_first, gradient_hinge, gradient_third = _angle_point_gradient(
                    points, frame_index, parent, hinge, child, label,
                )
            except ValueError as error:
                if str(error).startswith('undefined hinge angle gradient:'):
                    # At a perfectly straight/folded hinge the angle has no
                    # unique first-order direction. Leave an active row with
                    # zero gradient so the QP returns no step for that row;
                    # the full validator still rejects the nonlinear failure.
                    return None
                raise
            gradient = np.zeros_like(points)
            gradient[frame_index, parent] += gradient_first
            gradient[frame_index, hinge] += gradient_hinge
            gradient[frame_index, child] += gradient_third
            return gradient

        upper_gradient = np.zeros_like(points)
        lower_gradient = np.zeros_like(points)
        # Hinge angles are intrinsically in [0, pi], so these bounds are
        # mathematically inactive and their derivatives are unnecessary.
        if lower_bound > 0.:
            for frame_index in minimum_frames:
                gradient = angle_gradient(int(frame_index))
                if gradient is not None:
                    lower_gradient -= gradient / len(minimum_frames)
        if upper_bound < np.pi:
            for frame_index in maximum_frames:
                gradient = angle_gradient(int(frame_index))
                if gradient is not None:
                    upper_gradient += gradient / len(maximum_frames)
        append_metric(
            f'sourceJointAngleEnvelopeLower:{label}',
            (lower_bound - minimum) / allowed_excess,
            lower_gradient / allowed_excess,
        )
        append_metric(
            f'sourceJointAngleEnvelopeUpper:{label}',
            (maximum - upper_bound) / allowed_excess,
            upper_gradient / allowed_excess,
        )

    settling_inputs = (settling_weights, settling_limit, fps)
    if any(value is not None for value in settling_inputs):
        if any(value is None for value in settling_inputs):
            raise ValueError('settling weights, limit, and fps must be supplied together')
        from .controlled_motion import body_relative_points, weighted_settling_speed
        from .sequence_stabilization import frame_basis
        from .temporal_quality import body_orientation_axes

        weights = np.asarray(settling_weights, dtype=float)
        settling_limit = float(settling_limit)
        fps = float(fps)
        if (weights.shape not in ((frame_count - 1, joint_count),
                                  (frame_count - 1, joint_count, 1))
                or not np.isfinite(weights).all() or np.any(weights < 0.)
                or not np.isfinite([settling_limit, fps]).all()
                or settling_limit <= 0. or fps <= 0.):
            raise ValueError('settling gate inputs must be finite and match trajectory dimensions')
        if weights.ndim == 2:
            weights = weights[:, :, None]
        if 'pelvis' not in names:
            raise ValueError('rig names must include pelvis for settling')

        relative = body_relative_points(points, names)
        settling_speed = weighted_settling_speed(points, names, fps, weights)
        denominator = max(float(np.sum(weights)) * 3., 1.)
        point_gradient = np.zeros_like(points)
        if settling_speed > 1e-15:
            interval_gradient = (
                np.diff(relative, axis=0) * fps ** 2 * weights ** 2
                / (denominator * settling_speed * settling_limit)
            )
            relative_gradient = np.zeros_like(relative)
            relative_gradient[:-1] -= interval_gradient
            relative_gradient[1:] += interval_gradient

            axes = body_orientation_axes(points, names)
            if axes.shape != (frame_count, 2, 3):
                raise ValueError('rig names must include both hips and neck for settling')
            basis = frame_basis(axes[:, 1], axes[:, 0])
            pelvis_index = names.index('pelvis')
            for joint_index in range(joint_count):
                if joint_index == pelvis_index:
                    continue
                point_gradient[:, joint_index] = np.einsum(
                    'fij,fj->fi', basis, relative_gradient[:, joint_index],
                )
            point_gradient[:, pelvis_index] -= np.einsum(
                'fij,fj->fi', basis,
                np.sum(relative_gradient, axis=1),
            )

            # The body frame is recomputed from hips, pelvis, and neck for every
            # pose. Replace those four point gradients with a batched central
            # difference through that exact frame construction; all other joint
            # derivatives above are the analytic point-to-body-relative map.
            epsilon = 1e-6
            for joint_name in ('left_hip', 'right_hip', 'pelvis', 'neck'):
                if joint_name not in names:
                    raise ValueError(f'rig names must include {joint_name} for settling')
                joint_index = names.index(joint_name)
                for axis_index in range(3):
                    plus, minus = points.copy(), points.copy()
                    plus[:, joint_index, axis_index] += epsilon
                    minus[:, joint_index, axis_index] -= epsilon
                    relative_plus = body_relative_points(plus, names)
                    relative_minus = body_relative_points(minus, names)
                    point_gradient[:, joint_index, axis_index] = np.sum(
                        relative_gradient * (relative_plus - relative_minus)
                        / (2. * epsilon), axis=(1, 2),
                    )

        append_metric(
            'settling', settling_speed / settling_limit - 1.,
            point_gradient,
        )

    return metric_names, np.asarray(violations), vstack(gradient_rows, format='csr')


def _project_coordinate_rows_to_key_pin_tangent(coordinates, rig, pinned, rows):
    """Project coordinate-space covectors into each frame's key-pin tangent."""
    coordinates = np.asarray(coordinates, dtype=float).reshape(-1, rig.width)
    pinned = np.asarray(pinned, dtype=bool)
    rows = csr_matrix(rows).toarray()
    points = np.asarray(rig.decode(coordinates), dtype=float)
    frame_count, joint_count = points.shape[:2]
    if pinned.shape != (frame_count, joint_count):
        raise ValueError("pinned mask must match trajectory frame and joint dimensions")
    if rows.ndim != 2 or rows.shape[1] != coordinates.size or not np.isfinite(rows).all():
        raise ValueError("coordinate rows must be a finite matrix matching the trajectory")
    fk = rig.fk_jacobian(coordinates).tocsr()
    if fk.shape != (points.size, coordinates.size):
        raise ValueError("rig FK Jacobian has an invalid shape")

    projected = rows.copy()
    maximum_pin_tangent_residual = 0.
    for frame_index in range(frame_count):
        columns = slice(frame_index * rig.width, (frame_index + 1) * rig.width)
        row_start = frame_index * joint_count * 3
        frame_jacobian = fk[row_start:row_start + joint_count * 3, columns].toarray()
        pin_indices = np.flatnonzero(pinned[frame_index])
        if not len(pin_indices):
            continue
        pin_rows = np.concatenate([
            np.arange(joint_index * 3, joint_index * 3 + 3)
            for joint_index in pin_indices
        ])
        pin_jacobian = frame_jacobian[pin_rows]
        frame_rows = projected[:, columns]
        multipliers = np.linalg.lstsq(pin_jacobian.T, frame_rows.T, rcond=1e-10)[0]
        frame_rows -= multipliers.T @ pin_jacobian
        projected[:, columns] = frame_rows
        maximum_pin_tangent_residual = max(
            maximum_pin_tangent_residual,
            float(np.max(np.abs(pin_jacobian @ frame_rows.T), initial=0.)),
        )
    return projected, maximum_pin_tangent_residual


def inequality_gate_restoration_step(
        coordinates, rig, pinned, normalized_violations, coordinate_jacobian, *,
        numerical_margin, max_point_shift_meters):
    """Propose a bounded minimum-norm step that improves temporal gate violations.

    The linearized inequalities include both failing and passing metrics, so the
    proposal protects existing slack while reducing failures. This is only a
    local proposal; nonlinear production validation remains authoritative.
    """
    coordinates = np.asarray(coordinates, dtype=float).reshape(-1, rig.width)
    violations = np.asarray(normalized_violations, dtype=float).reshape(-1)
    jacobian = csr_matrix(coordinate_jacobian)
    margin = float(numerical_margin)
    trust_radius = float(max_point_shift_meters)
    before_points = np.asarray(rig.decode(coordinates), dtype=float)
    empty = {
        "applied": False,
        "normalizedViolationsBefore": violations.tolist(),
        "normalizedViolationsAfterLinearization": violations.tolist(),
    }
    if (not np.isfinite(coordinates).all() or not np.isfinite(before_points).all()
            or not np.isfinite(violations).all()
            or jacobian.shape != (len(violations), coordinates.size)
            or not np.isfinite(jacobian.data).all() or not np.isfinite(margin)
            or margin < 0. or not np.isfinite(trust_radius) or trust_radius <= 0.):
        return coordinates.copy(), {**empty, "reason": "invalid_gate_restoration_inputs"}
    if not len(violations):
        return coordinates.copy(), {**empty, "reason": "no_gate_metrics"}

    projected, pin_residual = _project_coordinate_rows_to_key_pin_tangent(
        coordinates, rig, pinned, jacobian,
    )
    target = violations + margin
    gram = projected @ projected.T
    gram = (gram + gram.T) * .5
    if not np.isfinite(gram).all():
        return coordinates.copy(), {**empty, "reason": "nonfinite_projected_gram"}

    def dual_objective(multipliers):
        return .5 * float(multipliers @ gram @ multipliers) - float(target @ multipliers)

    def dual_gradient(multipliers):
        return gram @ multipliers - target

    result = minimize(
        dual_objective,
        np.zeros(len(violations), dtype=float),
        jac=dual_gradient,
        method="L-BFGS-B",
        bounds=[(0., None)] * len(violations),
        options={"maxiter": 200, "ftol": 1e-12, "gtol": 1e-9, "maxls": 30},
    )
    if (not result.success or not np.isfinite(result.x).all()
            or not np.isfinite(result.fun)):
        return coordinates.copy(), {
            **empty, "reason": "dual_qp_failed", "optimizerMessage": str(result.message),
            "optimizerIterations": int(result.nit),
        }
    delta = -(projected.T @ np.asarray(result.x, dtype=float))
    if not np.isfinite(delta).all():
        return coordinates.copy(), {**empty, "reason": "nonfinite_gate_step"}
    predicted = violations + projected @ delta
    violation_tolerance = 64. * np.finfo(float).eps * max(
        1., float(np.max(np.abs(violations), initial=0.)),
        float(np.max(np.abs(predicted), initial=0.)),
    )
    if np.any(np.maximum(predicted, 0.) > np.maximum(violations, 0.) + violation_tolerance):
        return coordinates.copy(), {
            **empty, "reason": "linearized_gate_regression",
            "maximumKeyPinTangentResidual": pin_residual,
            "optimizerIterations": int(result.nit),
        }

    before_merit = float(np.sum(np.maximum(target, 0.) ** 2))
    after_target = predicted + margin
    after_merit = float(np.sum(np.maximum(after_target, 0.) ** 2))
    merit_tolerance = 64. * np.finfo(float).eps * max(1., before_merit)
    if not np.isfinite(after_merit) or after_merit >= before_merit - merit_tolerance:
        return coordinates.copy(), {
            **empty, "reason": "no_strict_linearized_merit_improvement",
            "linearizedMeritBefore": before_merit,
            "linearizedMeritAfter": after_merit,
            "maximumKeyPinTangentResidual": pin_residual,
            "optimizerIterations": int(result.nit),
        }

    uncapped_candidate = (coordinates.ravel() + delta).reshape(coordinates.shape)
    uncapped_points = np.asarray(rig.decode(uncapped_candidate), dtype=float)
    uncapped_shift = float(np.max(
        np.linalg.norm(uncapped_points - before_points, axis=-1), initial=0.,
    ))
    if not np.isfinite(uncapped_points).all() or not np.isfinite(uncapped_shift):
        return coordinates.copy(), {
            **empty, "reason": "nonfinite_decoded_gate_step",
            "trustRadiusMeters": trust_radius,
            "uncappedMaximumPointShiftMeters": uncapped_shift,
            "finalMaximumPointShiftMeters": uncapped_shift,
            "decodedTrustBacktracks": 0,
        }

    # FK is nonlinear: scaling by radius / uncapped_shift can still leave the
    # decoded points just outside the physical cap. Backtrack the scalar in FK
    # space until the real decoded displacement satisfies the bound.
    scale = min(1., trust_radius / max(uncapped_shift, 1e-15))
    scaled_delta = delta * scale
    candidate = (coordinates.ravel() + scaled_delta).reshape(coordinates.shape)
    candidate_points = np.asarray(rig.decode(candidate), dtype=float)
    maximum_point_shift = float(np.max(
        np.linalg.norm(candidate_points - before_points, axis=-1), initial=0.,
    ))
    decoded_trust_backtracks = 0
    trust_tolerance = max(1e-12, 16. * np.finfo(float).eps * max(1., trust_radius))
    while (np.isfinite(maximum_point_shift)
           and maximum_point_shift > trust_radius + trust_tolerance
           and decoded_trust_backtracks < MAX_FK_TRUST_BACKTRACKS):
        scale *= .5
        scaled_delta = delta * scale
        candidate = (coordinates.ravel() + scaled_delta).reshape(coordinates.shape)
        candidate_points = np.asarray(rig.decode(candidate), dtype=float)
        maximum_point_shift = float(np.max(
            np.linalg.norm(candidate_points - before_points, axis=-1), initial=0.,
        ))
        decoded_trust_backtracks += 1
    # Use the actual scaled delta in the linearized gate check.
    scaled_prediction = violations + projected @ scaled_delta
    if (not np.isfinite(candidate_points).all() or not np.isfinite(scaled_prediction).all()
            or maximum_point_shift > trust_radius + trust_tolerance):
        return coordinates.copy(), {
            **empty, "reason": "point_trust_cap_failed",
            "trustRadiusMeters": trust_radius,
            "uncappedMaximumPointShiftMeters": uncapped_shift,
            "finalMaximumPointShiftMeters": maximum_point_shift,
            "decodedTrustBacktracks": decoded_trust_backtracks,
        }
    if np.any(np.maximum(scaled_prediction, 0.) > np.maximum(violations, 0.) + violation_tolerance):
        return coordinates.copy(), {**empty, "reason": "scaled_step_gate_regression"}
    scaled_merit = float(np.sum(np.maximum(scaled_prediction + margin, 0.) ** 2))
    if not np.isfinite(scaled_merit) or scaled_merit >= before_merit - merit_tolerance:
        return coordinates.copy(), {
            **empty, "reason": "scaled_step_no_merit_improvement",
            "linearizedMeritBefore": before_merit,
            "linearizedMeritAfter": scaled_merit,
        }
    return candidate, {
        "applied": True,
        "normalizedViolationsBefore": violations.tolist(),
        "normalizedViolationsAfterLinearization": scaled_prediction.tolist(),
        "linearizedMeritBefore": before_merit,
        "linearizedMeritAfter": scaled_merit,
        "maximumPointShiftMeters": maximum_point_shift,
        "maximumKeyPinTangentResidual": pin_residual,
        "optimizerIterations": int(result.nit),
        "optimizerMessage": str(result.message),
        "trustScale": scale,
        "trustRadiusMeters": trust_radius,
        "uncappedMaximumPointShiftMeters": uncapped_shift,
        "finalMaximumPointShiftMeters": maximum_point_shift,
        "decodedTrustBacktracks": decoded_trust_backtracks,
    }
