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
        active_pose = spec.get('activePoseTarget', spec.get('activeContact'))
        if active_pose is not None and not active_pose[frame]:
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
        if 'kneeLower' in spec and 'kneeUpper' in spec:
            lower_margin = knee_angle - float(spec['kneeLower'][frame])
            upper_margin = float(spec['kneeUpper'][frame]) - knee_angle
            knee_margin = min(knee_margin, lower_margin, upper_margin)
            # The final source envelope is exact: optimizer tolerance must not
            # make an out-of-envelope pose an encodable initializer seed.
            unreachable |= lower_margin < 0. or upper_margin < 0.
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


def _encode_foot_world_orientations(rig, coordinates, world_orientations):
    """Encode desired foot world rotations against the actual ankle parents.

    Closed-chain target points constrain the ankle-to-foot bone direction but
    not its remaining twist. A full-sole material constraint owns the whole
    world foot orientation, so each desired matrix is rebased on the encoded
    ankle world rotation first. Only the foot local rotation changes; the
    fixed offset keeps the bone length and actual foot point.
    """
    encoded = np.asarray(coordinates, dtype=float).copy()
    if not isinstance(world_orientations, dict) or not world_orientations:
        return encoded
    if encoded.ndim != 2 or encoded.shape[1] != rig.width:
        return None
    world = rig.global_rotations(encoded)
    for side, values in world_orientations.items():
        try:
            frames = np.asarray(values['frames'], dtype=int)
            rotations = np.asarray(values['worldRotations'], dtype=float)
        except (KeyError, TypeError, ValueError):
            return None
        if (frames.ndim != 1 or rotations.shape != (len(frames), 3, 3)
                or not np.isfinite(rotations).all()
                or np.any(frames < 0) or np.any(frames >= len(encoded))):
            return None
        foot = rig.names.index(f'{side}_foot')
        ankle = rig.names.index(f'{side}_ankle')
        if foot not in rig.slots or ankle not in rig.parents:
            return None
        parent_world = world[ankle][frames]
        local = np.einsum('fji,fjk->fik', parent_world, rotations)
        slot = rig.slots[foot]
        encoded[frames, slot:slot + 3] = Rotation.from_matrix(local).as_rotvec()
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
            active_pose = spec.get('activePoseTarget', spec.get('activeContact'))
            if active_pose is not None and not active_pose[frame]:
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


def _camera_ray_mirrored_toe_points(
        rig, coordinates, points, targets, pinned, projection, theta):
    """Apply a common camera-normal yaw and its sagittal reflection to two legs."""
    from .contact_interpolation import _solve_knee

    names = list(rig.names)
    index = {name: i for i, name in enumerate(names)}
    output = np.asarray(points, dtype=float).copy()
    frames = len(output)
    reflection_normal = (output[:, index['right_hip']] - output[:, index['left_hip']])
    reflection_length = np.linalg.norm(reflection_normal, axis=1, keepdims=True)
    if not np.isfinite(reflection_length).all() or np.any(reflection_length <= 1e-8):
        raise ValueError('mirrored toe repair needs a defined sagittal hip plane')
    reflection_normal /= reflection_length
    reflection = (np.eye(3)[None] - 2. * reflection_normal[:, :, None]
                  * reflection_normal[:, None, :])
    camera_normal = np.cross(projection[0], projection[1])
    camera_normal /= max(float(np.linalg.norm(camera_normal)), _EPS)
    yaw = Rotation.from_rotvec(camera_normal * float(theta))

    for side in ('right', 'left'):
        hip, knee, ankle, foot = (index[f'{side}_{part}']
                                  for part in ('hip', 'knee', 'ankle', 'foot'))
        vector = output[:, foot] - output[:, ankle]
        if side == 'right':
            changed = yaw.apply(vector)
        else:
            changed = np.einsum('fij,fj->fi', reflection, vector)
            changed = yaw.apply(changed)
            changed = np.einsum('fij,fj->fi', reflection, changed)
        foot_target = np.where(pinned[:, foot, None], targets[:, foot], output[:, foot])
        foot_length = float(np.linalg.norm(rig.offsets[foot]))
        output[:, foot] = foot_target
        output[:, ankle] = foot_target - foot_length * _unit(changed)
        output[:, knee] = _solve_knee(
            output[:, hip], points[:, knee], points[:, ankle], output[:, ankle],
            np.full(frames, np.linalg.norm(rig.offsets[knee])),
            np.full(frames, np.linalg.norm(rig.offsets[ankle])), side)
    return output


def _free_camera_ray_authority(payload, constraint, pinned, index):
    """Require the current source evidence and resolved pins to leave both feet free."""
    if (payload.get('canonicalExecution') or {}).get('legs') != 'mirrored':
        return False
    if constraint.get('sourceFootHeelTrajectoryObservations'):
        return False
    free_states = {'unknown', 'unsupported', 'moving', 'airborne', 'free'}
    for row in constraint.get('sourceFootHeelImageObservations') or []:
        state = str(row.get('state', '')).casefold()
        if state not in free_states:
            return False
    authority_confirmed = False
    for evidence in (payload.get('sourceFootSupportEvidence') or {},
                     payload.get('motionSpaceSupportEvidence') or {}):
        patch = evidence.get('footPatchEvidence') or {}
        if patch.get('available') is not True:
            continue
        authority_confirmed = True
        feet = patch.get('feet') or {}
        for side in ('left', 'right'):
            side_data = feet.get(side)
            states = {str(state).casefold() for state in
                      (side_data or {}).get('states') or []}
            if not states or not states.issubset(free_states):
                return False
        for collection in ('contacts', 'supportContacts'):
            for contact in evidence.get(collection) or []:
                joint = str(contact.get('jointName') or '').casefold()
                kind = str(contact.get('supportKind') or '').casefold()
                if (joint in {f'{side}_{part}' for side in ('left', 'right')
                              for part in ('ankle', 'foot')}
                        or 'foot' in kind or 'sole' in kind):
                    return False
        stationary = {str(name).casefold()
                      for name in ((evidence.get('bodySupport') or {}).get(
                          'stationaryJoints') or [])}
        if any(f'{side}_{part}' in stationary for side in ('left', 'right')
               for part in ('ankle', 'foot')):
            return False
    if not authority_confirmed:
        return False
    for side in ('left', 'right'):
        ankle, foot = index[f'{side}_ankle'], index[f'{side}_foot']
        if np.any(pinned[:, ankle]) or np.any(pinned[:, foot]):
            return False
    return True


def _camera_ray_mirrored_free_foot_points(
        points, index, projection, yaw_radians, pitch_radians):
    """Rotate only free ankle-to-foot vectors with one reflected 2-DOF pair."""
    points = np.asarray(points, dtype=float)
    output = points.copy()
    hip_axis = points[:, index['right_hip']] - points[:, index['left_hip']]
    hip_length = np.linalg.norm(hip_axis, axis=1, keepdims=True)
    if not np.isfinite(hip_length).all() or np.any(hip_length <= 1e-8):
        raise ValueError('free-foot mirrored correction needs a sagittal plane')
    hip_axis /= hip_length
    reflection = (np.eye(3)[None] - 2. * hip_axis[:, :, None]
                  * hip_axis[:, None, :])
    left_knee = points[:, index['left_knee']]
    left_ankle = points[:, index['left_ankle']]
    left_foot = points[:, index['left_foot']]
    shin = _unit(left_ankle - left_knee)
    foot_vector = left_foot - left_ankle
    lateral = _unit(np.cross(shin, foot_vector))
    if (not np.isfinite(shin).all() or not np.isfinite(lateral).all()
            or np.any(np.linalg.norm(lateral, axis=1) <= 1e-8)):
        raise ValueError('free-foot mirrored correction needs a defined ankle plane')
    pitch = Rotation.from_rotvec(lateral * float(pitch_radians))
    yaw = Rotation.from_rotvec(shin * float(yaw_radians))
    left_changed = yaw.apply(pitch.apply(foot_vector))
    output[:, index['left_foot']] = left_ankle + left_changed
    # Reflect the exact left-side proper rotation into the opposite leg.
    right_ankle = points[:, index['right_ankle']]
    right_vector = points[:, index['right_foot']] - right_ankle
    left_rotation = (yaw * pitch).as_matrix()
    right_rotation = np.einsum('fij,fjk,fkl->fil', reflection,
                               left_rotation, reflection)
    right_changed = np.einsum('fij,fj->fi', right_rotation, right_vector)
    output[:, index['right_foot']] = right_ankle + right_changed
    return output


def _propose_camera_ray_mirrored_free_foot_repair(
        rig, coordinates, *, payload, source_projection_constraint,
        anatomical_reference, pinned, deadline, cyclic=False):
    """Fit one bounded mirrored yaw/pitch pair for unpinned, non-owned feet."""
    from .controlled_motion import _source_foot_ray_fit_evidence
    from .contact_interpolation import build_contact_foot_tracks

    if monotonic() >= deadline:
        return None
    names = list(rig.names)
    index = {name: i for i, name in enumerate(names)}
    required = {f'{side}_{part}' for side in ('left', 'right')
                for part in ('hip', 'knee', 'ankle', 'foot')}
    if (not required.issubset(index)
            or not _free_camera_ray_authority(
                payload, source_projection_constraint, pinned, index)):
        return None
    constraint = source_projection_constraint
    observations = constraint.get('sourceFootRayObservations') or []
    projection = np.asarray(constraint.get('projection'), dtype=float)
    coordinates = np.asarray(coordinates, dtype=float)
    reference = np.asarray(anatomical_reference, dtype=float)
    pinned = np.asarray(pinned, dtype=bool)
    points = rig.decode(coordinates)
    if (len(observations) < 2 or projection.shape != (2, 3)
            or not np.isfinite(projection).all()
            or np.linalg.matrix_rank(projection) != 2
            or reference.shape != points.shape
            or pinned.shape != points.shape[:2]):
        return None
    for row in observations:
        if not isinstance(row, dict) or row.get('sourceSide') not in ('left', 'right'):
            return None
        side = row['sourceSide']
        if (row.get('ankleJointIndex') != index[f'{side}_ankle']
                or row.get('footJointIndex') != index[f'{side}_foot']):
            return None
    before = _source_foot_ray_fit_evidence(points, constraint)
    if (not before.get('available') or before.get('passed') is True
            or any((before.get('bySide') or {}).get(side, {}).get('available') is not True
                   for side in ('left', 'right'))):
        return None
    tolerance = float(before.get('headingToleranceDegrees') or 0.) - _INTERIOR_MARGIN_DEGREES
    if not np.isfinite(tolerance) or tolerance <= 0.:
        return None

    # Bound common pitch by the existing per-side ankle articulation allowance
    # relative to its established anatomical reference.
    ankle_limits = {row[0]: np.deg2rad(float(row[4]) - _INTERIOR_MARGIN_DEGREES)
                    for row in ARTICULATIONS if row[0].endswith('_ankle')}
    pitch_low, pitch_high = -np.inf, np.inf
    for side in ('left', 'right'):
        knee, ankle, foot = (index[f'{side}_{part}']
                             for part in ('knee', 'ankle', 'foot'))
        actual = angles(points[:, knee], points[:, ankle], points[:, foot])
        expected = angles(reference[:, knee], reference[:, ankle], reference[:, foot])
        limit = ankle_limits.get(f'{side}_ankle')
        if limit is None or not np.isfinite(actual).all() or not np.isfinite(expected).all():
            return None
        # Positive pitch is defined to reduce this angle by pitch radians.
        pitch_low = max(pitch_low, float(np.max(actual - expected - limit)))
        pitch_high = min(pitch_high, float(np.min(actual - expected + limit)))
    if (not np.isfinite(pitch_low) or not np.isfinite(pitch_high)
            or pitch_low >= pitch_high):
        return None

    from scipy.optimize import least_squares

    weight = float(constraint.get('sourceFootRayWeight', constraint.get('weight', 1.)))
    if not np.isfinite(weight) or weight <= 0.:
        return None
    weights = np.asarray([float(row.get('confidenceWeight', 1.)) * weight
                          for row in observations], dtype=float)
    if not np.isfinite(weights).all() or np.any(weights <= 0.):
        return None

    def residual(parameters):
        if monotonic() >= deadline:
            raise TimeoutError('free-foot camera-ray solve exceeded its deadline')
        try:
            trial = _camera_ray_mirrored_free_foot_points(
                points, index, projection, parameters[0], parameters[1])
        except (ValueError, FloatingPointError):
            return np.full(len(observations), 1e3, dtype=float)
        values = np.empty(len(observations), dtype=float)
        for i, row in enumerate(observations):
            left, right, alpha = int(row['leftFrame']), int(row['rightFrame']), float(row['alpha'])
            ankle = (trial[left, row['ankleJointIndex']] * (1. - alpha)
                     + trial[right, row['ankleJointIndex']] * alpha)
            foot = (trial[left, row['footJointIndex']] * (1. - alpha)
                    + trial[right, row['footJointIndex']] * alpha)
            fitted = projection @ (foot - ankle)
            target = np.asarray(row.get('targetRay'), dtype=float)
            if (target.shape != (2,) or not np.isfinite(target).all()
                    or np.linalg.norm(target) <= _EPS
                    or not np.isfinite(fitted).all() or np.linalg.norm(fitted) <= _EPS):
                return np.full(len(observations), 1e3, dtype=float)
            values[i] = np.arctan2(
                target[0] * fitted[1] - target[1] * fitted[0],
                float(np.dot(target, fitted)))
        return values * np.sqrt(weights)

    try:
        fit = least_squares(
            residual, np.zeros(2), bounds=([-np.pi, pitch_low], [np.pi, pitch_high]),
            method='trf', x_scale=np.deg2rad([30., 10.]), max_nfev=80,
            ftol=1e-10, xtol=1e-10, gtol=1e-10,
        )
    except (ValueError, FloatingPointError, TimeoutError, KeyError, TypeError):
        return None
    if monotonic() >= deadline:
        return None
    yaw, pitch = map(float, fit.x)
    target_points = _camera_ray_mirrored_free_foot_points(
        points, index, projection, yaw, pitch)
    after = _source_foot_ray_fit_evidence(target_points, constraint)
    if (not after.get('available') or not after.get('passed')
            or any(float((after.get('bySide') or {}).get(side, {}).get(
                'absoluteAngularResidualP95Degrees') or np.inf) > tolerance
                for side in ('left', 'right'))):
        return None
    for side in ('left', 'right'):
        knee, ankle, foot = (index[f'{side}_{part}']
                             for part in ('knee', 'ankle', 'foot'))
        actual = angles(target_points[:, knee], target_points[:, ankle],
                        target_points[:, foot])
        expected = angles(reference[:, knee], reference[:, ankle], reference[:, foot])
        if np.max(np.abs(actual - expected), initial=0.) > ankle_limits[f'{side}_ankle'] + 1e-9:
            return None
        length_before = np.linalg.norm(points[:, foot] - points[:, ankle], axis=1)
        length_after = np.linalg.norm(target_points[:, foot] - target_points[:, ankle], axis=1)
        if np.max(np.abs(length_after - length_before), initial=0.) > 1e-9:
            return None
    moving = sorted((index['left_foot'], index['right_foot']), key=rig.order.index)
    encoded = _encode_targets(rig, coordinates, target_points, moving)
    if encoded is None or monotonic() >= deadline:
        return None
    decoded = rig.decode(encoded)
    decode_error = float(np.max(np.abs(decoded[:, moving] - target_points[:, moving]), initial=0.))
    unchanged = sorted(set(range(len(names))) - set(moving))
    unchanged_error = float(np.max(np.abs(decoded[:, unchanged] - points[:, unchanged]), initial=0.))
    foot_slots = {rig.slots[joint] for joint in moving if joint in rig.slots}
    if (decode_error > 1e-5 or unchanged_error > 1e-9
            or not np.array_equal(encoded[:, :3], coordinates[:, :3])
            or any(not np.array_equal(
                encoded[:, slot:slot + 3], coordinates[:, slot:slot + 3])
                for slot in range(3, rig.width, 3) if slot not in foot_slots)):
        return None
    tracks = build_contact_foot_tracks(rig, decoded, pinned)
    return encoded, tracks, {
        'appliedProposal': True,
        'strategy': 'source_camera_ray_mirrored_free_foot_yaw_pitch_v1',
        'cameraHeadingBefore': before,
        'cameraHeadingAfter': after,
        'derivedMirroredYawRadians': yaw,
        'derivedMirroredYawDegrees': float(np.degrees(yaw)),
        'derivedMirroredPitchRadians': pitch,
        'derivedMirroredPitchDegrees': float(np.degrees(pitch)),
        'cameraHeadingIs2DInference': True,
        'heelOr3DHeadingClaimed': False,
        'cyclicProposal': bool(cyclic),
        'contactFootTrackVersion': int(tracks['version']),
        'keyframeDecodeMaximumErrorMeters': decode_error,
        'maximumNonFootPointChangeMeters': unchanged_error,
        'fitEvaluations': int(fit.nfev),
        'anklePitchBoundsDegrees': [float(np.degrees(pitch_low)), float(np.degrees(pitch_high))],
    }


def _propose_camera_ray_mirrored_toe_repair(
        rig, coordinates, *, payload, source_projection_constraint,
        anatomical_reference, pinned, contact_targets, deadline, cyclic=False):
    """Build a toe-anchored mirrored leg proposal from qualified 2D ray rows.

    No 3D shoe heading or heel state is inferred here. The existing immutable
    candidate validator remains the final owner of all anatomy, support,
    source, playback, and temporal checks.
    """
    from .controlled_motion import _source_foot_ray_fit_evidence
    from .contact_interpolation import build_contact_foot_tracks

    if monotonic() >= deadline or (payload.get('canonicalExecution') or {}).get('legs') != 'mirrored':
        return None
    names = list(rig.names)
    index = {name: i for i, name in enumerate(names)}
    required = {f'{side}_{part}' for side in ('left', 'right')
                for part in ('hip', 'knee', 'ankle', 'foot')}
    if not required.issubset(index):
        return None
    constraint = source_projection_constraint
    observations = constraint.get('sourceFootRayObservations') or []
    projection = np.asarray(constraint.get('projection'), dtype=float)
    if (len(observations) < 2 or projection.shape != (2, 3)
            or not np.isfinite(projection).all()
            or np.linalg.matrix_rank(projection) != 2):
        return None
    coordinates = np.asarray(coordinates, dtype=float)
    reference = np.asarray(anatomical_reference, dtype=float)
    pinned = np.asarray(pinned, dtype=bool)
    targets = np.asarray(contact_targets, dtype=float)
    points = rig.decode(coordinates)
    if (reference.shape != points.shape or pinned.shape != points.shape[:2]
            or targets.shape != points.shape or not np.isfinite(targets).all()):
        return None
    sides = {side: {'ankle': index[f'{side}_ankle'],
                    'foot': index[f'{side}_foot']} for side in ('left', 'right')}
    sagittal = points[:, index['right_hip']] - points[:, index['left_hip']]
    sagittal_lengths = np.linalg.norm(sagittal, axis=1)
    if not np.isfinite(sagittal_lengths).all() or np.any(sagittal_lengths <= 1e-8):
        return None
    if (any(not np.any(pinned[:, sides[side]['foot']]) for side in ('left', 'right'))
            or any(np.any(pinned[:, sides[side]['ankle']]) for side in ('left', 'right'))):
        return None
    for row in observations:
        if not isinstance(row, dict):
            return None
        side = row.get('sourceSide')
        if side not in sides:
            return None
        if (row.get('ankleJointIndex') != sides[side]['ankle']
                or row.get('footJointIndex') != sides[side]['foot']):
            return None

    # Full-sole/material orientation and measured heel pitch retain their
    # existing owners. This path is only for toe-supported camera-ray fitting.
    if constraint.get('sourceFootHeelTrajectoryObservations'):
        return None
    for row in constraint.get('sourceFootHeelImageObservations') or []:
        if str(row.get('state', '')).casefold() == 'full_sole':
            return None
    for evidence in (payload.get('sourceFootSupportEvidence') or {},
                     payload.get('motionSpaceSupportEvidence') or {}):
        patch = evidence.get('footPatchEvidence') or {}
        if patch.get('available') is True and any(
                str(state).casefold() == 'full_sole'
                for side_data in (patch.get('feet') or {}).values()
                for state in (side_data.get('states') or [])):
            return None

    before = _source_foot_ray_fit_evidence(points, constraint)
    if not before.get('available') or before.get('passed') is True:
        return None
    by_side = before.get('bySide') or {}
    if any(by_side.get(side, {}).get('available') is not True
           for side in ('left', 'right')):
        return None
    repair_tolerance = float(before.get('headingToleranceDegrees') or 0.) - _INTERIOR_MARGIN_DEGREES
    if not np.isfinite(repair_tolerance) or repair_tolerance <= 0.:
        return None

    def evaluate(theta):
        if monotonic() >= deadline:
            return None
        trial_points = _camera_ray_mirrored_toe_points(
            rig, coordinates, points, targets, pinned, projection, theta)
        evidence = _source_foot_ray_fit_evidence(trial_points, constraint)
        side_evidence = evidence.get('bySide') or {}
        if (not evidence.get('available')
                or any(side_evidence.get(side, {}).get('available') is not True
                       or side_evidence.get(side, {}).get(
                           'absoluteAngularResidualP95Degrees') is None
                       or float(side_evidence[side]['absoluteAngularResidualP95Degrees'])
                       > repair_tolerance
                       for side in ('left', 'right'))):
            return None
        return trial_points, evidence

    # Find the nearest feasible common angle from the existing p95 ray limit.
    step = np.deg2rad(1.)
    bracket = None
    for degree in range(1, 181):
        if monotonic() >= deadline:
            return None
        magnitude = step * degree
        for theta in (-magnitude, magnitude):
            result = evaluate(theta)
            if result is not None:
                bracket = (theta, theta - np.sign(theta) * step, result)
                break
        if bracket is not None:
            break
    if bracket is None:
        return None
    passing, failing, result = bracket
    for _ in range(20):
        if monotonic() >= deadline:
            return None
        middle = (passing + failing) * .5
        candidate = evaluate(middle)
        if candidate is None:
            failing = middle
        else:
            passing, result = middle, candidate
    angle = passing
    target_points, after = result

    from .physical_validation import ARTICULATIONS
    limits = {row[0]: np.deg2rad(float(row[4]) - _INTERIOR_MARGIN_DEGREES)
              for row in ARTICULATIONS}
    for side in ('left', 'right'):
        hip, knee, ankle, foot = (index[f'{side}_{part}']
                                  for part in ('hip', 'knee', 'ankle', 'foot'))
        comparisons = (
            (f'{side}_knee', angles(target_points[:, hip], target_points[:, knee],
                                    target_points[:, ankle]),
             angles(reference[:, hip], reference[:, knee], reference[:, ankle])),
            (f'{side}_ankle', angles(target_points[:, knee], target_points[:, ankle],
                                     target_points[:, foot]),
             angles(reference[:, knee], reference[:, ankle], reference[:, foot])),
        )
        if any(np.max(np.abs(actual - expected), initial=0.) > limits[label]
               for label, actual, expected in comparisons):
            return None

    moving = sorted({index[f'{side}_{part}'] for side in ('left', 'right')
                     for part in ('knee', 'ankle', 'foot')}, key=rig.order.index)
    encoded = _encode_targets(rig, coordinates, target_points, moving)
    if encoded is None or monotonic() >= deadline:
        return None
    decoded = rig.decode(encoded)
    decode_error = float(np.max(
        np.abs(decoded[:, moving] - target_points[:, moving]), initial=0.))
    if decode_error > 1e-5:
        return None
    unchanged = sorted(set(range(len(names))) - set(moving))
    unchanged_error = float(np.max(
        np.abs(decoded[:, unchanged] - points[:, unchanged]), initial=0.))
    if unchanged_error > 1e-9:
        return None
    tracks = build_contact_foot_tracks(rig, decoded, pinned)
    if tracks.get('version') != 1 or any(side not in tracks for side in ('left', 'right')):
        return None
    return encoded, tracks, {
        'appliedProposal': True,
        'strategy': 'source_camera_ray_mirrored_toe_chain_v1',
        'cameraHeadingBefore': before,
        'cameraHeadingAfter': after,
        'derivedMirroredYawRadians': float(angle),
        'derivedMirroredYawDegrees': float(np.degrees(angle)),
        'cameraHeadingIs2DInference': True,
        'heelOr3DHeadingClaimed': False,
        'cyclicProposal': bool(cyclic),
        'contactFootTrackVersion': int(tracks['version']),
        'keyframeDecodeMaximumErrorMeters': decode_error,
        'maximumNonLegPointChangeMeters': unchanged_error,
    }


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
    failure_report=None, contact_targets=None,
):
    """Return an exact local closed-chain proposal, or decline without mutation."""
    started = monotonic()
    if not np.isfinite(fps) or fps <= 0. or monotonic() >= deadline:
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
        has_foot_pins = any(
            np.any(pinned[:, names.index(f'{side}_{part}')])
            for side in ('left', 'right') for part in ('ankle', 'foot')
            if f'{side}_{part}' in names)
        if not has_foot_pins:
            proposal = _propose_camera_ray_mirrored_free_foot_repair(
                rig, coordinates, payload=payload,
                source_projection_constraint=source_projection_constraint,
                anatomical_reference=reference, pinned=pinned,
                deadline=deadline, cyclic=cyclic)
            if proposal is None and isinstance(failure_report, dict):
                failure_report['reason'] = 'camera_ray_free_foot_ineligible_or_infeasible'
            return proposal
        if contact_targets is None:
            if isinstance(failure_report, dict):
                failure_report['reason'] = 'camera_ray_contact_targets_unavailable'
            return None
        proposal = _propose_camera_ray_mirrored_toe_repair(
            rig, coordinates, payload=payload,
            source_projection_constraint=source_projection_constraint,
            anatomical_reference=reference, pinned=pinned,
            contact_targets=contact_targets, deadline=deadline, cyclic=cyclic)
        if proposal is None and isinstance(failure_report, dict):
            failure_report['reason'] = 'camera_ray_toe_chain_ineligible_or_infeasible'
        return proposal
    if cyclic:
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
