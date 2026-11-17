"""Small tangent-space restoration steps for fixed-rig trajectories."""
from __future__ import annotations

import numpy as np
from scipy.optimize import minimize
from scipy.sparse import csr_matrix, vstack

MAX_FK_TRUST_BACKTRACKS = 32


def representable_backtracking_trials(coordinates, proposal):
    """Halve a direction until it no longer changes the stored coordinates."""
    coordinates = np.asarray(coordinates, dtype=float)
    direction = np.asarray(proposal, dtype=float) - coordinates
    if not np.isfinite(direction).all():
        return
    alpha = 1.
    while alpha:
        trial = coordinates + alpha * direction
        if np.array_equal(trial, coordinates):
            return
        yield alpha, trial
        alpha *= .5


def dense_cyclic_root_continuity_rows(
        sampled_root, *, fps, scale, cyclic, sampled_root_jacobian=None):
    """Build validator-identical 30 Hz root-continuity inequalities.

    ``sampled_root`` is one dense playback traversal (not duplicated).  For a
    cyclic clip the validator repeats that traversal before taking second
    differences, so the seam rows are included here the same way.  An optional
    Jacobian maps flattened dense root xyz values to the caller's source
    coordinates; callers must supply the derivative of their full sampling,
    projection, and contact-retraction chain.
    """
    from scipy.sparse import csr_matrix

    root = np.asarray(sampled_root, dtype=float)
    rate = float(fps)
    body_scale = float(scale)
    if (root.ndim != 2 or root.shape[1] != 3 or len(root) < 2
            or not np.isfinite(root).all() or not np.isfinite(rate)
            or rate <= 0. or not np.isfinite(body_scale) or body_scale <= 0.):
        raise ValueError('dense root continuity requires finite Nx3 samples, fps, and scale')
    if type(cyclic) is not bool:
        raise ValueError('cyclic must be a bool')

    traversals = 2 if cyclic else 1
    repeated = np.concatenate([root] * traversals, axis=0)
    factor = (rate / 30.) ** 2
    limit = .05 * body_scale
    second = np.diff(repeated, n=2, axis=0)
    magnitudes = np.linalg.norm(second, axis=1) * factor
    violations = magnitudes / limit - 1.
    labels = [f'denseCyclicRootContinuity:{i + 1}' for i in range(len(violations))]

    jacobian = None
    if sampled_root_jacobian is not None:
        sample_jac = csr_matrix(sampled_root_jacobian)
        if sample_jac.shape[0] != root.size or not np.isfinite(sample_jac.data).all():
            raise ValueError('sampled root Jacobian must have 3 rows per dense sample')
        if cyclic:
            sample_jac = vstack([sample_jac, sample_jac], format='csr')
        rows = []
        for i, (vector, magnitude) in enumerate(zip(second, magnitudes)):
            if magnitude <= 1e-15:
                rows.append(csr_matrix((1, sample_jac.shape[1])))
                continue
            direction = (factor / (limit * np.linalg.norm(vector))) * vector
            rows.append(direction[0] * (sample_jac[3*(i+2)] - 2.*sample_jac[3*(i+1)] + sample_jac[3*i])
                        + direction[1] * (sample_jac[3*(i+2)+1] - 2.*sample_jac[3*(i+1)+1] + sample_jac[3*i+1])
                        + direction[2] * (sample_jac[3*(i+2)+2] - 2.*sample_jac[3*(i+1)+2] + sample_jac[3*i+2]))
        jacobian = vstack(rows, format='csr') if rows else csr_matrix((0, sample_jac.shape[1]))

    return labels, violations, jacobian, {
        'available': True,
        'passed': not bool(np.any(magnitudes > limit)),
        'policy': 'root_translation_continuity_v1',
        'sampleRateHz': rate,
        'cyclic': cyclic,
        'maximumSecondDifferenceMetersAt30Hz': float(magnitudes.max(initial=0.)),
        'limitMetersAt30Hz': float(limit),
        'frames': (np.flatnonzero(magnitudes > limit) + 1).tolist(),
    }


def sample_dense_root_for_playback(rig, *, subdivisions=4, cyclic):
    """Sample root xyz using the exact fixed-rig playback interpolation clock."""
    from .rig_playback import sample_rig_coordinates

    coordinates = np.asarray(rig.get('coordinates'), dtype=float)
    if coordinates.ndim != 2 or len(coordinates) < 2 or coordinates.shape[1] < 3:
        raise ValueError('fixed-rig coordinates are unavailable for dense root sampling')
    if isinstance(subdivisions, bool) or int(subdivisions) != subdivisions or subdivisions < 1:
        raise ValueError('subdivisions must be a positive integer')
    count = len(coordinates)
    cursors = (np.arange(count * int(subdivisions), dtype=float) / int(subdivisions)
               if cyclic else
               np.arange((count - 1) * int(subdivisions) + 1, dtype=float) / int(subdivisions))
    sampled = sample_rig_coordinates(rig, cursors, wrap=bool(cyclic))
    if not np.isfinite(sampled[:, :3]).all():
        raise ValueError('playback root samples are nonfinite')
    return cursors, sampled[:, :3]


def dense_root_sampling_jacobian(coordinates, cursors, *, interpolation, wrap):
    """Differentiate the playback root sampler w.r.t. keyframe root xyz slots."""
    from scipy.sparse import coo_matrix
    from .rig_interpolation import INTERPOLATION, LEGACY_INTERPOLATION, hermite_samples

    coordinates = np.asarray(coordinates, dtype=float)
    cursors = np.asarray(cursors, dtype=float)
    if (coordinates.ndim != 2 or coordinates.shape[1] < 3 or len(coordinates) < 2
            or cursors.ndim != 1 or not np.isfinite(coordinates).all()
            or not np.isfinite(cursors).all()):
        raise ValueError('root sampler Jacobian inputs are invalid')
    first = np.floor(np.mod(cursors, len(coordinates)) if wrap else
                     np.clip(cursors, 0., len(coordinates)-1)).astype(int)
    normalized = np.mod(cursors, len(coordinates)) if wrap else np.clip(cursors, 0., len(coordinates)-1)
    last = (first + 1) % len(coordinates) if wrap else np.minimum(first + 1, len(coordinates)-1)
    alpha = normalized - first
    hermite = interpolation in (INTERPOLATION, LEGACY_INTERPOLATION)
    limiter = interpolation == INTERPOLATION

    def sample(values):
        if hermite:
            return hermite_samples(values, first, last, alpha, wrap=wrap,
                                   smooth_limiter=limiter)
        return values[first] * (1. - alpha[:, None]) + values[last] * alpha[:, None]

    roots = coordinates[:, :3].copy()
    baseline = sample(roots)
    rows, columns, data = [], [], []
    epsilon = 1e-6
    for frame in range(len(roots)):
        for component in range(3):
            plus, minus = roots.copy(), roots.copy()
            plus[frame, component] += epsilon
            minus[frame, component] -= epsilon
            derivative = (sample(plus) - sample(minus)) / (2. * epsilon)
            for output_component in range(3):
                active = np.flatnonzero(np.abs(derivative[:, output_component]) > 1e-12)
                rows.extend((active * 3 + output_component).tolist())
                columns.extend([frame * 3 + component] * len(active))
                data.extend(derivative[active, output_component].tolist())
    return coo_matrix((data, (rows, columns)),
                      shape=(baseline.size, roots.size)).tocsr()


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


def _cosine_point_gradient(proximal, hinge, distal, label):
    a, b = proximal-hinge, distal-hinge
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if min(na, nb) <= 1e-12:
        raise ValueError(f'degenerate attachment geometry: {label}')
    cosine = float(np.dot(a,b)/(na*nb))
    da = b/(na*nb)-cosine*a/(na*na)
    db = a/(na*nb)-cosine*b/(nb*nb)
    return cosine, (da, -(da+db), db)


def _append_active_anatomy_metrics(points, names, append_metric, *,
                                   chest_attachment_limit_radians=None,
                                   preserve_torso_bend=False, anatomy_reference=None):
    """Preserve existing physical bounds while restoring temporal feasibility."""
    frame_count = len(points)
    required = ('spine3', 'neck', 'left_collar', 'right_collar')
    if chest_attachment_limit_radians is not None and all(name in names for name in required):
        limit = float(chest_attachment_limit_radians)
        if not np.isfinite(limit) or not 0. < limit < np.pi:
            raise ValueError('chest attachment bound must be a finite angle')
        spine, neck, left, right = [names.index(name) for name in required]
        cosine_limit = np.cos(limit)
        normalization = 1. - cosine_limit
        for frame in range(frame_count):
            cosine, derivatives = _cosine_point_gradient(
                points[frame, neck], points[frame, spine],
                (points[frame, left]+points[frame, right])*.5, 'chest')
            gradient = np.zeros_like(points)
            gradient[frame, neck] = -derivatives[0]/normalization
            gradient[frame, spine] = -derivatives[1]/normalization
            gradient[frame, left] = gradient[frame, right] = -.5*derivatives[2]/normalization
            append_metric(f'anatomyChestAttachment:neck:{frame}',
                          (cosine_limit-cosine)/normalization, gradient)

    required = ('left_hip', 'right_hip', 'spine1')
    if not preserve_torso_bend or not all(name in names for name in required):
        return
    from .physical_validation import torso_bend_floor
    reference = None if anatomy_reference is None else np.asarray(anatomy_reference, dtype=float)
    if reference is not None and reference.shape != points.shape:
        reference = None  # Same source-reference fallback as physical acceptance.
    hips = [names.index(name) for name in required[:2]]
    spine = names.index('spine1')
    proximal = points[:, hips].mean(axis=1)
    targets = [('spine1', ['neck']), ('shoulders', ['left_shoulder', 'right_shoulder'])]
    for label, distal_names in targets:
        if not all(name in names for name in distal_names):
            continue
        distal = [names.index(name) for name in distal_names]
        virtual = np.stack([proximal, points[:, spine], points[:, distal].mean(axis=1)], axis=1)
        basis = points if reference is None else reference
        floor = torso_bend_floor(basis[:, hips].mean(axis=1), basis[:, spine],
                                 basis[:, distal].mean(axis=1), source_conditioned=reference is not None)
        floor = np.broadcast_to(np.asarray(floor), (frame_count,))
        for frame in range(frame_count):
            if floor[frame] <= 0.:
                continue  # A nonpositive floor cannot constrain a hinge angle.
            cosine, derivatives = _cosine_point_gradient(*virtual[frame], label)
            cosine_floor = np.cos(floor[frame])
            normalization = 1.+cosine_floor
            gradient = np.zeros_like(points)
            for joint in hips:
                gradient[frame, joint] += derivatives[0]/(len(hips)*normalization)
            gradient[frame, spine] += derivatives[1]/normalization
            for joint in distal:
                gradient[frame, joint] += derivatives[2]/(len(distal)*normalization)
            append_metric(f'anatomyTorsoBend:{label}:{frame}',
                          (cosine-cosine_floor)/normalization, gradient)


def temporal_gate_metrics_and_jacobian(
        coordinates, rig, *, world_d3, jerk_limit, joint_shake_limits,
        relative_shake_limits, ankle_episodes, settling_weights=None,
        settling_limit=None, fps=None, joint_angle_envelopes=None,
        chest_attachment_limit_radians=None, preserve_torso_bend=False,
        anatomy_reference=None, coordinate_projection=None, projection_jacobian=None,
        canonical_pose_policy=None):
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
    projected_coordinates = (coordinates if coordinate_projection is None
                             else coordinate_projection(coordinates))
    points = np.asarray(rig.decode(projected_coordinates), dtype=float)
    frame_count, joint_count = points.shape[:2]
    names = list(rig.names)
    if (points.shape != (frame_count, len(names), 3)
            or frame_count < 4 or not np.isfinite(points).all()):
        raise ValueError('rig must decode finite frame-by-joint 3D points')

    fk = rig.fk_jacobian(projected_coordinates).tocsr()
    if projection_jacobian is not None:
        fk = fk @ projection_jacobian
    if fk.shape != (points.size, coordinates.size):
        raise ValueError('rig FK Jacobian has an invalid shape')
    metric_names, violations, gradient_rows = [], [], []

    def append_metric(name, violation, point_gradient):
        metric_names.append(name)
        violations.append(float(violation))
        gradient_rows.append(csr_matrix(
            np.asarray(point_gradient, dtype=float).reshape(1, -1)) @ fk)

    _append_active_anatomy_metrics(
        points, names, append_metric, chest_attachment_limit_radians=chest_attachment_limit_radians,
        preserve_torso_bend=preserve_torso_bend, anatomy_reference=anatomy_reference)

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
        # An averaged extrema covector is only a subgradient of max/min.
        # Protect each frame too: improving that average can otherwise move a
        # tied frame outside the same envelope and reject every nonlinear step.
        for frame_index, observed in enumerate(observed_angles):
            gradient = angle_gradient(frame_index)
            if gradient is None:
                gradient = np.zeros_like(points)
            append_metric(
                f'sourceJointAngleFrameLower:{label}:{frame_index}',
                (lower_bound - observed) / allowed_excess,
                -gradient / allowed_excess if lower_bound > 0. else np.zeros_like(points),
            )
            append_metric(
                f'sourceJointAngleFrameUpper:{label}:{frame_index}',
                (observed - upper_bound) / allowed_excess,
                gradient / allowed_excess if upper_bound < np.pi else np.zeros_like(points),
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

    if canonical_pose_policy is not None:
        canonical_names, canonical_violations, canonical_jacobian, _ = (
            canonical_pose_metrics_and_jacobian(
                coordinates, rig, canonical_pose_policy,
                projected_coordinates=projected_coordinates,
                coordinate_projection=coordinate_projection,
                projection_jacobian=projection_jacobian,
                compute_jacobian=bool(canonical_pose_policy.get('compute_jacobian', True))))
        metric_names.extend(canonical_names)
        violations.extend(canonical_violations.tolist())
        gradient_rows.extend(canonical_jacobian.getrow(index)
                             for index in range(canonical_jacobian.shape[0]))

    return metric_names, np.asarray(violations), vstack(gradient_rows, format='csr')


def canonical_pose_metrics_and_jacobian(coordinates, rig, policy, *, projected_coordinates=None,
                                        coordinate_projection=None, projection_jacobian=None,
                                        compute_jacobian=True):
    """Playback canonical inequalities with a stencil-colored active-set FD Jacobian.

    Values always cover the complete quarter-frame path. With a Jacobian, labels,
    violations, and Jacobian rows contain the selected active-set rows, mapped by
    ``policy['last_jacobian_diagnostics']['selectedRows']`` into the full
    ``full_by_sample`` array. Without a Jacobian, labels and violations cover all
    rows and the Jacobian is a matching all-zero matrix. Every evaluation refreshes
    pose-derived contact-track geometry while preserving activity and anchor IDs.
    """
    from .controlled_motion import canonical_bilateral_reference, KEYFRAME_CONTACT_LIMIT_METERS
    from .rig_playback import sample_rig
    from .contact_interpolation import refresh_contact_foot_tracks
    values=np.asarray(coordinates,dtype=float).reshape(-1,rig.width); count=len(values)
    projected_values=(np.asarray(projected_coordinates,dtype=float).reshape(-1,rig.width)
                      if projected_coordinates is not None else
                      values if coordinate_projection is None else np.asarray(coordinate_projection(values),dtype=float))
    if coordinate_projection is not None and np.max(np.abs(coordinate_projection(projected_values)-projected_values),initial=0.)>1e-9:
        raise ValueError('canonical restoration requires an idempotent local coordinate projection')
    config=policy.get('rig_payload'); execution=policy.get('execution'); names=list(policy.get('joint_names') or rig.names)
    if not isinstance(config,dict) or not isinstance(execution,dict) or names!=list(rig.names):
        raise ValueError('canonical pose policy requires the owning rig and execution contract')
    export_translation = np.asarray(policy.get('sampling_root_translation', np.zeros(3)), dtype=float)
    if export_translation.shape != (3,) or not np.isfinite(export_translation).all():
        raise ValueError('canonical restoration requires a finite sampling root translation')
    cyclic=bool(policy.get('cyclic')); subdivisions=int(policy.get('subdivisions',4))
    tolerance=float(policy.get('tolerance_meters',KEYFRAME_CONTACT_LIMIT_METERS))
    if subdivisions!=4 or tolerance!=KEYFRAME_CONTACT_LIMIT_METERS:
        raise ValueError('canonical restoration must use playback quarter-frames and approved tolerance')
    cursors=(np.arange(count*subdivisions,dtype=float)/subdivisions if cyclic else
             np.arange((count-1)*subdivisions+1,dtype=float)/subdivisions)
    def measure(raw, sample_indices, *, include_contact_tracks=True):
        local=dict(config)
        if not include_contact_tracks: local.pop('contactFootTracks',None)
        raw_values=np.asarray(raw,dtype=float).reshape(count,rig.width)
        sampling_values = raw_values.copy()
        sampling_values[:, :3] += export_translation
        local['coordinates']=sampling_values.tolist()
        if include_contact_tracks and isinstance(local.get('contactFootTracks'),dict):
            keypoints=np.asarray(rig.decode(sampling_values),dtype=float)
            local['contactFootTracks']=refresh_contact_foot_tracks(
                rig, keypoints, local['contactFootTracks'])
        points=sample_rig(local,cursors[np.asarray(sample_indices,dtype=int)],wrap=cyclic)
        target=canonical_bilateral_reference(points,names,execution,authoritative_sides=policy.get('authoritative_sides'))
        return np.linalg.norm(points-target,axis=-1)/tolerance-1.
    all_samples=np.arange(len(cursors),dtype=int)
    base=measure(projected_values,all_samples)
    base_flat=base.reshape(-1)
    if not compute_jacobian:
        zero=csr_matrix((base_flat.size,count*rig.width))
        all_names=[f'canonicalPose:{name}:sample{sample}' for sample in range(len(cursors)) for name in names]
        policy['last_jacobian_diagnostics']={'valuesOnly':True,'violatedRows':int(np.count_nonzero(base_flat>0.)),'finiteDifferenceCalls':0}
        return all_names,base_flat,zero,base

    safety_margin=float(policy.get('safety_margin',.2))
    if not np.isfinite(safety_margin) or safety_margin<0.:
        raise ValueError('canonical active-set safety margin must be finite and nonnegative')
    selected=np.flatnonzero(base_flat>-safety_margin)
    if not len(selected):
        policy['last_jacobian_diagnostics']={'violatedRows':0,'selectedRows':[],'activeSamples':0,'finiteDifferenceCalls':0,'safetyMargin':safety_margin}
        return [],np.empty(0),csr_matrix((0,count*rig.width)),base
    selected_samples=np.unique(selected//len(names))
    selected_by_sample={int(sample):np.flatnonzero(np.isin(np.arange(len(names)),selected[selected//len(names)==sample]%len(names))) for sample in selected_samples}
    first=np.floor(cursors).astype(int)
    stencil=first[selected_samples,None]+np.arange(-1,3)
    stencil=stencil%count if cyclic else np.clip(stencil,0,count-1)
    used_frames=np.unique(stencil)
    conflicts=[set() for _ in range(count)]
    for neighbors in stencil:
        for frame in neighbors: conflicts[int(frame)].update(map(int,neighbors))
    colors=np.full(count,-1,dtype=int)
    for frame in used_frames:
        used={colors[other] for other in conflicts[int(frame)] if colors[other]>=0}
        color=0
        while color in used: color+=1
        colors[int(frame)]=color
    active_rows=(base_flat[selected]>-np.inf)
    selected_sample_position={int(sample):i for i,sample in enumerate(selected_samples)}
    selected_matrix=base[:, :]
    lower_body={names.index(n) for n in names if n.endswith(('_knee','_ankle','_foot'))}
    selected_joint_ids=np.unique(selected%len(names))
    include_tracks=True
    if not np.intersect1d(selected_joint_ids,list(lower_body)).size:
        trackless=measure(projected_values,selected_samples,include_contact_tracks=False)
        full_selected=np.asarray([base[sample, selected_by_sample[int(sample)]] for sample in selected_samples],dtype=object)
        same=True
        for row,sample in enumerate(selected_samples):
            if np.max(np.abs(trackless[row,selected_by_sample[int(sample)]]-base[sample,selected_by_sample[int(sample)]]),initial=0.)>1e-9:
                same=False;break
        include_tracks=not same
    step=float(policy.get('finite_difference_step',2e-6))
    rows=[]; columns=[]; entries=[]; fd_calls=0
    for slot in range(rig.width):
        for color in np.unique(colors[used_frames]):
            frames=np.flatnonzero((colors==color))
            plus,minus=projected_values.copy(),projected_values.copy()
            plus[frames,slot]+=step; minus[frames,slot]-=step
            affected=np.asarray([sample for sample in selected_samples if np.any(colors[stencil[selected_sample_position[int(sample)]]]==color)],dtype=int)
            if not len(affected): continue
            pmetric=measure(plus,selected_samples,include_contact_tracks=include_tracks)
            mmetric=measure(minus,selected_samples,include_contact_tracks=include_tracks)
            diff=(pmetric-mmetric)/(2.*step); fd_calls+=2
            sample_lookup={int(sample):i for i,sample in enumerate(selected_samples)}
            for sample in selected_samples:
                sample=int(sample); local_i=sample_lookup[sample]; joints=selected_by_sample[sample]
                touches=np.flatnonzero(colors[stencil[selected_sample_position[sample]]]==color)
                if not len(touches):
                    if np.max(np.abs(diff[local_i,joints]),initial=0.)>2e-7:
                        raise ValueError('canonical derivative couples outside selected interpolation stencil')
                    continue
                source_frame=int(stencil[selected_sample_position[sample],touches[0]])
                for joint in joints:
                    value=float(diff[local_i,joint])
                    if abs(value)>1e-12:
                        rows.append(int(np.flatnonzero(selected==sample*len(names)+joint)[0]))
                        columns.append(source_frame*rig.width+slot); entries.append(value)
    jac=csr_matrix((entries,(rows,columns)),shape=(len(selected),count*rig.width))
    if projection_jacobian is not None: jac=jac@csr_matrix(projection_jacobian)
    labels=[f'canonicalPose:{names[index%len(names)]}:sample{index//len(names)}' for index in selected]
    policy['last_jacobian_diagnostics']={'violatedRows':int(np.count_nonzero(base_flat>0.)),'selectedRows':selected.tolist(),'activeSamples':int(len(selected_samples)),'finiteDifferenceCalls':fd_calls,'fdStep':step,'safetyMargin':safety_margin,'tracklessUpperRowsVerified':not include_tracks}
    return labels,base_flat[selected],jac,base


def _project_coordinate_rows_to_key_pin_tangent(coordinates, rig, pinned, rows, *,
                                               coordinate_projection=None, projection_jacobian=None,
                                               protected_jacobian=None):
    """Project coordinate-space covectors into each frame's key-pin tangent."""
    coordinates = np.asarray(coordinates, dtype=float).reshape(-1, rig.width)
    pinned = np.asarray(pinned, dtype=bool)
    rows = csr_matrix(rows).toarray()
    projected_coordinates = (coordinates if coordinate_projection is None
                             else coordinate_projection(coordinates))
    points = np.asarray(rig.decode(projected_coordinates), dtype=float)
    frame_count, joint_count = points.shape[:2]
    if pinned.shape != (frame_count, joint_count):
        raise ValueError("pinned mask must match trajectory frame and joint dimensions")
    if rows.ndim != 2 or rows.shape[1] != coordinates.size or not np.isfinite(rows).all():
        raise ValueError("coordinate rows must be a finite matrix matching the trajectory")
    fk = rig.fk_jacobian(projected_coordinates).tocsr()
    if projection_jacobian is not None:
        fk = fk @ projection_jacobian
    if fk.shape != (points.size, coordinates.size):
        raise ValueError("rig FK Jacobian has an invalid shape")

    projected = rows.copy()
    protected = None if protected_jacobian is None else csr_matrix(protected_jacobian)
    if protected is not None and (protected.shape[1] != coordinates.size
                                  or not np.isfinite(protected.data).all()):
        raise ValueError('protected equality Jacobian must match source coordinates')
    maximum_pin_tangent_residual = 0.
    for frame_index in range(frame_count):
        columns = slice(frame_index * rig.width, (frame_index + 1) * rig.width)
        row_start = frame_index * joint_count * 3
        frame_jacobian = fk[row_start:row_start + joint_count * 3, columns].toarray()
        pin_indices = np.flatnonzero(pinned[frame_index])
        if len(pin_indices):
            pin_rows = np.concatenate([
                np.arange(joint_index * 3, joint_index * 3 + 3)
                for joint_index in pin_indices
            ])
            pin_jacobian = frame_jacobian[pin_rows]
        else:
            pin_jacobian = np.zeros((0, rig.width), dtype=float)
        if protected is not None:
            extra = protected[:, columns].toarray()
            extra = extra[np.any(np.abs(extra) > 1e-12, axis=1)]
            if len(extra):
                pin_jacobian = np.vstack((pin_jacobian, extra))
        if not len(pin_jacobian):
            continue
        frame_rows = projected[:, columns]
        multipliers = np.linalg.lstsq(pin_jacobian.T, frame_rows.T, rcond=1e-10)[0]
        frame_rows -= multipliers.T @ pin_jacobian
        projected[:, columns] = frame_rows
        maximum_pin_tangent_residual = max(
            maximum_pin_tangent_residual,
            float(np.max(np.abs(pin_jacobian @ frame_rows.T), initial=0.)),
        )
    return projected, maximum_pin_tangent_residual


def _inequality_gate_restoration_linear_step(
        coordinates, rig, pinned, normalized_violations, coordinate_jacobian, *,
        numerical_margin, max_point_shift_meters, coordinate_projection=None,
        projection_jacobian=None, protected_jacobian=None):
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
    def decode(values):
        return rig.decode(values if coordinate_projection is None else coordinate_projection(values))
    before_points = np.asarray(decode(coordinates), dtype=float)
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
        coordinates, rig, pinned, jacobian, coordinate_projection=coordinate_projection,
        projection_jacobian=projection_jacobian, protected_jacobian=protected_jacobian,
    )
    # Scale each inequality by its row norm for the dual solve. This preserves
    # the primal feasible set while improving conditioning when coordinate
    # covectors have very different magnitudes. Keep an unscaled copy for all
    # primal feasibility, merit, and returned-step checks below.
    projected_unscaled = np.asarray(projected, dtype=float)
    row_norms = np.linalg.norm(projected_unscaled, axis=1)
    row_scale = 1. / np.maximum(row_norms, 1e-12)
    projected = projected_unscaled * row_scale[:, None]
    target = (violations + margin) * row_scale
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
        # Small dual objectives can satisfy relative cost convergence before
        # the protected primal inequalities are feasible.
        options={"maxiter": 200, "ftol": 1e-15, "gtol": 1e-12, "maxls": 30},
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
    predicted = violations + projected_unscaled @ delta
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

    before_merit = float(np.sum(np.maximum(violations + margin, 0.) ** 2))
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
    uncapped_points = np.asarray(decode(uncapped_candidate), dtype=float)
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
    candidate_points = np.asarray(decode(candidate), dtype=float)
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
        candidate_points = np.asarray(decode(candidate), dtype=float)
        maximum_point_shift = float(np.max(
            np.linalg.norm(candidate_points - before_points, axis=-1), initial=0.,
        ))
        decoded_trust_backtracks += 1
    # Use the actual scaled delta in the linearized gate check.
    scaled_prediction = violations + projected_unscaled @ scaled_delta
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
        "_uncappedCandidate": uncapped_candidate,
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


def inequality_gate_restoration_step(
        coordinates, rig, pinned, normalized_violations, coordinate_jacobian, *,
        numerical_margin, max_point_shift_meters, coordinate_projection=None,
        projection_jacobian=None, protected_jacobian=None, vector_norm_models=(),
        max_vector_norm_cuts=8):
    """Solve the existing linear gate QP, optionally exchanging norm-ball cuts.

    Each vector model contains a normalized residual vector at ``coordinates``,
    its scalar-row index, and callbacks mapping a coordinate delta to residual
    delta and a residual direction to one sparse tangent row. If exchange does
    not find a feasible affine norm step, preserve the original bounded QP
    proposal; nonlinear validation remains authoritative.
    """
    base_coordinates = np.asarray(coordinates, dtype=float).reshape(-1, rig.width)
    base_violations = np.asarray(normalized_violations, dtype=float).reshape(-1)
    base_jacobian = csr_matrix(coordinate_jacobian)
    legacy_candidate, legacy_evidence = _inequality_gate_restoration_linear_step(
        base_coordinates, rig, pinned, base_violations, base_jacobian,
        numerical_margin=numerical_margin,
        max_point_shift_meters=max_point_shift_meters,
        coordinate_projection=coordinate_projection,
        projection_jacobian=projection_jacobian,
        protected_jacobian=protected_jacobian)
    models = tuple(vector_norm_models or ())
    if not models:
        legacy_evidence.pop("_uncappedCandidate", None)
        return legacy_candidate, legacy_evidence

    fallback_evidence = {**legacy_evidence, "vectorNormModels": []}
    fallback_evidence.pop("_uncappedCandidate", None)
    if not legacy_evidence.get("applied"):
        fallback_evidence["vectorNormModels"] = [
            {"name": str(model.get("name", "vectorNorm")), "status": "legacy_fallback",
             "cutHistory": [{
                 "iteration": 0, "targetRadius": max(0., 1. - float(numerical_margin)),
                 "qpStatus": "not_applied",
                 "qpReason": str(legacy_evidence.get("reason", "unknown")),
                 "optimizerIterations": legacy_evidence.get("optimizerIterations"),
             }]}
            for model in models]
        return legacy_candidate, fallback_evidence

    cuts = []
    current_candidate, current_evidence = legacy_candidate, legacy_evidence
    current_uncapped = np.asarray(
        legacy_evidence.pop("_uncappedCandidate", legacy_candidate), dtype=float)
    max_cuts = max(0, int(max_vector_norm_cuts))
    for model in models:
        name = str(model.get("name", "vectorNorm"))
        residual = np.asarray(model.get("residual"), dtype=float).reshape(-1)
        row_index = int(model.get("row_index", -1))
        apply_delta = model.get("apply_delta")
        tangent_row = model.get("tangent_row")
        if (not len(residual) or not np.isfinite(residual).all()
                or row_index < 0 or row_index >= len(base_violations)
                or not callable(apply_delta) or not callable(tangent_row)):
            return legacy_candidate, {
                **fallback_evidence,
                "vectorNormModels": [{"name": name, "status": "invalid_model"}],
            }
        scalar_violation = float(base_violations[row_index])
        if abs((float(np.linalg.norm(residual)) - 1.) - scalar_violation) > 1e-8:
            return legacy_candidate, {
                **fallback_evidence,
                "vectorNormModels": [{"name": name, "status": "scalar_vector_mismatch"}],
            }
        if scalar_violation <= 0.:
            current_evidence.setdefault("vectorNormModels", []).append(
                {"name": name, "status": "already_feasible", "cuts": 0})
            continue

        status = "cut_cap_fallback"
        used_cuts = 0
        target_radius = max(0., 1. - float(numerical_margin))
        cut_history = []
        base_norm = float(np.linalg.norm(residual))
        model_merit_before = float(np.sum(np.maximum(
            base_violations + float(numerical_margin), 0.) ** 2))
        model_merit_tolerance = 64. * np.finfo(float).eps * max(1., model_merit_before)
        best_progress = None
        best_feasible = None
        for _ in range(max_cuts + 1):
            # Exchange cuts against the full QP step before the physical point
            # trust cap. The capped candidate is returned unchanged for the
            # existing production prefilter and final validation.
            delta = (current_uncapped - base_coordinates).reshape(-1)
            predicted_residual = residual + np.asarray(apply_delta(delta), dtype=float).reshape(-1)
            if predicted_residual.shape != residual.shape or not np.isfinite(predicted_residual).all():
                status = "invalid_prediction_fallback"
                cut_history.append({
                    "iteration": used_cuts, "targetRadius": target_radius,
                    "qpStatus": "applied" if current_evidence.get("applied") else "not_applied",
                    "optimizerIterations": current_evidence.get("optimizerIterations"),
                    "predictedNormStatus": "invalid",
                })
                break
            predicted_norm = float(np.linalg.norm(predicted_residual))
            capped_delta = (current_candidate - base_coordinates).reshape(-1)
            capped_residual = residual + np.asarray(apply_delta(capped_delta), dtype=float).reshape(-1)
            capped_norm = float(np.linalg.norm(capped_residual))
            original_predicted_rows = base_violations + np.asarray(
                base_jacobian @ capped_delta, dtype=float).reshape(-1)
            predicted_rows = original_predicted_rows.copy()
            predicted_rows[row_index] = capped_norm - 1.
            row_tolerance = 64. * np.finfo(float).eps * max(
                1., float(np.max(np.abs(base_violations), initial=0.)),
                float(np.max(np.abs(predicted_rows), initial=0.)))
            no_component_regression = not np.any(
                np.maximum(predicted_rows, 0.)
                > np.maximum(base_violations, 0.) + row_tolerance)
            model_merit = float(np.sum(np.maximum(
                predicted_rows + float(numerical_margin), 0.) ** 2))
            norm_tolerance = 64. * np.finfo(float).eps * max(1., base_norm, capped_norm)
            strict_model_progress = (
                no_component_regression
                and capped_norm < base_norm - norm_tolerance
                and model_merit < model_merit_before - model_merit_tolerance)
            cut_history.append({
                "iteration": used_cuts, "uncappedPredictedNorm": predicted_norm,
                "cappedPredictedNorm": capped_norm,
                "modelMerit": model_merit,
                "targetRadius": target_radius,
                "qpStatus": "applied" if current_evidence.get("applied") else "not_applied",
                "optimizerIterations": current_evidence.get("optimizerIterations"),
            })
            if strict_model_progress:
                record = {
                    "candidate": current_candidate.copy(),
                    "evidence": dict(current_evidence),
                    "originalPredictedRows": original_predicted_rows.copy(),
                    "cuts": used_cuts,
                    "uncappedNorm": predicted_norm,
                    "cappedNorm": capped_norm,
                    "merit": model_merit,
                    "history": list(cut_history),
                    "lineScale": 1.,
                }
                if capped_norm <= target_radius + 1e-10:
                    if best_feasible is None or model_merit < best_feasible["merit"]:
                        best_feasible = record
                elif best_progress is None or model_merit < best_progress["merit"]:
                    best_progress = record

            # The norm-cut QP can exhaust its cut budget while the capped
            # endpoint still has a worse norm than the base. A scalar line
            # minimizer along that already-bounded direction may nevertheless
            # give a useful, fully row-checked step. Keep this refinement
            # limited to the current single-model production case; callers
            # with multiple vector models retain the existing exchange path.
            if len(models) == 1:
                norm_delta = np.asarray(apply_delta(capped_delta), dtype=float).reshape(-1)
                denominator = float(norm_delta @ norm_delta)
                if np.isfinite(denominator) and denominator > 1e-30:
                    line_scale = float(np.clip(-(residual @ norm_delta) / denominator, 0., 1.))
                    if 0. < line_scale < 1.:
                        line_delta = line_scale * capped_delta
                        line_residual = residual + line_scale * norm_delta
                        line_norm = float(np.linalg.norm(line_residual))
                        line_rows = base_violations + np.asarray(
                            base_jacobian @ line_delta, dtype=float).reshape(-1)
                        original_line_rows = line_rows.copy()
                        line_rows[row_index] = line_norm - 1.
                        line_row_tolerance = 64. * np.finfo(float).eps * max(
                            1., float(np.max(np.abs(base_violations), initial=0.)),
                            float(np.max(np.abs(line_rows), initial=0.)))
                        line_no_regression = not np.any(
                            np.maximum(line_rows, 0.)
                            > np.maximum(base_violations, 0.) + line_row_tolerance)
                        line_merit = float(np.sum(np.maximum(
                            line_rows + float(numerical_margin), 0.) ** 2))
                        line_norm_tolerance = 64. * np.finfo(float).eps * max(
                            1., base_norm, line_norm)
                        line_merit_progress = (
                            line_no_regression
                            and line_norm < base_norm - line_norm_tolerance
                            and line_merit < model_merit_before - model_merit_tolerance)
                        if line_merit_progress:
                            line_candidate = (base_coordinates.ravel() + line_delta).reshape(
                                base_coordinates.shape)
                            try:
                                decoded_candidate = (line_candidate if coordinate_projection is None
                                                     else np.asarray(
                                                         coordinate_projection(line_candidate),
                                                         dtype=float))
                                line_points = np.asarray(rig.decode(decoded_candidate), dtype=float)
                                base_decoded = (base_coordinates
                                                if coordinate_projection is None
                                                else np.asarray(
                                                    coordinate_projection(base_coordinates),
                                                    dtype=float))
                                base_points = np.asarray(rig.decode(base_decoded), dtype=float)
                                line_point_shift = float(np.max(np.linalg.norm(
                                    line_points - base_points, axis=-1), initial=0.))
                            except (ValueError, TypeError, KeyError, FloatingPointError):
                                line_point_shift = float("inf")
                            point_cap_tolerance = max(
                                1e-12, 16. * np.finfo(float).eps
                                * max(1., float(max_point_shift_meters)))
                            if (np.isfinite(line_point_shift)
                                    and line_point_shift <= float(max_point_shift_meters)
                                    + point_cap_tolerance):
                                record = {
                                    "candidate": line_candidate,
                                    "evidence": dict(current_evidence),
                                    "originalPredictedRows": original_line_rows,
                                    "cuts": used_cuts,
                                    "uncappedNorm": predicted_norm,
                                    "cappedNorm": line_norm,
                                    "merit": line_merit,
                                    "history": list(cut_history),
                                    "lineScale": line_scale,
                                }
                                record["evidence"]["maximumPointShiftMeters"] = line_point_shift
                                record["evidence"]["finalMaximumPointShiftMeters"] = line_point_shift
                                if line_norm <= target_radius + 1e-10:
                                    if best_feasible is None or line_merit < best_feasible["merit"]:
                                        best_feasible = record
                                elif best_progress is None or line_merit < best_progress["merit"]:
                                    best_progress = record
            if predicted_norm <= target_radius + 1e-10:
                status = "affine_norm_feasible"
                break
            if used_cuts >= max_cuts or predicted_norm <= 1e-15:
                status = "cut_cap_fallback"
                break
            direction = predicted_residual / predicted_norm
            try:
                row = csr_matrix(tangent_row(direction))
            except (TypeError, ValueError):
                status = "invalid_tangent_fallback"
                break
            if row.shape != (1, base_coordinates.size) or not np.isfinite(row.data).all():
                status = "invalid_tangent_fallback"
                break
            cut_violation = float(direction @ residual) - 1.
            cuts.append((cut_violation, row))
            used_cuts += 1
            augmented_violations = np.concatenate(
                (base_violations, np.asarray([cut[0] for cut in cuts], dtype=float)))
            augmented_jacobian = vstack(
                (base_jacobian, *(cut[1] for cut in cuts)), format="csr")
            next_candidate, next_evidence = _inequality_gate_restoration_linear_step(
                base_coordinates, rig, pinned, augmented_violations, augmented_jacobian,
                numerical_margin=numerical_margin,
                max_point_shift_meters=max_point_shift_meters,
                coordinate_projection=coordinate_projection,
                projection_jacobian=projection_jacobian,
                protected_jacobian=protected_jacobian)
            if not next_evidence.get("applied"):
                status = "linear_qp_fallback"
                cut_history.append({
                    "iteration": used_cuts,
                    "targetRadius": target_radius,
                    "qpStatus": "not_applied",
                    "qpReason": str(next_evidence.get("reason", "unknown")),
                    "optimizerIterations": next_evidence.get("optimizerIterations"),
                })
                break
            current_candidate, current_evidence = next_candidate, next_evidence
            current_uncapped = np.asarray(
                current_evidence.pop("_uncappedCandidate", next_candidate), dtype=float)
        else:
            status = "cut_cap_fallback"

        selected = best_feasible or best_progress
        if selected is None:
            fallback_evidence["vectorNormModels"].append(
                {"name": name, "status": status, "cuts": used_cuts,
                 "modelGateFeasible": False, "cutHistory": cut_history})
            return legacy_candidate, fallback_evidence
        selected_status = "affine_norm_feasible" if best_feasible is not None else "affine_norm_progress"
        selected_evidence = selected["evidence"]
        selected_evidence.pop("_uncappedCandidate", None)
        exchange_merit_before = selected_evidence.pop("linearizedMeritBefore", None)
        exchange_merit_after = selected_evidence.pop("linearizedMeritAfter", None)
        selected_rows = np.asarray(selected["originalPredictedRows"], dtype=float).reshape(-1)
        selected_evidence["normalizedViolationsBefore"] = base_violations.tolist()
        selected_evidence["normalizedViolationsAfterLinearization"] = selected_rows.tolist()
        selected_evidence["linearizedMeritBefore"] = float(np.sum(np.maximum(
            base_violations + float(numerical_margin), 0.) ** 2))
        selected_evidence["linearizedMeritAfter"] = float(np.sum(np.maximum(
            selected_rows + float(numerical_margin), 0.) ** 2))
        selected_evidence["normExchangeQpMeritBefore"] = exchange_merit_before
        selected_evidence["normExchangeQpMeritAfter"] = exchange_merit_after
        selected_evidence["cappedNormModelMeritBefore"] = model_merit_before
        selected_evidence["cappedNormModelMeritAfter"] = selected["merit"]
        selected_evidence.setdefault("vectorNormModels", []).append({
            "name": name, "status": selected_status,
            "modelGateFeasible": selected["cappedNorm"] <= target_radius + 1e-10,
            "uncappedModelGateFeasible": selected["uncappedNorm"] <= target_radius + 1e-10,
            "cuts": selected["cuts"], "cutHistory": selected["history"],
            "uncappedPredictedNorm": selected["uncappedNorm"],
            "cappedPredictedNorm": selected["cappedNorm"],
            "lineScale": selected["lineScale"],
            "lineMinimized": selected["lineScale"] < 1.,
            "targetRadius": target_radius,
            "modelMeritBefore": model_merit_before,
            "modelMeritAfter": selected["merit"],
        })
        current_candidate, current_evidence = selected["candidate"], selected_evidence

    current_evidence.pop("_uncappedCandidate", None)
    return current_candidate, current_evidence


def jerk_vector_linearization(
        coordinates, rig, world_d3, jerk_limit, *,
        coordinate_projection=None, projection_jacobian=None):
    """Build a matrix-free normalized affine model of the full jerk vector."""
    coordinates = np.asarray(coordinates, dtype=float).reshape(-1, rig.width)
    projected = (coordinates if coordinate_projection is None
                 else np.asarray(coordinate_projection(coordinates), dtype=float))
    points = np.asarray(rig.decode(projected), dtype=float)
    difference = csr_matrix(world_d3)
    if (points.ndim != 3 or difference.shape[1] != len(points)
            or not np.isfinite(points).all()):
        raise ValueError("jerk vector model has invalid decoded points or difference matrix")
    limit = float(jerk_limit)
    if not np.isfinite(limit) or limit <= 0.:
        raise ValueError("jerk vector limit must be finite and positive")
    scale = float(np.sqrt(difference.shape[0] * points.shape[1] * points.shape[2]) * limit)
    if not np.isfinite(scale) or scale <= 0.:
        raise ValueError("jerk vector normalization is invalid")
    point_width = points.shape[1] * points.shape[2]
    residual = np.asarray(
        difference @ points.reshape(len(points), point_width), dtype=float).reshape(-1) / scale
    fk = rig.fk_jacobian(projected).tocsr()
    if projection_jacobian is not None:
        fk = fk @ csr_matrix(projection_jacobian)
    if fk.shape != (points.size, coordinates.size):
        raise ValueError("jerk vector FK Jacobian has an invalid shape")

    def apply_delta(delta):
        delta = np.asarray(delta, dtype=float).reshape(-1)
        if delta.size != coordinates.size:
            raise ValueError("jerk vector delta has an invalid shape")
        point_delta = np.asarray(fk @ delta, dtype=float).reshape(len(points), point_width)
        return np.asarray(difference @ point_delta, dtype=float).reshape(-1) / scale

    def tangent_row(direction):
        direction = np.asarray(direction, dtype=float).reshape(-1)
        if direction.size != residual.size or not np.isfinite(direction).all():
            raise ValueError("jerk tangent direction has an invalid shape")
        point_covector = np.asarray(
            difference.T @ direction.reshape(difference.shape[0], point_width), dtype=float,
        ).reshape(-1) / scale
        return csr_matrix(point_covector.reshape(1, -1)) @ fk

    return {"name": "jerk", "residual": residual,
            "apply_delta": apply_delta, "tangent_row": tangent_row}
