"""Bounded common-root and closed-chain repair for source-observed heel motion."""
from __future__ import annotations

from time import monotonic

import numpy as np
from scipy.optimize import least_squares, minimize
from scipy.sparse import lil_matrix
from scipy.spatial.transform import Rotation

from .contact_interpolation import build_contact_foot_tracks
from .foot_kinematics import _source_knee_poles, _transport_knee_poles
from .physical_validation import ARTICULATIONS, angles


_ROOT_LIMIT_METERS = 0.12
_INTERIOR_MARGIN_DEGREES = 0.5
_EPS = 1e-9


def _unit(vector):
    vector = np.asarray(vector, dtype=float)
    return vector / np.maximum(np.linalg.norm(vector, axis=-1, keepdims=True), _EPS)


def _leg_specs(names, points, reference, desired_directions, pinned):
    index = {name: i for i, name in enumerate(names)}
    specs = []
    for side_index, side in enumerate(('left', 'right')):
        required = [f'{side}_{part}' for part in ('hip', 'knee', 'ankle', 'foot')]
        if any(name not in index for name in required):
            continue
        hip_i, knee_i, ankle_i, toe_i = [index[name] for name in required]
        source_knee = angles(reference[:, hip_i], reference[:, knee_i], reference[:, ankle_i])
        source_ankle = angles(reference[:, knee_i], reference[:, ankle_i], reference[:, toe_i])
        poles = _source_knee_poles(
            points[:, hip_i], points[:, knee_i], points[:, ankle_i])
        if np.any(np.linalg.norm(poles, axis=1) <= 1e-5):
            return None
        ankle_pin, toe_pin = pinned[:, ankle_i], pinned[:, toe_i]
        toe_only = toe_pin & ~ankle_pin
        ankle_only = ankle_pin & ~toe_pin
        free = ~ankle_pin & ~toe_pin
        foot_length = float(np.linalg.norm(points[0, toe_i] - points[0, ankle_i]))
        ankle_target = points[:, ankle_i].copy()
        toe_target = points[:, toe_i].copy()
        ankle_target[toe_only] = (points[toe_only, toe_i]
                                  - foot_length * desired_directions[toe_only, side_index])
        toe_target[ankle_only] = (points[ankle_only, ankle_i]
                                  + foot_length * desired_directions[ankle_only, side_index])
        # Contact authority determines only which endpoint is pinned. Between
        # observed support intervals, retain the existing world-space toe path
        # and carry the smoothed measured pitch through the ambiguous gap.
        ankle_target[free] = (points[free, toe_i]
                              - foot_length * desired_directions[free, side_index])
        specs.append({
            'side': side,
            'indices': (hip_i, knee_i, ankle_i, toe_i),
            'hip': points[:, hip_i], 'knee': points[:, knee_i],
            'ankle': points[:, ankle_i], 'toe': points[:, toe_i],
            'targetAnkle': ankle_target, 'targetToe': toe_target,
            'ankleFollowsRoot': np.zeros_like(free),
            'toeFollowsRoot': np.zeros_like(free),
            'thigh': np.linalg.norm(points[:, knee_i] - points[:, hip_i], axis=1),
            'shin': np.linalg.norm(points[:, ankle_i] - points[:, knee_i], axis=1),
            'pole': _unit(poles),
            'sourceAxis': _unit(points[:, ankle_i] - points[:, hip_i]),
            'referenceKneeAngle': source_knee,
            'referenceAnkleAngle': source_ankle,
            'kneeTolerance': np.deg2rad(next(float(row[4]) for row in ARTICULATIONS
                                             if row[0] == f'{side}_knee')),
            'ankleTolerance': np.deg2rad(next(float(row[4]) for row in ARTICULATIONS
                                              if row[0] == f'{side}_ankle')),
        })
    return specs or None


def _frame_state(specs, frame, translation):
    margins, target_knees = [], []
    unreachable = False
    for spec in specs:
        if 'activeContact' in spec and not spec['activeContact'][frame]:
            # A free/unknown frame does not own a support IK target. Carry its
            # source knee with the root track, leaving its articulation intact.
            margins.extend((np.pi, np.pi))
            target_knees.append(spec['knee'][frame] + translation)
            continue
        hip = spec['hip'][frame] + translation
        ankle = spec['targetAnkle'][frame] + (
            translation if spec['ankleFollowsRoot'][frame] else 0.)
        toe = spec['targetToe'][frame] + (
            translation if spec['toeFollowsRoot'][frame] else 0.)
        reach = ankle - hip
        distance = float(np.linalg.norm(reach))
        thigh, shin = float(spec['thigh'][frame]), float(spec['shin'][frame])
        inner_reach = abs(thigh - shin)
        outer_reach = thigh + shin
        leg_unreachable = distance < inner_reach or distance > outer_reach
        unreachable |= leg_unreachable
        reach_margin = (min(distance - inner_reach, outer_reach - distance)
                        / max(thigh, shin, _EPS) * np.pi)
        if distance > _EPS:
            axis = reach / distance
        else:
            # At a collapsed reach the norm has no useful finite-difference
            # direction. Use the source limb axis to keep the signed reach
            # margin informative to the root optimizer.
            axis = _unit(spec['sourceAxis'][frame])
        solve_distance = float(np.clip(distance, inner_reach, outer_reach))
        solve_distance = max(solve_distance, _EPS)
        along = (thigh * thigh - shin * shin + solve_distance * solve_distance) / (
            2. * solve_distance)
        height_squared = thigh * thigh - along * along
        height_squared = max(height_squared, 0.)
        carried = _transport_knee_poles(
            spec['pole'][frame:frame + 1], spec['sourceAxis'][frame:frame + 1],
            axis[None, :])[0]
        bend = _unit(carried - axis * np.dot(carried, axis))
        knee = hip + axis * along + bend * np.sqrt(height_squared)
        knee_angle = float(angles(hip, knee, ankle))
        ankle_angle = float(angles(knee, ankle, toe))
        interior = np.deg2rad(_INTERIOR_MARGIN_DEGREES)
        knee_margin = (spec['kneeTolerance'] - interior
                       - abs(knee_angle - float(spec['referenceKneeAngle'][frame])))
        ankle_margin = (spec['ankleTolerance'] - interior
                        - abs(ankle_angle - float(spec['referenceAnkleAngle'][frame])))
        # Keep the established two articulation constraints per leg. Outside
        # the reach annulus both stay strictly infeasible and inherit the
        # signed reach gradient, even when the nearest-pose articulation is
        # already slightly outside its angular limit. This replaces the old
        # constant -pi plateau without changing reachable-pose thresholds.
        if leg_unreachable:
            reach_deficit = -reach_margin
            knee_margin = min(knee_margin, 0.) - reach_deficit
            ankle_margin = min(ankle_margin, 0.) - reach_deficit
        margins.extend((knee_margin, ankle_margin))
        target_knees.append(knee)
    return np.asarray(margins), (None if unreachable else np.asarray(target_knees))


def _root_track(specs, frame_count, deadline):
    """Find per-frame feasible offsets for the coupled solver's initial seed."""
    bounds = [(-_ROOT_LIMIT_METERS, _ROOT_LIMIT_METERS)] * 3
    translations = np.zeros((frame_count, 3), dtype=float)
    for frame in range(frame_count):
        if monotonic() >= deadline:
            raise TimeoutError('contact heel root feasibility exceeded its deadline')
        at_zero, _ = _frame_state(specs, frame, np.zeros(3))
        if np.min(at_zero) >= -1e-8:
            continue

        def margins(value):
            if monotonic() >= deadline:
                raise TimeoutError('contact heel root feasibility exceeded its deadline')
            return _frame_state(specs, frame, value)[0]

        seeds = [np.zeros(3)]
        if frame:
            seeds.append(translations[frame - 1].copy())
        candidates = []
        for seed in seeds:
            def objective(value):
                if monotonic() >= deadline:
                    raise TimeoutError('contact heel root feasibility exceeded its deadline')
                return float(value @ value)

            result = minimize(
                objective, seed,
                jac=lambda value: 2. * value, method='SLSQP', bounds=bounds,
                constraints=[{'type': 'ineq', 'fun': margins}],
                options={'maxiter': 35, 'ftol': 1e-9, 'disp': False})
            trial = np.asarray(result.x, dtype=float)
            trial_margins = margins(trial)
            candidates.append((float(np.min(trial_margins)), float(trial @ trial), trial))
            if np.min(trial_margins) >= -1e-7:
                break
        feasible = [row for row in candidates if row[0] >= -1e-7]
        if not feasible:
            return None, {'feasible': False, 'frame': frame,
                          'bestMinimumMarginDegrees': float(np.rad2deg(max(row[0] for row in candidates)))}
        translations[frame] = min(feasible, key=lambda row: row[1])[2]

    margins = np.asarray([_frame_state(specs, frame, translations[frame])[0]
                          for frame in range(frame_count)])
    if not np.isfinite(margins).all() or np.min(margins) < -1e-7:
        return None, {'feasible': False, 'reason': 'smoothed_root_track_not_feasible',
                      'minimumMarginDegrees': float(np.rad2deg(np.nanmin(margins)))}
    return translations, {
        'feasible': True,
        'maxMagnitudeMeters': float(np.max(np.linalg.norm(translations, axis=1), initial=0.)),
        'rmsMagnitudeMeters': float(np.sqrt(np.mean(np.sum(translations ** 2, axis=1)))),
        'maxStepMeters': float(np.max(np.linalg.norm(np.diff(translations, axis=0), axis=1), initial=0.)),
        'maxSecondDifferenceMeters': float(np.max(
            np.linalg.norm(np.diff(translations, n=2, axis=0), axis=1), initial=0.)),
        'minimumInteriorMarginDegrees': float(np.rad2deg(np.min(margins))),
    }


def _rotation_matrices(rig, coordinates, frame):
    matrices = {}
    rotations = Rotation.from_rotvec(coordinates[frame, 3:].reshape(-1, 3)).as_matrix()
    for joint in rig.order:
        parent = rig.parents[joint]
        local = rotations[(rig.slots[joint] - 3) // 3] if joint in rig.slots else np.eye(3)
        matrices[joint] = local if parent < 0 else matrices[parent] @ local
    return matrices


def _aim_rotation(current, offset, desired_world_direction):
    source = _unit(current @ offset)
    target = _unit(desired_world_direction)
    cross = np.cross(source, target)
    sine = float(np.linalg.norm(cross))
    cosine = float(np.clip(np.dot(source, target), -1., 1.))
    if sine <= 1e-10:
        if cosine >= 0.:
            return current
        axis = np.cross(source, [1., 0., 0.])
        if np.linalg.norm(axis) <= 1e-8:
            axis = np.cross(source, [0., 0., 1.])
        swing = Rotation.from_rotvec(_unit(axis) * np.pi)
    else:
        swing = Rotation.from_rotvec(cross / sine * np.arctan2(sine, cosine))
    return (swing * Rotation.from_matrix(current)).as_matrix()


def _aim_rotation_track(current, offset, desired_world_directions):
    """Apply the existing minimal swing to a track while preserving each twist."""
    source = _unit(current @ np.asarray(offset, dtype=float))
    target = _unit(desired_world_directions)
    cross = np.cross(source, target)
    sine = np.linalg.norm(cross, axis=1)
    cosine = np.clip(np.sum(source * target, axis=1), -1., 1.)
    rotvec = np.zeros_like(source)
    regular = sine > 1e-10
    rotvec[regular] = (cross[regular] / sine[regular, None]
                       * np.arctan2(sine[regular], cosine[regular])[:, None])
    opposite = ~regular & (cosine < 0.)
    if np.any(opposite):
        axes = np.cross(source[opposite], [1., 0., 0.])
        fallback = np.linalg.norm(axes, axis=1) <= 1e-8
        axes[fallback] = np.cross(source[opposite][fallback], [0., 0., 1.])
        rotvec[opposite] = _unit(axes) * np.pi
    return (Rotation.from_rotvec(rotvec) * Rotation.from_matrix(current)).as_matrix()


def _encode_targets(rig, coordinates, target_points, moving_joints):
    encoded = np.asarray(coordinates, dtype=float).copy()
    moving_joints = sorted(set(moving_joints), key=rig.order.index)
    frame_count = len(encoded)
    active_index = {joint: index for index, joint in enumerate(rig.active)}
    active_rotations = Rotation.from_rotvec(
        encoded[:, 3:].reshape(frame_count, len(rig.active), 3).reshape(-1, 3)
    ).as_matrix().reshape(frame_count, len(rig.active), 3, 3)
    world_matrices = np.empty((frame_count, len(rig.names), 3, 3), dtype=float)
    moving = set(moving_joints)
    identity = np.broadcast_to(np.eye(3), (frame_count, 3, 3))
    for joint in rig.order:
        parent = rig.parents[joint]
        if joint in active_index:
            local = active_rotations[:, active_index[joint]]
        else:
            local = identity
        if joint in moving:
            if joint not in rig.slots or parent < 0:
                return None
            desired = target_points[:, joint] - target_points[:, parent]
            if np.max(np.abs(np.linalg.norm(desired, axis=1)
                             - np.linalg.norm(rig.offsets[joint])), initial=0.) > 1e-5:
                return None
            parent_matrix = world_matrices[:, parent]
            desired_local = np.einsum('fji,fj->fi', parent_matrix, desired)
            local = _aim_rotation_track(local, rig.offsets[joint], desired_local)
            active_rotations[:, active_index[joint]] = local
        world_matrices[:, joint] = (local if parent < 0 else
                                    world_matrices[:, parent] @ local)
    for joint in moving_joints:
        active_slot = active_index[joint]
        coordinate_slot = rig.slots[joint]
        encoded[:, coordinate_slot:coordinate_slot + 3] = Rotation.from_matrix(
            active_rotations[:, active_slot]
        ).as_rotvec()
    decoded = rig.decode(encoded)
    if not np.isfinite(decoded).all():
        return None
    difference = np.abs(decoded[:, moving_joints] - target_points[:, moving_joints])
    if np.max(difference, initial=0.) > 1e-5:
        return None
    return encoded


def _encode_root_adjusted_pose(rig, coordinates, specs, offsets):
    """Re-solve and encode the closed chains for a trial common-root track."""
    coordinates = np.asarray(coordinates, dtype=float)
    offsets = np.asarray(offsets, dtype=float)
    shifted = coordinates.copy()
    shifted[:, :3] += offsets
    shifted_points = rig.decode(shifted)
    targets = shifted_points.copy()
    moving = sorted({joint for spec in specs
                     for joint in (spec['indices'][1], spec['indices'][2], spec['indices'][3])})
    margins_by_frame = np.empty((len(shifted_points), 2 * len(specs)), dtype=float)
    for frame in range(len(shifted_points)):
        margins, knees = _frame_state(specs, frame, offsets[frame])
        if knees is None:
            return None, None, None
        margins_by_frame[frame] = margins
        translation = offsets[frame]
        for spec, knee in zip(specs, knees):
            if 'activeContact' in spec and not spec['activeContact'][frame]:
                continue
            hip_i, knee_i, ankle_i, toe_i = spec['indices']
            targets[frame, hip_i] = spec['hip'][frame] + translation
            targets[frame, knee_i] = knee
            targets[frame, ankle_i] = (spec['targetAnkle'][frame]
                + translation * spec['ankleFollowsRoot'][frame])
            targets[frame, toe_i] = (spec['targetToe'][frame]
                + translation * spec['toeFollowsRoot'][frame])
    encoded = _encode_targets(rig, shifted, targets, moving)
    return encoded, targets, margins_by_frame


def _quarter_angle_deltas(rig, coordinates, tracks, reference, fps, cursors,
                          *, preserve_keys=True):
    from .controlled_motion import _sampling_payload
    from .contact_interpolation import sample_contact_foot_tracks
    from .rig_playback import sample_rig

    sample_payload = _sampling_payload(rig, coordinates)
    if preserve_keys:
        sample_payload['contactFootTracks'] = tracks
        sampled = sample_rig(sample_payload, cursors, wrap=False)
    else:
        sample_payload.pop('contactFootTracks', None)
        raw = sample_rig(sample_payload, cursors, wrap=False)
        sampled = sample_contact_foot_tracks(
            {**sample_payload, 'contactFootTracks': tracks}, cursors, raw,
            wrap=False, preserve_keys=False)
    count = len(coordinates)
    first = np.floor(cursors).astype(int)
    last = np.minimum(first + 1, count - 1)
    alpha = cursors - first
    source = reference[first] * (1. - alpha[:, None, None]) + reference[last] * alpha[:, None, None]
    names = list(rig.names)
    index = {name: i for i, name in enumerate(names)}
    labels = []
    deltas = []
    limits = []
    for label, parent, hinge, child, tolerance_degrees in ARTICULATIONS:
        if not label.endswith(('_knee', '_ankle')) or any(
                name not in index for name in (parent, hinge, child)):
            continue
        joints = [index[name] for name in (parent, hinge, child)]
        deltas.append(angles(*(sampled[:, joint] for joint in joints))
                      - angles(*(source[:, joint] for joint in joints)))
        limits.append(np.deg2rad(float(tolerance_degrees) - _INTERIOR_MARGIN_DEGREES))
        labels.append(label)
    return np.column_stack(deltas), np.asarray(limits), labels


def _root_invariant_source_context(constraint, specs):
    """Remove source-fit rows that cannot change under this root-only solve."""
    fixed_sides = set()
    fixed_indices = set()
    for spec in specs:
        ankle_follows = np.asarray(spec['ankleFollowsRoot'], dtype=bool)
        toe_follows = np.asarray(spec['toeFollowsRoot'], dtype=bool)
        if np.any(ankle_follows) or np.any(toe_follows):
            continue
        fixed_sides.add(spec['side'])
        fixed_indices.update((spec['indices'][2], spec['indices'][3]))

    context = dict(constraint)
    excluded = {
        'pointObservations': 0,
        'rayObservations': 0,
        'materialHeelObservations': 0,
        'materialHeelEvents': 0,
    }
    for field in ('observations', 'sourceFootPointObservations'):
        original = list(context.get(field) or [])
        context[field] = [row for row in original
                          if int(row['jointIndex']) not in fixed_indices]
        excluded['pointObservations'] += len(original) - len(context[field])

    original_rays = list(context.get('sourceFootRayObservations') or [])
    context['sourceFootRayObservations'] = [
        row for row in original_rays
        if not ({int(row['ankleJointIndex']), int(row['footJointIndex'])}
                <= fixed_indices)
    ]
    excluded['rayObservations'] = len(original_rays) - len(context['sourceFootRayObservations'])

    original_heels = list(context.get('sourceFootHeelImageObservations') or [])
    context['sourceFootHeelImageObservations'] = [
        row for row in original_heels if row.get('motionSide') not in fixed_sides]
    excluded['materialHeelObservations'] = (
        len(original_heels) - len(context['sourceFootHeelImageObservations']))

    original_events = list(context.get('sourceFootHeelTrajectoryEvents') or [])
    context['sourceFootHeelTrajectoryEvents'] = [
        row for row in original_events if row.get('motionSide') not in fixed_sides]
    excluded['materialHeelEvents'] = (
        len(original_events) - len(context['sourceFootHeelTrajectoryEvents']))
    return context, excluded


def _coupled_root_fit(
    rig, coordinates, tracks, specs, reference, fps, deadline,
    *, pinned, seed_offsets, source_constraint, jerk_reference, shake_reference,
    jerk_limit, body_scale,
):
    """Solve the complete root-offset trajectory with contact and temporal rows."""
    from .controlled_motion import (
        _source_projection_fit_rows,
        root_relative_acceleration,
    )

    coordinates = np.asarray(coordinates, dtype=float)
    reference = np.asarray(reference, dtype=float)
    jerk_reference = np.asarray(jerk_reference, dtype=float)
    shake_reference = np.asarray(shake_reference, dtype=float)
    seed_offsets = np.asarray(seed_offsets, dtype=float)
    count, joint_count = len(coordinates), len(rig.names)
    cursors = np.arange((count - 1) * 4 + 1, dtype=float) / 4.
    baseline, limits, labels = _quarter_angle_deltas(
        rig, coordinates, tracks, reference, fps, cursors)
    report = {
        'attempted': True,
        'source': 'production_quarter_sampler_coupled_root_xyz_trajectory',
        'sampleCount': len(cursors),
        'jointLabels': labels,
        'maximumInitialExcessDegrees': float(np.rad2deg(np.max(
            np.maximum(np.abs(baseline) - limits[None, :], 0.), initial=0.))),
        'seedMaxStepMeters': float(np.max(
            np.linalg.norm(np.diff(seed_offsets, axis=0), axis=1), initial=0.)),
    }
    if (jerk_reference.shape != (count, joint_count, 3)
            or shake_reference.shape != (count, joint_count, 3)
            or not np.isfinite(jerk_reference).all()
            or not np.isfinite(shake_reference).all()
            or not np.isfinite(jerk_limit) or jerk_limit <= 0.
            or not np.isfinite(body_scale) or body_scale <= 0.):
        return None, {**report, 'applied': False, 'reason': 'temporal_reference_unavailable'}

    shake_before = root_relative_acceleration(shake_reference, rig.names)
    shake_limits = np.maximum(shake_before * 1.2, .003 * (30. / fps) ** 2)
    root_d2_limit = .05 * body_scale * (30. / fps) ** 2
    key_rows = 2 * len(specs) * count
    quarter_rows = len(cursors) * len(labels)
    offset_rows = 3 * count
    root_d2_rows = 3 * max(0, count - 2)
    jerk_rows = max(0, count - 3) * joint_count * 3
    shake_rows = max(0, count - 2) * joint_count * 3
    source_context, invariant_source_rows = _root_invariant_source_context(
        source_constraint, specs)
    source_event_count = len(source_constraint.get('sourceFootHeelTrajectoryEvents') or [])
    source_context['sourceFootHeelTrajectoryEvents'] = []
    source_point_count = len((source_context.get('observations') or [])
                             + (source_context.get('sourceFootPointObservations') or []))
    source_ray_count = len(source_context.get('sourceFootRayObservations') or [])
    source_heel_count = len(source_context.get('sourceFootHeelImageObservations') or [])
    source_rows = 2 * source_point_count + source_ray_count + 2 * source_heel_count
    row_count = (quarter_rows + key_rows + offset_rows + root_d2_rows
                 + jerk_rows + shake_rows + source_rows)
    sparsity = lil_matrix((row_count, 3 * count), dtype=np.int8)
    row = 0
    for sample, cursor in enumerate(cursors):
        start = int(np.floor(cursor))
        for frame in range(max(0, start - 1), min(count, start + 3)):
            sparsity[row:row + len(labels), 3 * frame:3 * frame + 3] = 1
        row += len(labels)
    for frame in range(count):
        sparsity[row:row + 2 * len(specs), 3 * frame:3 * frame + 3] = 1
        row += 2 * len(specs)
    for frame in range(count):
        sparsity[row:row + 3, 3 * frame:3 * frame + 3] = 1
        row += 3
    for frame in range(count - 2):
        for touched in (frame, frame + 1, frame + 2):
            sparsity[row:row + 3, 3 * touched:3 * touched + 3] = 1
        row += 3
    for frame in range(count - 3):
        for touched in range(frame, frame + 4):
            sparsity[row:row + joint_count * 3, 3 * touched:3 * touched + 3] = 1
        row += joint_count * 3
    for frame in range(count - 2):
        for touched in (frame, frame + 1, frame + 2):
            sparsity[row:row + joint_count * 3, 3 * touched:3 * touched + 3] = 1
        row += joint_count * 3

    # Source image rows are local in fit time. Aggregate heel-event amplitude
    # rows are intentionally left to the exact final source gate.
    for observation in ((source_context.get('observations') or [])
                        + (source_context.get('sourceFootPointObservations') or [])):
        for frame in {int(observation['leftFrame']), int(observation['rightFrame'])}:
            sparsity[row:row + 2, 3 * frame:3 * frame + 3] = 1
        row += 2
    for observation in source_context.get('sourceFootRayObservations') or []:
        for frame in {int(observation['leftFrame']), int(observation['rightFrame'])}:
            sparsity[row, 3 * frame:3 * frame + 3] = 1
        row += 1
    for observation in source_context.get('sourceFootHeelImageObservations') or []:
        for frame in {int(observation['leftFrame']), int(observation['rightFrame'])}:
            sparsity[row:row + 2, 3 * frame:3 * frame + 3] = 1
        row += 2
    if row != row_count:
        return None, {**report, 'applied': False, 'reason': 'residual_sparsity_mismatch'}
    sparsity = sparsity.tocsr()
    angle_scale = np.deg2rad(.25)
    root_i = int(rig.root)
    failed_residual = np.full(row_count, 1e3, dtype=float)
    def residual(flat):
        if monotonic() >= deadline:
            raise TimeoutError('coupled root trajectory solve exceeded its deadline')
        offsets = np.asarray(flat, dtype=float).reshape(count, 3)
        encoded, targets, key_margins = _encode_root_adjusted_pose(
            rig, coordinates, specs, offsets)
        if encoded is None:
            return failed_residual.copy()
        points = rig.decode(encoded)
        delta, _quarter_limits, _quarter_labels = _quarter_angle_deltas(
            rig, encoded, tracks, reference, fps, cursors)
        key_excess = np.maximum(-key_margins, 0.) / angle_scale
        quarter_excess = np.maximum(np.abs(delta) - limits[None, :], 0.) / angle_scale
        root_d2 = np.diff(points[:, root_i], n=2, axis=0)
        root_norm = np.linalg.norm(root_d2, axis=1, keepdims=True)
        root_d2_excess = np.maximum(root_norm - root_d2_limit, 0.) * root_d2 / np.maximum(root_norm, _EPS)
        jerk_delta = np.diff(points, n=3, axis=0) - np.diff(jerk_reference, n=3, axis=0)
        point_relative = points - points[:, root_i:root_i + 1]
        shake_relative = shake_reference - shake_reference[:, root_i:root_i + 1]
        shake_delta = np.diff(point_relative, n=2, axis=0) - np.diff(shake_relative, n=2, axis=0)
        shake_delta /= np.maximum(shake_limits[None, :, None], 1e-9)
        source_rows_now = _source_projection_fit_rows(points, source_context)
        source_rows_now = source_rows_now[:source_rows]
        if source_rows_now.shape != (source_rows,):
            return failed_residual.copy()
        return np.r_[quarter_excess.ravel(), key_excess.ravel(),
                     (offsets / .02).ravel(),
                     (10. * root_d2_excess.ravel() / max(root_d2_limit, 1e-9)),
                     (jerk_delta / jerk_limit).ravel(), shake_delta.ravel(), source_rows_now]

    try:
        fit = least_squares(
            residual, seed_offsets.ravel(), jac_sparsity=sparsity,
            method='trf', tr_solver='lsmr', max_nfev=10,
            bounds=(-np.full(3 * count, _ROOT_LIMIT_METERS),
                    np.full(3 * count, _ROOT_LIMIT_METERS)),
            x_scale=.02, ftol=1e-5, xtol=1e-5, gtol=1e-5,
        )
    except (ValueError, FloatingPointError, KeyError, TypeError) as error:
        return None, {**report, 'applied': False,
                      'reason': 'bounded_solver_failed', 'detail': type(error).__name__}
    if monotonic() >= deadline:
        raise TimeoutError('coupled root trajectory solve exceeded its deadline')
    offsets = np.asarray(fit.x, dtype=float).reshape(count, 3)
    encoded, targets, key_margins = _encode_root_adjusted_pose(
        rig, coordinates, specs, offsets)
    if encoded is None:
        return None, {**report, 'applied': False, 'reason': 'key_chain_reencode_failed'}
    points = rig.decode(encoded)
    try:
        final_tracks = build_contact_foot_tracks(rig, points, pinned)
    except (TypeError, ValueError, FloatingPointError):
        return None, {**report, 'applied': False, 'reason': 'contact_track_rebuild_failed'}
    deltas, limits, labels = _quarter_angle_deltas(
        rig, encoded, final_tracks, reference, fps, cursors)
    interior_excess = np.maximum(np.abs(deltas) - limits[None, :], 0.)
    key_excess = np.maximum(-key_margins, 0.)
    hard_limits = np.asarray([
        np.deg2rad(next(float(row[4]) + .25 for row in ARTICULATIONS
                        if row[0] == label)) for label in labels], dtype=float)
    hard_excess = np.maximum(np.abs(deltas) - hard_limits[None, :], 0.)
    hard_allowance = np.deg2rad(_INTERIOR_MARGIN_DEGREES + .25)
    key_hard_excess = np.maximum(key_excess - hard_allowance, 0.)
    root_quality = np.linalg.norm(np.diff(points[:, root_i], n=2, axis=0), axis=1) * (fps / 30.) ** 2
    jerk_after = float(np.sqrt(np.mean(np.diff(points, n=3, axis=0) ** 2)))
    shake_after = root_relative_acceleration(points, rig.names)
    passed = bool(np.max(hard_excess, initial=0.) <= 1e-7
                  and np.max(key_hard_excess, initial=0.) <= 1e-7
                  and np.max(root_quality, initial=0.) <= .05 * body_scale + 1e-7
                  and np.isfinite(points).all())
    report.update(
        applied=passed,
        reason=None if passed else 'coupled_trajectory_hard_geometry_failed',
        optimizerSuccess=bool(fit.success), optimizerStatus=int(fit.status),
        optimizerMessage=str(fit.message), evaluations=int(fit.nfev),
        maximumFinalInteriorExcessDegrees=float(np.rad2deg(np.max(interior_excess, initial=0.))),
        maximumFinalHardExcessDegrees=float(np.rad2deg(np.max(hard_excess, initial=0.))),
        maximumFinalKeyInteriorExcessDegrees=float(np.rad2deg(np.max(key_excess, initial=0.))),
        maximumFinalKeyHardExcessDegrees=float(np.rad2deg(np.max(key_hard_excess, initial=0.))),
        maximumRootOffsetXYZMeters=np.max(np.abs(offsets), axis=0).tolist(),
        maximumRootOffsetMeters=float(np.max(np.linalg.norm(offsets, axis=1), initial=0.)),
        maximumRootOffsetStepMeters=float(np.max(np.linalg.norm(np.diff(offsets, axis=0), axis=1), initial=0.)),
        rootOffsetByFrame=offsets.tolist(),
        maximumFinalRootSecondDifferenceAt30Hz=float(np.max(root_quality, initial=0.)),
        maximumRelativeAccelerationLimitRatio=float(np.max(
            shake_after / np.maximum(shake_limits, 1e-12), initial=0.)),
        relativeAccelerationBefore=shake_before.tolist(),
        relativeAccelerationAfter=shake_after.tolist(),
        candidateJerkRms=jerk_after,
        jerkReferenceRms=float(np.sqrt(np.mean(np.diff(jerk_reference, n=3, axis=0) ** 2))),
        jerkAcceptanceLimit=float(jerk_limit),
        finalContactTrackVersion=final_tracks.get('version'),
        sourceResidualRowCount=source_rows,
        aggregateHeelEventRowsExcludedFromFit=source_event_count,
        rootInvariantSourceRowsExcluded=invariant_source_rows,
    )
    return ((encoded, final_tracks, points, targets) if passed else None), report


def propose_contact_heel_repair(
    rig, coordinates, *, payload, source_projection_constraint,
    anatomical_reference, pinned, fps, cyclic, deadline,
    jerk_reference, shake_reference, jerk_limit, body_scale,
    failure_report=None,
):
    """Return an exact local closed-chain proposal, or decline without mutation."""
    started = monotonic()
    if cyclic or not np.isfinite(fps) or fps <= 0. or monotonic() >= deadline:
        return None
    from .contact_heel_pitch import propose_source_heel_pitch

    coordinates = np.asarray(coordinates, dtype=float)
    reference = np.asarray(anatomical_reference, dtype=float)
    pinned = np.asarray(pinned, dtype=bool)
    names = list(rig.names)
    if (coordinates.ndim != 2 or len(coordinates) < 4
            or reference.shape != (len(coordinates), len(names), 3)
            or pinned.shape != reference.shape[:2]
            or not np.isfinite(coordinates).all() or not np.isfinite(reference).all()):
        return None
    if not source_projection_constraint.get('sourceFootHeelTrajectoryObservations'):
        return None
    image_states = {
        str(row.get('state', 'unknown')).lower()
        for row in source_projection_constraint.get('sourceFootHeelImageObservations') or []
    }
    patch_states = set()
    for evidence in (payload.get('sourceFootSupportEvidence') or {},
                     payload.get('motionSpaceSupportEvidence') or {}):
        patch = evidence.get('footPatchEvidence') or {}
        if patch.get('available') is not True:
            continue
        for side_data in (patch.get('feet') or {}).values():
            patch_states.update(str(state).lower()
                                for state in (side_data.get('states') or []))
    if (image_states - {'full_sole', 'toe_only', 'unknown'}
            or patch_states - {'full_sole', 'toe_only', 'unknown'}):
        # This proposal has no independent airborne-foot trajectory model.
        # Decline rather than extend a support-derived pitch through it.
        return None

    try:
        points = rig.decode(coordinates)
        desired_directions, pitch_report = propose_source_heel_pitch(
            rig, coordinates, payload, source_projection_constraint, pinned, fps,
            deadline=deadline)
    except (KeyError, TypeError, ValueError, FloatingPointError):
        return None
    if (not pitch_report.get('passed') or not np.isfinite(desired_directions).all()
            or monotonic() >= deadline):
        return None
    specs = _leg_specs(names, points, reference, desired_directions, pinned)
    if specs is None:
        return None
    offsets, root_report = _root_track(specs, len(points), deadline)
    if offsets is None:
        return None
    seed_encoded, _seed_targets, _seed_margins = _encode_root_adjusted_pose(
        rig, coordinates, specs, offsets)
    if seed_encoded is None or monotonic() >= deadline:
        return None
    corrected_points = rig.decode(seed_encoded)
    try:
        tracks = build_contact_foot_tracks(rig, corrected_points, pinned)
    except (ValueError, TypeError, FloatingPointError):
        return None
    if tracks.get('version') != 1:
        return None
    if any(side not in tracks for side in ('left', 'right')):
        return None
    specs = _leg_specs(names, points, reference, desired_directions, pinned)
    if specs is None:
        return None
    coupled, coupled_report = _coupled_root_fit(
        rig, coordinates, tracks, specs, reference, fps, deadline,
        pinned=pinned, seed_offsets=offsets,
        source_constraint=source_projection_constraint,
        jerk_reference=jerk_reference, shake_reference=shake_reference,
        jerk_limit=jerk_limit, body_scale=body_scale)
    if coupled is None:
        if isinstance(failure_report, dict):
            failure_report.update({
                'reason': coupled_report.get('reason') or 'coupled_root_fit_failed',
                'rootFeasibility': root_report,
                'coupledRootTrajectoryFit': coupled_report,
            })
        return None
    encoded, tracks, corrected_points, targets = coupled
    moving = sorted({joint for spec in specs for joint in spec['indices'][1:]})
    details = {
        'appliedProposal': True,
        'strategy': 'bounded_coupled_root_source_heel_pitch_closed_chain_v3',
        'elapsedSeconds': monotonic() - started,
        'rootFeasibility': root_report,
        'coupledRootTrajectoryFit': coupled_report,
        'sourceHeelPitch': pitch_report,
        'bodyPose': 'only common root translation and lower-leg/foot rotations changed',
        'contactFootTrackVersion': int(tracks['version']),
        'keyframeDecodeMaximumErrorMeters': float(np.max(
            np.abs(corrected_points[:, moving] - targets[:, moving]), initial=0.)),
    }
    return encoded, tracks, details
