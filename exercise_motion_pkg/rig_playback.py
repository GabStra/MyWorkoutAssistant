"""Independent checks of the poses produced between exported rig samples."""
from __future__ import annotations

import numpy as np
from scipy.spatial.transform import Rotation

from .physical_validation import angles, body_scale, validate_physical_motion, source_hinge_direction_authority
from .sequence_stabilization import contact_mask
from .contact_constraints import (stationary_target_track, stationary_contact_anchor_ids, interpolated_contact_mask,
                                   observed_ground_contact_mask, calibrate_shared_contact_pair,
                                   InfeasibleContactCorrection,
                                   vertical_only_contact_mask,
                                   vertical_only_contact_targets)

# Mid-sample contact tolerance for hermite-interpolated samples. The fit's
# keyframe anchor standard stays at 0.5mm (a solver-precision demand the
# optimizer satisfies); the spline overshoots between keyframes, so this
# limit is calibrated to the rendering-perception scale instead — 3mm is
# sub-pixel at wear-preview resolution and ~100x below visible skating.
PLAYBACK_CONTACT_LIMIT_METERS = .003
PLAYBACK_FLOOR_LIMIT_METERS = .002
RIG_NUMERICAL_CONSISTENCY_METERS = 1e-9


def playback_reference_samples(articulation, first, last, alpha, names):
    """Return time-aligned articulation and enclosing-frame anatomy references."""
    articulation = np.asarray(articulation, dtype=float)
    first = np.asarray(first, dtype=int)
    last = np.asarray(last, dtype=int)
    amount = np.asarray(alpha, dtype=float).reshape((-1, 1, 1))
    reference_samples = (articulation[first] * (1. - amount)
                         + articulation[last] * amount)
    anatomy_reference_samples = articulation[first].copy()
    index = {name: i for i, name in enumerate(names)}
    if all(name in index for name in ('left_hip', 'right_hip', 'spine1', 'neck')):
        def torso_angles(points):
            hips = .5 * (points[:, index['left_hip']] + points[:, index['right_hip']])
            return angles(hips, points[:, index['spine1']], points[:, index['neck']])

        first_torso = torso_angles(articulation[first])
        last_torso = torso_angles(articulation[last])
        use_last = last_torso < first_torso
        anatomy_reference_samples = np.where(
            use_last[:, None, None], articulation[last], anatomy_reference_samples)
    return reference_samples, anatomy_reference_samples


def rig_contact_targets(points, names, pinned, offsets, *, stationary_positions=None,
                        evidence=None, floor=None, rest_pitches=None):
    """Immutable source stance anchors, calibrated to the fixed foot geometry."""
    evidence = evidence if isinstance(evidence, dict) else {}
    reference = points.copy()
    for name, position in (stationary_positions or {}).items():
        reference[:, names.index(name)] = position
    anchors = reference.copy()
    anchor_ids = stationary_contact_anchor_ids(evidence, names, len(points))
    for joint in range(len(names)):
        anchors[:,joint],_ = stationary_target_track(reference[:,joint],pinned[:,joint],
                                                    anchor_ids=anchor_ids[:, joint])
    from .contact_constraints import fit_frame_full_sole_masks
    full_sole_state = fit_frame_full_sole_masks(evidence, None, len(points))
    maximum_calibration = 0.
    vertical_mask, vertical_targets = vertical_only_contact_targets(
        reference, evidence, names, floor=floor,
    )
    vertical_mask &= ~pinned
    anchors[:, :, 1][vertical_mask] = vertical_targets[:, :, 1][vertical_mask]
    ground = observed_ground_contact_mask(evidence, names, len(points)) & pinned
    if floor is not None:
        for side in ('left', 'right'):
            ankle, foot = names.index(side+'_ankle'), names.index(side+'_foot')
            active = ground[:, foot]
            shift = float(floor)-anchors[active, foot, 1]
            anchors[active, foot, 1] = float(floor)
            anchors[active, ankle, 1] += shift
    # Body-support materialization owns some full-sole foot pins, so those
    # frames are intentionally absent from observed_ground_contact_mask. Apply
    # their explicit one-point forefoot plane as a common pair translation;
    # this keeps the observed ankle-to-toe vector, heading and calibrated
    # material pitch intact while restoring the shoe's physical floor height.
    body_support = evidence.get('bodySupport')
    support_geometry = body_support if isinstance(body_support, dict) else evidence
    sole_pairs = {
        (contact['joints'][1], contact['joints'][2])
        for contact in support_geometry.get('soleContacts', [])
        if len(contact.get('joints') or []) == 3
    }
    for group in support_geometry.get('coplanarGroups', []):
        joints = group.get('joints') or []
        if len(joints) != 1 or 'planeOffsetMeters' not in group:
            continue
        toe_name = joints[0]
        if not toe_name.endswith('_foot'):
            continue
        side = toe_name.removesuffix('_foot')
        ankle_name = f'{side}_ankle'
        if ((ankle_name, toe_name) not in sole_pairs
                or ankle_name not in names or toe_name not in names):
            continue
        try:
            normal = np.array(group['normal'], dtype=float, copy=True)
            offset = float(group['planeOffsetMeters'])
        except (KeyError, TypeError, ValueError):
            continue
        normal_length = np.linalg.norm(normal)
        if normal.shape != (3,) or not np.isfinite(normal).all() or normal_length < 1e-8:
            continue
        normal /= normal_length
        ankle, toe = names.index(ankle_name), names.index(toe_name)
        # An observed full-sole foot owns the physical sole state even though
        # only its foot point is an exact XYZ pin. The explicit ankle pair
        # remains valid for contacts that really own both endpoints.
        active = ((pinned[:, ankle] & pinned[:, toe])
                  | (pinned[:, toe] & full_sole_state.get(side, np.zeros(len(points), dtype=bool))))
        if not np.any(active):
            continue
        shift = offset - anchors[:, toe] @ normal
        anchors[active, toe] += shift[active, None] * normal
        anchors[active, ankle] += shift[active, None] * normal
        maximum_calibration = max(maximum_calibration, float(np.max(np.abs(shift[active]), initial=0.)))
    for side in ('left', 'right'):
        ankle, foot = names.index(side+'_ankle'), names.index(side+'_foot')
        # A full-sole foot pin owns the physical sole state and its foot anchor
        # even though the ankle is not an exact XYZ pin. Shared observed stance
        # identities still calibrate their foot anchors as one rigid transform.
        active = ((pinned[:, ankle] & pinned[:, foot])
                  | (pinned[:, foot] & full_sole_state.get(
                      side, np.zeros(len(points), dtype=bool))))
        direction = anchors[:,ankle]-anchors[:,foot]
        direction /= np.maximum(np.linalg.norm(direction,axis=-1,keepdims=True),1e-12)
        proposed = anchors[:,foot]+direction*np.linalg.norm(offsets[foot])
        # Calibrating each toe episode separately must not split an ankle that
        # the source explicitly identifies as the same stationary anchor.
        shared_groups = {value for value in anchor_ids[active, ankle] if value is not None}
        shared_rows = [active & (anchor_ids[:, ankle] == group) for group in shared_groups]
        # Unnamed continuous pins own one anchor too, as stationary_target_track does.
        edges = np.diff(np.r_[False, pinned[:, ankle], False].astype(int))
        for first, stop in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)):
            rows = np.zeros(len(points), dtype=bool)
            rows[first:stop] = True
            shared_rows.append(rows & active & np.equal(anchor_ids[:, ankle], None))
        if any(len(np.unique(anchors[rows, foot], axis=0)) > 1 for rows in shared_rows):
            pair = [ankle, foot]
            calibrated = calibrate_shared_contact_pair(
                anchors[:, pair], pinned[:, pair], anchor_ids[:, pair],
                distance=np.linalg.norm(offsets[foot]), ground_mask=ground[:, pair], floor=floor)
            maximum_calibration = max(maximum_calibration, float(np.max(
                np.linalg.norm(calibrated[:, 0] - anchors[:, ankle], axis=1))))
            anchors[:, pair] = calibrated
            continue
        maximum_calibration = max(maximum_calibration, float(np.max(
            np.linalg.norm((proposed-anchors[:,ankle])[active],axis=-1),initial=0.)))
        anchors[active,ankle] = proposed[active]

    # Independent ankle/toe medians can change their pair's pitch even when
    # each source row preserves the calibrated shoe orientation. Rebuild only
    # source-clock-mapped full-sole pins from the shared material calibration.
    patch = evidence.get('footPatchEvidence') or {}
    state_indices = evidence.get('_fitFrameStateIndices')
    from .contact_constraints import fit_frame_foot_patch_states_by_side
    fit_patch_states = fit_frame_foot_patch_states_by_side(evidence, len(points))
    if state_indices is None:
        # Clockless legacy evidence has one unambiguous mapping only when its
        # native rows and fit rows have identical length. Route that case
        # through the shared mapper; timestamped evidence stays unresolved
        # unless motion_space_support_evidence attached its exact clock map.
        from .contact_constraints import mapped_foot_patch_state_indices
        state_indices = mapped_foot_patch_state_indices(
            evidence, [None] * len(points), len(points))
    if patch.get('available') is True and state_indices is not None:
        try:
            state_indices = np.asarray(state_indices)
        except (TypeError, ValueError, OverflowError):
            state_indices = np.empty(0, dtype=int)
        if state_indices.dtype.kind not in {'i', 'u'}:
            state_indices = np.empty(0, dtype=int)
        pitches = (rest_pitches or evidence.get('materialFootRestPitchRadians')
                   or evidence.get('footRestPitchRadians') or {})
        if state_indices.shape == (len(points),):
            patch_feet = patch.get('feet') or {}
            for side in ('left', 'right'):
                foot_track = patch_feet.get(side) or {}
                states = foot_track.get('states') if isinstance(foot_track, dict) else None
                if not isinstance(states, list) or side not in pitches:
                    continue
                try:
                    pitch = float(pitches[side])
                    bone_length = float(np.linalg.norm(offsets[names.index(f'{side}_foot')]))
                except (TypeError, ValueError, OverflowError, IndexError):
                    continue
                if not np.isfinite(pitch) or not np.isfinite(bone_length) or bone_length <= 1e-8:
                    continue
                aligned_states = fit_patch_states.get(side)
                if aligned_states is not None:
                    mapped_full_sole = np.asarray([
                        state == 'full_sole' for state in aligned_states
                    ], dtype=bool)
                else:
                    mapped_full_sole = np.asarray([
                        0 <= index < len(states)
                        and str(states[index]).casefold() == 'full_sole'
                        for index in state_indices
                    ], dtype=bool)
                ankle, foot = names.index(f'{side}_ankle'), names.index(f'{side}_foot')
                # The foot pin plus the observed full-sole state own this
                # calibration; the ankle target is derived from material pitch.
                active = (pinned[:, foot] & mapped_full_sole
                          & (state_indices >= 0) & (state_indices < len(states)))
                if not np.any(active):
                    continue
                horizontal = anchors[:, foot, :][:, (0, 2)] - anchors[:, ankle, :][:, (0, 2)]
                horizontal_length = np.linalg.norm(horizontal, axis=1)
                active &= np.isfinite(horizontal_length) & (horizontal_length > 1e-8)
                if not np.any(active):
                    continue
                target_vector = np.zeros_like(horizontal)
                target_vector[active] = (horizontal[active] / horizontal_length[active, None]
                                         * (bone_length * np.cos(pitch)))
                ankle_target = anchors[:, foot].copy()
                ankle_target[:, 0] -= target_vector[:, 0]
                ankle_target[:, 2] -= target_vector[:, 1]
                ankle_target[:, 1] -= bone_length * np.sin(pitch)
                maximum_calibration = max(maximum_calibration, float(np.max(
                    np.linalg.norm(ankle_target[active] - anchors[active, ankle], axis=1),
                    initial=0.)))
                anchors[active, ankle] = ankle_target[active]
    # A held ankle can outlast a full-sole patch (the toe may become hidden).
    # Calibrating only the paired rows would split that same observed point
    # into two heights, then a second target construction would median them.
    from .contact_constraints import motion_support_contacts, contact_frame_bounds, is_stationary_contact
    for side in ('left', 'right'):
        ankle, foot = names.index(side + '_ankle'), names.index(side + '_foot')
        for contact in motion_support_contacts(evidence):
            if contact.get('jointName') != side + '_ankle' or not is_stationary_contact(contact):
                continue
            first, last = contact_frame_bounds(contact, len(points))
            owned = np.zeros(len(points), dtype=bool)
            owned[first:last + 1] = pinned[first:last + 1, ankle]
            edges = np.diff(np.r_[False, owned, False].astype(int))
            for start, stop in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)):
                paired = pinned[start:stop, foot]
                if not np.any(paired):
                    continue
                identities = {value for value in anchor_ids[start:stop, ankle] if value is not None}
                if len(identities) > 1:
                    continue  # Distinct observed anchor epochs are not one point.
                calibrated = anchors[start:stop, ankle][paired]
                anchor = np.median(calibrated, axis=0)
                if np.max(np.linalg.norm(calibrated - anchor, axis=-1)) > RIG_NUMERICAL_CONSISTENCY_METERS:
                    raise InfeasibleContactCorrection('One stationary ankle interval has conflicting calibrated anchors')
                maximum_calibration = max(maximum_calibration, float(np.max(
                    np.linalg.norm(anchors[start:stop, ankle] - anchor, axis=-1))))
                anchors[start:stop, ankle] = anchor
    return anchors, maximum_calibration


def decode_rig(rig, coordinates):
    values = np.asarray(coordinates,dtype=float)
    rotations = Rotation.from_rotvec(values[:,3:].reshape(-1,3)).as_matrix().reshape(
        len(values), len(rig['rotationJointNames']), 3, 3)
    return _decode_rig_matrices(rig, values[:, :3], rotations)


def _decode_rig_matrices(rig, roots, rotations):
    """Share forward kinematics without round-tripping interpolated rotations."""
    names, parents = rig['jointNames'], rig['parents']
    slots = {names.index(n):i for i,n in enumerate(rig['rotationJointNames'])}
    points=np.empty((len(roots),len(names),3));matrices={}
    identity = np.broadcast_to(np.eye(3), (len(roots), 3, 3))
    for joint in rig['order']:
        parent=parents[joint]
        local=rotations[:,slots[joint]] if joint in slots else identity
        matrices[joint]=local if parent<0 else matrices[parent]@local
        points[:,joint]=roots if parent<0 else points[:,parent]+np.einsum('fij,j->fi',matrices[joint],rig['offsets'][joint])
    return points


def sample_rig_coordinates(rig, cursors, *, wrap=False):
    """Interpolate stored coordinates before enforcing the playback socket guard."""
    values=np.asarray(rig['coordinates'],dtype=float)
    cursors=np.asarray(cursors,dtype=float)
    cursors=np.mod(cursors,len(values)) if wrap else np.clip(cursors,0,len(values)-1)
    first=np.floor(cursors).astype(int);last=(first+1)%len(values) if wrap else np.minimum(first+1,len(values)-1)
    alpha=cursors-first
    # Convert each stored rotation once, rather than once per subframe endpoint.
    # Quaternion SLERP follows the same shortest rotation arc as the rotvec
    # composition; sinc keeps the identical/near-identical case differentiable.
    joint_count = (values.shape[1]-3)//3
    quaternions = Rotation.from_rotvec(values[:,3:].reshape(-1,3)).as_quat().reshape(len(values),joint_count,4)
    from .rig_interpolation import INTERPOLATION, LEGACY_INTERPOLATION, hermite_samples
    if rig.get('interpolation') in (INTERPOLATION, LEGACY_INTERPOLATION):
        smooth_limiter = rig.get('interpolation') == INTERPOLATION
        interpolated = hermite_samples(quaternions, first, last, alpha, wrap=wrap, quaternion=True, smooth_limiter=smooth_limiter)
        roots = hermite_samples(values[:, :3], first, last, alpha, wrap=wrap, smooth_limiter=smooth_limiter)
    else:
        left, right = quaternions[first], quaternions[last]
        dot = np.sum(left*right, axis=-1, keepdims=True)
        right = np.where(dot < 0., -right, right)
        theta = np.arccos(np.clip(abs(dot), 0., 1.)) / np.pi
        amount = alpha[:,None,None]
        interpolated = (left*(1.-amount)*np.sinc((1.-amount)*theta)
                        + right*amount*np.sinc(amount*theta)) / np.sinc(theta)
        roots = values[first,:3]*(1.-alpha[:,None])+values[last,:3]*alpha[:,None]
    rotvecs = Rotation.from_quat(interpolated.reshape(-1, 4)).as_rotvec().reshape(len(cursors), -1)
    return np.concatenate([roots, rotvecs], axis=1)


def sample_rig(rig, cursors, *, wrap=False, native_foot_geometry=None, foot_scale=None,
               return_side_axes=False):
    coordinates = sample_rig_coordinates(rig, cursors, wrap=wrap)
    # Keyframe socket projection does not preserve the collar plane under
    # rotation interpolation. Re-apply the same analytic clamp on samples so
    # residual, export, and playback validate one consistent neck attachment.
    from .controlled_motion import ANATOMY_FIT_MARGIN, project_neck_attachment_values
    from .physical_validation import SOCKET_ALIGNMENT_MAX_LATERAL_RATIO
    names = list(rig['jointNames'])
    active = [names.index(name) for name in rig['rotationJointNames']]
    coordinates = project_neck_attachment_values(
        coordinates, np.asarray(rig['offsets'], dtype=float), names, active,
        SOCKET_ALIGNMENT_MAX_LATERAL_RATIO - ANATOMY_FIT_MARGIN)
    points = decode_rig(rig, coordinates)
    from .contact_interpolation import sample_contact_foot_tracks
    if native_foot_geometry is None:
        native_foot_geometry = rig.get('_nativeFootGeometryForSampling')
    if foot_scale is None:
        foot_scale = rig.get('_nativeFootScaleForSampling')
    return sample_contact_foot_tracks(
        rig, cursors, points, wrap=wrap,
        native_foot_geometry=native_foot_geometry, foot_scale=foot_scale,
        return_side_axes=return_side_axes)


def native_material_sampling_payload(rig):
    """Legacy artifacts retain their original serialized material baseline."""
    return rig.get('_nativeMaterialPayloadForSampling')


def _native_sampling_rig(payload):
    """Attach top-level geometry authority only to this ephemeral sampling view."""
    rig = payload['fixedRig']
    if 'materialFrames' in rig:
        from .native_material_frames import validate_material_frames
        validate_material_frames(rig)
        if len(payload.get('frames', ())) != len(rig['coordinates']):
            raise ValueError('materialFrames rig and payload frame clocks differ')
    support_tracks = None
    if 'supportJointTracks' in rig:
        from .support_joint_tracks import validate_support_joint_tracks
        support_tracks = validate_support_joint_tracks(
            rig['supportJointTracks'], list(rig['jointNames']),
            len(rig.get('coordinates') or []))
    tracks = rig.get('contactFootTracks')
    if not isinstance(tracks, dict) or tracks.get('version') != 2:
        if support_tracks is None:
            return rig
        return {**rig, '_supportJointTracksForSampling': support_tracks}
    from .foot_geometry import foot_scale_from_pose
    from .native_foot_geometry import validated_native_foot_geometry
    names = list(rig['jointNames'])
    frames = payload.get('frames') or []
    if not frames:
        raise ValueError('native material sampling requires canonical frame-zero scale')
    geometry = validated_native_foot_geometry(payload.get('nativeFootGeometry'))
    if geometry is None:
        raise ValueError('native material sampling requires root nativeFootGeometry')
    points0 = np.asarray([frames[0]['joints'][name] for name in names], dtype=float)
    canonical_execution = payload.get('canonicalExecution')
    result = {**rig,
            '_nativeMaterialPayloadForSampling': payload,
            '_canonicalExecutionForSampling': (
                dict(canonical_execution) if isinstance(canonical_execution, dict) else {}),
            '_nativeFootGeometryForSampling': geometry,
            '_nativeFootScaleForSampling': float(foot_scale_from_pose(points0, names))}
    if support_tracks is not None:
        result['_supportJointTracksForSampling'] = support_tracks
    return result


def unanchored_floor_clearance_lift(rig, floor, pinned, *, cyclic, subdivisions=4):
    """A constant placement correction cannot change motion or break a loop seam."""
    if floor is None or np.any(pinned):
        return 0.0
    count = len(rig['coordinates'])
    cursors = np.arange(count * subdivisions if cyclic else (count - 1) * subdivisions + 1) / subdivisions
    points = sample_rig(rig, cursors, wrap=cyclic)
    return max(0.0, float(floor) - float(points[:, :, 1].min()))


def free_joint_floor_clearance_lift(rig, floor, pinned, *, cyclic, subdivisions=4):
    """Raise only the unsupported interpolated path above the floor.

    Planted contacts keep their anchors; a constant root lift is recovered by
    a later freeze-root plant projection so stance does not float away.
    """
    if floor is None:
        return 0.0
    if not np.any(pinned):
        return unanchored_floor_clearance_lift(rig, floor, pinned, cyclic=cyclic, subdivisions=subdivisions)
    count = len(rig['coordinates'])
    cursors = np.arange(count * subdivisions if cyclic else (count - 1) * subdivisions + 1) / subdivisions
    points = sample_rig(rig, cursors, wrap=cyclic)
    first = np.floor(cursors).astype(int)
    last = np.ceil(cursors).astype(int) % count
    planted = pinned[first] & pinned[last]
    heights = np.asarray(points[:, :, 1], dtype=float)
    heights[planted] = np.inf
    lowest = float(np.min(heights))
    if not np.isfinite(lowest):
        return 0.0
    return max(0.0, float(floor) - lowest)


def native_active_contact_ownership(tracks, *, count, cursors=None, cyclic=False, subdivisions=4):
    """Per-foot cursor ownership from the active native material contact tracks.

    A native side track that is active at a cursor binds that shoe's material to
    a physical support target. The shoe is anchored geometry, not free flight, so
    a rig-wide floor lift must not use its vertices to justify a global
    translation. Ownership is the union of the two frames enclosing each cursor,
    matching how interpolated playback reaches the measured samples.
    """
    if not isinstance(tracks, dict) or tracks.get('version') != 2:
        return {}
    if cursors is None:
        cursors = np.arange(count * subdivisions if cyclic else (count - 1) * subdivisions + 1) / subdivisions
    first = np.floor(np.asarray(cursors, dtype=float)).astype(int)
    last = np.ceil(np.asarray(cursors, dtype=float)).astype(int) % count
    ownership = {}
    for side in ('left', 'right'):
        track = tracks.get(side)
        if track is None:
            continue
        active = np.asarray(track.get('active'), dtype=bool)
        if active.shape != (count,) or not active.any():
            continue
        ownership[side] = active[first] | active[last]
    return ownership


def _free_material_sampling_rig(rig, owned, cursors):
    """Ephemeral sampling view that drops contact samples the free-foot measure discards.

    The free outsole measure only scores cursors a side does not own; those owned
    cursors are excluded from the result, so the sampler must not run their
    contact IK. A cursor is contact-corrected only when one of its enclosing
    frames is active, and those are exactly the cursors ``owned`` marks, so
    deactivating an owned side leaves every free cursor unchanged. Mirrored-leg
    playback can still use an owned side as the unilateral driver of the free
    contralateral chain, so such a driver keeps its samples.
    """
    tracks = rig.get('contactFootTracks')
    if not isinstance(tracks, dict) or tracks.get('version') != 2 or not owned:
        return rig
    execution = rig.get('_canonicalExecutionForSampling') or {}
    empty = np.zeros(len(np.asarray(cursors).reshape(-1)), dtype=bool)
    left = empty if owned.get('left') is None else np.asarray(owned['left'], dtype=bool)
    right = empty if owned.get('right') is None else np.asarray(owned['right'], dtype=bool)
    drivers = set()
    if execution.get('legs') == 'mirrored':
        if np.any(left & ~right):
            drivers.add('left')
        if np.any(right & ~left):
            drivers.add('right')
    masked = dict(tracks)
    for side in ('left', 'right'):
        track = masked.get(side)
        if track is None or side not in owned or side in drivers:
            continue
        masked[side] = {
            **track,
            'active': [False] * len(track['active']),
            'anchorIds': [None] * len(track['anchorIds']),
            'episodes': [],
        }
    return {**rig, 'contactFootTracks': masked}


def free_material_floor_clearance_lift(payload, pinned, *, cyclic, subdivisions=4):
    """Measure outsole clearance on dense playback, excluding verified plants."""
    floor = payload.get('renderFloorY')
    pitches = payload.get('footRestPitchRadians') or {}
    if floor is None:
        return 0.0

    from .foot_geometry import _sample_material_foot_geometry, foot_scale_from_pose, shoe_vertices
    from .contact_constraints import (
        contact_frame_bounds, motion_space_support_evidence, motion_support_contacts,
        observed_ground_contact_mask,
    )

    rig = _native_sampling_rig(payload)
    frames, names = payload['frames'], payload['jointNames']
    count = len(frames)
    pinned = np.asarray(pinned, dtype=bool)
    if pinned.shape != (count, len(names)):
        raise ValueError('pinned mask must match playback frame and joint counts')
    cursors = np.arange(count * subdivisions if cyclic else (count - 1) * subdivisions + 1) / subdivisions
    owned = native_active_contact_ownership(
        (payload.get('fixedRig') or {}).get('contactFootTracks'),
        count=count, cursors=cursors, cyclic=cyclic)
    points, side_axes = sample_rig(
        _free_material_sampling_rig(rig, owned, cursors), cursors, wrap=cyclic,
        return_side_axes=True)
    first = np.floor(cursors).astype(int)
    last = np.ceil(cursors).astype(int) % count
    evidence = motion_space_support_evidence(payload)
    ground = observed_ground_contact_mask(evidence, names, count)
    full_sole = np.zeros_like(ground)
    for contact in motion_support_contacts(evidence):
        if contact.get('contactState') == 'full_sole' and contact.get('jointName') in names:
            start, end = contact_frame_bounds(contact, count)
            joint = str(contact['jointName'])
            joints = [joint]
            if joint.endswith(('_ankle', '_foot')):
                side = joint.split('_', 1)[0]
                joints = [f'{side}_ankle', f'{side}_foot']
            for name in joints:
                if name in names:
                    full_sole[start:end + 1, names.index(name)] = True

    axes = _sample_material_foot_geometry(
        payload, cursors, points, side_axes_override=side_axes)
    scale = foot_scale_from_pose(
        np.asarray([frames[0]['joints'][name] for name in names]), names)
    maximum_lift = 0.0
    for side in ('left', 'right'):
        ankle_name, toe_name = f'{side}_ankle', f'{side}_foot'
        if ankle_name not in names or toe_name not in names:
            continue
        pitch = float(pitches[side]) if side in pitches else None
        ankle, toe = names.index(ankle_name), names.index(toe_name)
        planted = (pinned[first, toe] & pinned[last, toe]
                   & full_sole[first, toe] & full_sole[last, toe]
                   & ground[first, toe] & ground[last, toe])
        free = ~planted
        side_owned = owned.get(side)
        if side_owned is not None:
            free &= ~side_owned
        if not np.any(free):
            continue
        vertices = shoe_vertices(
            points[:, ankle], points[:, toe], axes[side]['lateral'], pitch, scale,
            orientation=axes[side].get('orientation'),
            native_geometry=axes[side].get('nativeGeometry'))
        minimum = float(vertices[free, :, 1].min())
        maximum_lift = max(maximum_lift, float(floor) - minimum)
    return max(0.0, maximum_lift)


def mirrored_arm_policy_evidence(payload, points=None):
    """Check explicit symmetry on the native path at fixed-rig numerical precision."""
    if (payload.get('canonicalExecution') or {}).get('arms') != 'mirrored':
        return {'required': False, 'passed': True}
    try:
        rig = _native_sampling_rig(payload)
        names = rig['jointNames']
        if points is None:
            count = len(rig['coordinates'])
            cyclic = bool((payload.get('loop') or {}).get('enabled'))
            cursors = np.arange(count * 4 if cyclic else (count - 1) * 4 + 1) / 4
            points = sample_rig(rig, cursors, wrap=cyclic)
        from .controlled_motion import canonical_bilateral_reference
        arm_indices = [names.index(side + '_' + part) for side in ('left', 'right')
                       for part in ('shoulder', 'elbow', 'wrist', 'hand')]
        canonical = canonical_bilateral_reference(points, names, {'arms': 'mirrored'})
        residual = float(np.max(np.linalg.norm((canonical - points)[:, arm_indices], axis=-1)))
    except (KeyError, ValueError, TypeError, IndexError):
        return {'required': True, 'passed': False, 'reason': 'native_mirrored_arm_geometry_unavailable'}
    return {'required': True, 'passed': bool(np.isfinite(residual)
                                           and residual <= RIG_NUMERICAL_CONSISTENCY_METERS),
            'maximumNativeResidualMeters': residual,
            'numericalConsistencyToleranceMeters': RIG_NUMERICAL_CONSISTENCY_METERS}


def canonical_execution_policy_evidence(payload, points=None, *,
                                        sample_positions=None, side_axes=None):
    """Verify declared canonical pose and stance targets on dense native samples."""
    if payload.get('canonicalExecutionIntentProblem'):
        return {'required': True, 'passed': False,
                'reason': payload['canonicalExecutionIntentProblem']}
    execution = payload.get('canonicalExecution')
    if execution is None:
        execution = {}
    if not isinstance(execution, dict):
        return {'required': True, 'passed': False,
                'reason': 'canonical_execution_policy_unavailable'}

    allowed = {
        'arms': {'mirrored', 'unconstrained'},
        'legs': {'mirrored', 'unconstrained'},
        'torso': {'sagittal', 'support_aligned', 'unconstrained'},
    }
    pose_execution = {}
    for group, valid_modes in allowed.items():
        mode = execution.get(group)
        if mode is None:
            continue
        if mode not in valid_modes:
            return {'required': True, 'passed': False,
                    'reason': 'canonical_execution_mode_invalid', 'group': group}
        pose_execution[group] = mode
    pose_required = any(mode != 'unconstrained' for mode in pose_execution.values())
    stance_mode = execution.get('stance')
    stance_required = stance_mode == 'stationary_bilateral'
    if stance_mode not in (None, 'unconstrained', 'stationary_bilateral'):
        return {'required': True, 'passed': False,
                'reason': 'canonical_stance_mode_invalid'}
    required = pose_required or stance_required
    if not required:
        return {'required': False, 'passed': True}

    pose_report = {'required': pose_required, 'passed': True}
    stance_report = {'required': stance_required, 'passed': True}
    names = list(payload.get('jointNames') or (payload.get('fixedRig') or {}).get('jointNames') or [])
    samples = None
    playback_positions = None
    playback_side_axes = side_axes
    if pose_required or stance_required:
        try:
            if points is None:
                rig = _native_sampling_rig(payload)
                count = len(rig['coordinates'])
                cyclic = bool((payload.get('loop') or {}).get('enabled'))
                playback_positions = np.arange(
                    count * 4 if cyclic else (count - 1) * 4 + 1) / 4
                if (rig.get('contactFootTracks') or {}).get('version') == 2:
                    samples, playback_side_axes = sample_rig(
                        rig, playback_positions, wrap=cyclic, return_side_axes=True)
                else:
                    samples = sample_rig(rig, playback_positions, wrap=cyclic)
            else:
                samples = np.asarray(points, dtype=float)
                if sample_positions is not None:
                    playback_positions = np.asarray(sample_positions, dtype=float).reshape(-1)
                elif len(samples) == len(payload.get('frames') or []):
                    playback_positions = np.arange(len(samples), dtype=float)
                native_tracks = (payload.get('fixedRig') or {}).get('contactFootTracks')
                if (playback_side_axes is None and playback_positions is not None
                        and isinstance(native_tracks, dict)
                        and native_tracks.get('version') == 2):
                    rig = _native_sampling_rig(payload)
                    _, playback_side_axes = sample_rig(
                        rig, playback_positions,
                        wrap=bool((payload.get('loop') or {}).get('enabled')),
                        return_side_axes=True)
            if (not names or samples.ndim != 3 or samples.shape[1:] != (len(names), 3)
                    or not np.isfinite(samples).all()):
                raise ValueError('dense canonical samples are missing or invalid')
        except (KeyError, TypeError, ValueError, IndexError):
            return {'required': True, 'passed': False,
                    'reason': 'canonical_execution_geometry_unavailable',
                    'posePolicy': {'required': pose_required, 'passed': not pose_required},
                    'stationaryBilateralStance': {'required': stance_required,
                                                  'passed': not stance_required}}

    if pose_required:
        try:
            from .controlled_motion import KEYFRAME_CONTACT_LIMIT_METERS, canonical_bilateral_reference
            canonical = canonical_bilateral_reference(samples, names, pose_execution)
            residual = np.linalg.norm(canonical - samples, axis=-1)
            per_joint = {name: float(np.max(residual[:, index]))
                         for index, name in enumerate(names)}
            maximum = max(per_joint.values(), default=float('inf'))
            pose_report = {
                'required': True,
                'passed': bool(np.isfinite(maximum)
                               and maximum <= KEYFRAME_CONTACT_LIMIT_METERS),
                'modes': pose_execution,
                'checkedJoints': names,
                'perJointMaximumResidualMeters': per_joint,
                'maximumResidualMeters': maximum,
                'toleranceMeters': KEYFRAME_CONTACT_LIMIT_METERS,
            }
        except (KeyError, ValueError, TypeError, IndexError, FloatingPointError):
            pose_report = {'required': True, 'passed': False,
                           'reason': 'canonical_execution_geometry_unavailable',
                           'modes': pose_execution}

    if stance_required:
        # The compatibility classifier is owned by source-contact policy. It
        # may allow estimates when source observations are unknown, but it must
        # veto known incompatible ground/airborne evidence.
        try:
            from .sequence_stabilization import canonical_stance_compatibility, fit_contact_mask
            from .contact_constraints import motion_space_support_evidence
            count = len(payload.get('frames') or [])
            if count < 2:
                raise ValueError('stationary stance requires two native frames')
            support_evidence = motion_space_support_evidence(payload)
            compatibility = canonical_stance_compatibility(
                payload, names=names, count=count, support_evidence=support_evidence)
            fit_mask = fit_contact_mask(
                payload, names=names, count=count, support_evidence=support_evidence)
        except (ImportError, TypeError, ValueError, KeyError, AttributeError):
            compatibility, fit_mask = None, None
        compatibility_passed = (compatibility is True or
                                isinstance(compatibility, dict)
                                and compatibility.get('passed') is True)
        toe_checks = {}
        try:
            from .controlled_motion import KEYFRAME_CONTACT_LIMIT_METERS
            if len(samples) < 2:
                raise ValueError('stationary stance requires at least two samples')
            frames = payload.get('frames') or []
            fixed_rig = payload.get('fixedRig') or {}
            native_tracks = fixed_rig.get('contactFootTracks')
            native_track_present = (
                isinstance(native_tracks, dict) and native_tracks.get('version') == 2)
            material_forefeet = None
            native_observed_frames = {}
            if native_track_present:
                if (playback_positions is None
                        or len(playback_positions) != len(samples)):
                    raise ValueError('native material stance sample clock is unavailable')
                from .native_foot_geometry import validated_native_foot_geometry
                if validated_native_foot_geometry(payload.get('nativeFootGeometry')) is None:
                    raise ValueError('native material stance geometry is unavailable')
                from .foot_geometry import _sample_material_foot_geometry
                material_geometry = _sample_material_foot_geometry(
                    payload, playback_positions, samples,
                    side_axes_override=playback_side_axes)
                from .foot_geometry import foot_scale_from_pose, shoe_vertices
                from .support_geometry import _NATIVE_SHOE_SOLE_RING_VERTICES
                from .material_region_support import shoe_triangles
                from .body_surface_geometry import evaluate_contact_patch
                native_geometry = validated_native_foot_geometry(
                    payload.get('nativeFootGeometry'))
                if native_geometry is None:
                    raise ValueError('native material stance geometry is unavailable')
                frame_points = np.asarray([
                    [frame['joints'][name] for name in names] for frame in frames
                ], dtype=float)
                scale = float(foot_scale_from_pose(frame_points[0], names))
                if not np.isfinite(scale) or scale <= 0.:
                    raise ValueError('native material stance scale is unavailable')
                scale_count = len(frames)
                first = np.floor(playback_positions).astype(int)
                wrap = bool((payload.get('loop') or {}).get('enabled'))
                last = (first + 1) % scale_count if wrap else np.minimum(first + 1, scale_count - 1)
                first = np.mod(first, scale_count) if wrap else np.clip(first, 0, scale_count - 1)
                triangles = shoe_triangles()
                material_forefeet = {}
                for side in ('left', 'right'):
                    values = material_geometry.get(side)
                    if values is None:
                        raise ValueError('native material stance is missing a side')
                    ankle_i, toe_i = names.index(f'{side}_ankle'), names.index(f'{side}_foot')
                    pitches = payload.get('footRestPitchRadians') or {}
                    shoes = shoe_vertices(
                        samples[:, ankle_i], samples[:, toe_i], values['lateral'],
                        float(pitches[side]) if side in pitches else None,
                        scale, orientation=values.get('orientation'),
                        native_geometry=values.get('nativeGeometry'))
                    # A free inferred foot uses the actual rendered forefoot
                    # sole patch, not the skin marker or toe-joint pivot.
                    pivots = np.mean(
                        shoes[:, _NATIVE_SHOE_SOLE_RING_VERTICES[-2:]], axis=1)
                    track = native_tracks.get(side) or {}
                    active = np.asarray(track.get('active', ()), dtype=bool)
                    anchor_ids = track.get('anchorIds')
                    if active.shape != (scale_count,):
                        raise ValueError(f'{side} native stance active mask is invalid')
                    if not isinstance(anchor_ids, (list, tuple)) or len(anchor_ids) != scale_count:
                        raise ValueError(f'{side} native stance anchor ids are invalid')
                    active_sample = active[first] & active[last]
                    same_anchor = np.asarray([
                        anchor_ids[a] == anchor_ids[b]
                        for a, b in zip(first, last)
                    ], dtype=bool)
                    active_sample &= same_anchor
                    observed = np.zeros(len(samples), dtype=bool)
                    episode_covered = np.zeros(len(samples), dtype=bool)
                    for episode in track.get('episodes') or []:
                        start, end = int(episode['startFrame']), int(episode['endFrame'])
                        rows = (active_sample & (first >= start) & (last <= end)
                                & np.asarray([
                                    anchor_ids[a] == episode.get('anchorId')
                                    and anchor_ids[b] == episode.get('anchorId')
                                    for a, b in zip(first, last)
                                ], dtype=bool))
                        selected = np.flatnonzero(rows)
                        if not len(selected):
                            continue
                        mode = episode.get('mode')
                        if mode == 'verticalOnly':
                            # A vertical-only episode still supplies a valid
                            # native forefoot surface pivot. Keep its changing
                            # pitch in the sampled shoe geometry; do not treat
                            # the skin/toe joint as the floor contact.
                            episode_covered[selected] = True
                            continue
                        if mode != 'stationary':
                            raise ValueError(f'{side} native stance episode mode is invalid')
                        primitive = str(episode['primitiveId'])
                        bary_point = evaluate_contact_patch(
                            {primitive: {'vertices': shoes[selected], 'triangles': triangles}},
                            {'primitiveId': primitive, 'points': [{
                                'triangleIndex': int(episode['triangleIndex']),
                                'barycentric': list(episode['barycentric']),
                            }]})[:, 0]
                        if (bary_point.shape != (len(selected), 3)
                                or not np.isfinite(bary_point).all()):
                            raise ValueError(f'{side} native stance episode point is invalid')
                        pivots[selected] = bary_point
                        observed[selected] = True
                        episode_covered[selected] = True
                    if (np.any(active_sample) and not np.all(episode_covered[active_sample])):
                        raise ValueError(f'{side} native stance episode coverage is incomplete')
                    if pivots.shape != (len(samples), 3) or not np.isfinite(pivots).all():
                        raise ValueError(f'{side} native material stance pivots are invalid')
                    material_forefeet[side] = pivots
                    native_observed_frames[side] = int(np.count_nonzero(observed))
            floor = payload.get('renderFloorY')
            if floor is None:
                if material_forefeet is not None:
                    floor = float(np.median(np.stack([
                        material_forefeet[side][:, 1] for side in ('left', 'right')
                    ])))
                    floor_authority = 'estimated_median_bilateral_material_forefoot_plane'
                else:
                    toe_names = [f'{side}_foot' for side in ('left', 'right')]
                    if any(name not in names for name in toe_names):
                        raise KeyError('both toe pivots are required to estimate the floor plane')
                    toe_indices = [names.index(name) for name in toe_names]
                    floor = float(np.median(samples[:, toe_indices, 1]))
                    floor_authority = 'estimated_median_bilateral_toe_plane'
            else:
                if (isinstance(floor, bool) or not isinstance(floor, (int, float))
                        or not np.isfinite(floor)):
                    raise ValueError('explicit renderFloorY must be finite')
                floor = float(floor)
                floor_authority = 'payload_renderFloorY'
            for side in ('left', 'right'):
                name = f'{side}_foot'
                if name not in names:
                    raise KeyError(name)
                pivot = (material_forefeet[side] if material_forefeet is not None
                         else samples[:, names.index(name)])
                drift = np.linalg.norm(pivot - pivot[0], axis=-1)
                toe_floor_error = np.abs(pivot[:, 1] - float(floor))
                observed_frames = native_observed_frames.get(side, 0)
                toe_checks[side] = {
                    'maximumDriftMeters': float(np.max(drift)),
                    'maximumToeFloorErrorMeters': float(np.max(toe_floor_error)),
                    'toleranceMeters': KEYFRAME_CONTACT_LIMIT_METERS,
                    'pivotKind': (
                        'qualified_episode_material_point'
                        if native_track_present and native_observed_frames.get(side, 0)
                        else 'native_forefoot_sole_patch'
                        if native_track_present else 'legacy_toe_joint'),
                    'geometryAuthority': (
                        'source_native_contact_track' if observed_frames
                        else 'canonical_inferred_native_geometry'
                    ) if native_track_present else 'legacy_payload_geometry',
                    'observedTrackFrameCount': native_observed_frames.get(side, 0),
                    'passed': bool(np.max(drift) <= KEYFRAME_CONTACT_LIMIT_METERS
                                   and np.max(toe_floor_error) <= KEYFRAME_CONTACT_LIMIT_METERS),
                }
            fit_mask_valid = (isinstance(fit_mask, np.ndarray)
                              and fit_mask.shape == (count, len(names)))
            fit_toes_pinned = (fit_mask_valid and all(
                bool(np.all(fit_mask[:, names.index(f'{side}_foot')]))
                for side in ('left', 'right')))
            stance_passed = (compatibility_passed and fit_mask_valid
                             and fit_toes_pinned
                             and all(row['passed'] for row in toe_checks.values()))
            stance_report = {
                'required': True,
                'passed': bool(stance_passed),
                'compatibility': compatibility,
                'floorY': floor,
                'floorAuthority': floor_authority,
                'fitContactMaskAvailable': bool(fit_mask_valid),
                'bothToePivotsPinnedByFitPolicy': bool(fit_toes_pinned),
                'toePivots': toe_checks,
            }
        except (KeyError, ValueError, TypeError, IndexError, FloatingPointError):
            stance_report = {
                'required': True, 'passed': False,
                'reason': 'canonical_bilateral_stance_geometry_unavailable',
                'compatibility': compatibility,
                'fitContactMaskAvailable': False,
                'bothToePivotsPinnedByFitPolicy': False,
                'toePivots': toe_checks,
            }

    return {
        'required': True,
        'passed': bool(pose_report.get('passed') is True
                       and stance_report.get('passed') is True),
        'posePolicy': pose_report,
        'stationaryBilateralStance': stance_report,
    }


def validate_rig_playback(payload, *, subdivisions=4):
    rig=_native_sampling_rig(payload);names=rig['jointNames'];count=len(rig['coordinates']);fps=float(payload['fps'])
    from .body_support_observation import materialize_stationary_sole_support
    materialized_support = materialize_stationary_sole_support(payload)
    contact_tracks = rig.get('contactFootTracks')
    if isinstance(contact_tracks, dict) and contact_tracks.get('version') == 2:
        from .contact_interpolation import suppress_native_foot_pins
        from .foot_geometry import foot_scale_from_pose
        from .native_foot_geometry import validated_native_foot_geometry
        materialized_support['_nativeFootMaterialTracks'] = contact_tracks
        materialized_support['_nativeFootScale'] = float(foot_scale_from_pose(
            np.asarray([payload['frames'][0]['joints'][name] for name in names], dtype=float), names))
        materialized_support['nativeFootGeometry'] = validated_native_foot_geometry(
            payload.get('nativeFootGeometry'))
    from .support_geometry import support_contact_readiness
    support_readiness = support_contact_readiness(payload, evidence=materialized_support)
    cyclic=bool((payload.get("loop") or {}).get("enabled"))
    cursors=np.arange(count*subdivisions if cyclic else (count-1)*subdivisions+1)/subdivisions
    from .contact_interpolation import ContactFootIKUnreachable
    try:
        points, playback_side_axes = sample_rig(
            rig, cursors, wrap=cyclic, return_side_axes=True)
    except ContactFootIKUnreachable as error:
        return {
            'passed': False,
            'reason': 'contact_foot_ik_unreachable',
            'physicalReasons': ['contact_foot_ik_unreachable'],
            'contactFootIKUnreachable': error.evidence(),
            'validationStatusByCheck': {
                'rigSampling': 'failed',
                'contactReachability': 'failed',
                'contactAnchors': 'unverified',
                'heelContact': 'unverified',
                'floorClearance': 'unverified',
                'anatomy': 'unverified',
                'physicalMotion': 'unverified',
                'boneLengthVariation': 'unverified',
                'velocityContinuity': 'unverified',
                'loopSeam': 'unverified',
                'equipment': 'unverified',
                'bodySupport': 'unverified',
                'shoeOrientation': 'unverified',
            },
        }
    scale=body_scale(points,names)
    originals=np.asarray([[f['joints'][n] for n in names] for f in payload['frames']],dtype=float)
    sample_error=float(np.max(abs(points[::subdivisions]-originals)))
    pinned=contact_mask(payload,names,count,support_evidence=materialized_support)
    if pinned is None:
        return {'passed':False,'reason':'unrepresented_heel_contact'}
    if isinstance(contact_tracks, dict) and contact_tracks.get('version') == 2:
        try:
            pinned = suppress_native_foot_pins(
                pinned, names, contact_tracks, support_evidence=materialized_support)
        except ValueError as error:
            return {'passed': False, 'reason': 'native_foot_contact_track_invalid',
                    'nativeFootContactError': str(error)}
    source=np.asarray([[f.get('supportContactReferenceJoints', f.get('controlledSourceJoints',f['joints']))[n] for n in names] for f in payload['frames']],dtype=float)
    placement = payload.get('scenePlacement', {})
    unplaced, fitting_floor = source, payload.get('renderFloorY')
    if placement.get('version') == 1:
        # Component medians are not rotation-equivariant. Reconstruct the
        # immutable stance anchors in the fitting frame, then place them with
        # the rig; do not choose new anchors after a presentation rotation.
        rotation = Rotation.from_rotvec(placement['rotationVector'])
        origin = np.asarray(placement['originAfterRotation'])
        unplaced = rotation.inv().apply((source + origin).reshape(-1, 3)).reshape(source.shape)
        fitting_floor = None if (payload.get('renderFloorY') is None or placement.get('floorInferred')) else float(payload['renderFloorY'])+float(origin[1])
    try:
        anchors,_=rig_contact_targets(
            unplaced, names, pinned, rig['offsets'], evidence=materialized_support,
            floor=fitting_floor, rest_pitches=payload.get('footRestPitchRadians'))
    except InfeasibleContactCorrection as error:
        return {'passed': False, 'reason': 'incompatible_stationary_contact_anchors',
                'physicalReasons': ['incompatible_stationary_contact_anchors'],
                'contactConstraintError': str(error)}
    if placement.get('version') == 1:
        anchors = rotation.apply(anchors.reshape(-1, 3)).reshape(source.shape) - origin
    first=np.floor(cursors).astype(int);last=np.ceil(cursors).astype(int)%count
    anchor_ids = stationary_contact_anchor_ids(materialized_support, names, count)
    active = interpolated_contact_mask(pinned, first, last, anchor_ids)
    contact_error=float(np.max(np.linalg.norm((points-anchors[first])[active],axis=-1),initial=0.))
    frame_contact_error=float(np.max(np.linalg.norm((originals-anchors)[pinned],axis=-1),initial=0.))
    vertical_mask = vertical_only_contact_mask(materialized_support, names, count) & ~pinned
    if isinstance(contact_tracks, dict) and contact_tracks.get('version') == 2:
        vertical_mask = suppress_native_foot_pins(
            vertical_mask, names, contact_tracks, support_evidence=materialized_support)
    vertical_active = vertical_mask[first] & vertical_mask[last]
    vertical_error = float(np.max(np.abs(
        points[:, :, 1][vertical_active] - anchors[first, :, 1][vertical_active]
    ), initial=0.))
    frame_vertical_error = float(np.max(np.abs(
        originals[:, :, 1][vertical_mask] - anchors[:, :, 1][vertical_mask]
    ), initial=0.))
    from .heel_contacts import heel_contact_tracks
    from .heel_contacts import resolved_foot_side_axes
    heel_side_axes = resolved_foot_side_axes(unplaced, names)
    key_material_axes = None
    if 'materialFrames' in rig:
        from .native_material_frames import material_axes
        key_material_axes = material_axes(rig, np.arange(count))
        reference_axes = material_axes(
            {**rig, 'coordinates': rig['materialFrames']['referenceCoordinates']}, np.arange(count))
        heel_side_axes = ({side: rotation.inv().apply(axes) for side, axes in reference_axes.items()}
                          if placement.get('version') == 1 else reference_axes)
    heel_contacts = heel_contact_tracks(
        unplaced, names, materialized_support, floor=fitting_floor, fps=fps,
        rest_pitches=payload.get('footRestPitchRadians'),
        native_geometry=payload.get('nativeFootGeometry'), side_axes=heel_side_axes)
    if placement.get('version') == 1 and heel_contacts.pairs:
        shape = heel_contacts.targets.shape
        heel_contacts.targets = rotation.apply(heel_contacts.targets.reshape(-1, 3)).reshape(shape) - origin
    heel_error = float(np.max(np.linalg.norm(
        heel_contacts.residual(points, first, last, side_axes=(
            [playback_side_axes[names[ankle].split('_')[0]] for ankle, _ in heel_contacts.pairs]
            if key_material_axes is not None else None)), axis=-1), initial=0.))
    heel_frame_error = float(np.max(np.linalg.norm(heel_contacts.residual(originals, side_axes=(
        [key_material_axes[names[ankle].split('_')[0]] for ankle, _ in heel_contacts.pairs]
        if key_material_axes is not None else None)), axis=-1), initial=0.))
    contact_error = max(contact_error, heel_error)
    frame_contact_error = max(frame_contact_error, heel_frame_error)
    floor=payload.get('renderFloorY')
    floor_error=0. if floor is None else max(0.,float(floor)-float(points[:,:,1].min()))
    # Match keyframe anatomy authority: torso-bend floors follow the observed
    # articulation reference. For mid-samples, use the more flexed enclosing
    # keyframe so hermite interpolation of a legal hinge is not rejected.
    from .physical_validation import source_articulation_reference_field, _joint_array_from_frames
    source_field = source_articulation_reference_field(payload['frames'])
    articulation = _joint_array_from_frames(payload['frames'], source_field, names)
    if articulation is None:
        return {'passed': False, 'reason': 'fixed_rig_reference_unavailable',
                'physicalReasons': ['fixed_rig_reference_unavailable'], 'physicalEvents': []}
    anatomy_articulation = articulation
    if payload.get('anatomicalSourceRepair'):
        anatomy_articulation = np.asarray([
            [frame.get('correctedAnatomicalReferenceJoints', frame[source_field])[name] for name in names]
            for frame in payload['frames']], dtype=float)
    # The spatial support target is not anatomy authority. The actual stored
    # and dense candidate still face support readiness/geometry checks below.
    if (articulation.shape == (count, len(names), 3)
            and np.isfinite(articulation).all()):
        alpha = cursors - first
        reference_samples, _ = playback_reference_samples(articulation, first, last, alpha, names)
        _, anatomy_reference_samples = playback_reference_samples(
            anatomy_articulation, first, last, alpha, names)
        sample_pin = interpolated_contact_mask(pinned, first, last, anchor_ids)
        index = {name: i for i, name in enumerate(names)}
        foot_names = ('left_ankle', 'left_foot', 'right_ankle', 'right_foot')
        if all(name in index for name in foot_names):
            foot_idx = [index[name] for name in foot_names]
            support_mask = np.all(sample_pin[:, foot_idx], axis=1)
        else:
            support_mask = None
        physical = validate_physical_motion(
            points, names, reference=reference_samples,
            anatomy_reference=anatomy_reference_samples, fps=fps * subdivisions,
            support_mask=support_mask,
            direction_authority=source_hinge_direction_authority(payload, names)[first]
                & source_hinge_direction_authority(payload, names)[last])
    else:
        physical = validate_physical_motion(points, names, fps=fps * subdivisions)
    # Fixed-rig bone lengths are checked via maximumBoneLengthVariationMeters;
    # all source-relative articulation checks use the time-aligned reference.
    _playback_ignore = {'repair_bone_length_distortion'}
    # Keyframe anatomy is already gated on the exported joints. Hermite can
    # overshoot torso/spine residuals between accepted knots; reject structure
    # only when it also appears on the knot samples themselves.
    _structure_mid_only = {
        'anatomy_spine_deviation',
        'anatomy_torso_bend',
        'anatomy_spine_fold',
        'anatomy_chest_attachment',
        'anatomy_neck_fold',
    }
    knot_frames = set(range(0, len(points), subdivisions))
    physical = dict(physical)
    physical['events'] = [
        event for event in physical.get('events') or []
        if event.get('reason') not in _playback_ignore
        and not (
            event.get('reason') in _structure_mid_only
            and int(event.get('frameIndex', -1)) not in knot_frames
        )]
    physical['reasons'] = sorted({event['reason'] for event in physical['events']})
    physical['passed'] = not physical['events']
    variation=max(float(np.ptp(np.linalg.norm(points[:,j]-points[:,parent],axis=-1)))
                  for j,parent in enumerate(rig['parents']) if parent>=0)
    from .rig_interpolation import INTERPOLATION, LEGACY_INTERPOLATION
    velocity_jump = None
    seam_velocity_jump = None
    seam_velocity_limit = None
    velocity_continuous = True
    if cyclic:
        from .rig_interpolation import frame_boundary_velocity_jump
        seam_velocity_jump = frame_boundary_velocity_jump(
            lambda query: sample_rig(rig, query, wrap=True), [0], fps)
        if rig.get('interpolation') in (INTERPOLATION, LEGACY_INTERPOLATION):
            knots = np.arange(count)
            velocity_jump = frame_boundary_velocity_jump(
                lambda query: sample_rig(rig, query, wrap=True), knots, fps)
            velocity_continuous = velocity_jump < .001 * scale
            seam_velocity_limit = .001 * scale
        else:
            from .loop_seam import MAX_VELOCITY_MISMATCH_BODY_RATIO
            seam_velocity_limit = MAX_VELOCITY_MISMATCH_BODY_RATIO * scale
    elif rig.get('interpolation') in (INTERPOLATION, LEGACY_INTERPOLATION):
        from .rig_interpolation import frame_boundary_velocity_jump
        knots = np.arange(1, count-1)
        if len(knots):
            velocity_jump = frame_boundary_velocity_jump(
                lambda query: sample_rig(rig, query, wrap=False), knots, fps)
        velocity_continuous = velocity_jump is None or velocity_jump < .001 * scale
    from .loop_seam import seam_quality_metrics
    seam_metrics = seam_quality_metrics(
        originals, fps=fps, scale=scale, rendered_velocity_jump=seam_velocity_jump,
        rendered_velocity_limit=seam_velocity_limit)
    from .temporal_quality import track_discontinuity_metrics
    loop_motion = {'available': False, 'severe': False, 'events': []}
    if cyclic:
        repeated = np.concatenate((points, points), axis=0)
        loop_motion = track_discontinuity_metrics(
            {name: repeated[:, index].tolist() for index, name in enumerate(names)},
            root_joint='pelvis', fps=fps * subdivisions, body_height=scale)
        from .motion_placement import root_motion_quality
        loop_motion['rootContinuity'] = root_motion_quality(
            repeated[:, names.index('pelvis')], fps * subdivisions, scale)
        seam_metrics['seamContinuous'] &= (
            loop_motion.get('available') is True and not loop_motion.get('severe')
            and loop_motion['rootContinuity'].get('passed') is True)
    seam_safe = seam_metrics['seamContinuous']
    from .equipment_constraints import validate_grip
    equipment = validate_grip(points, names, payload.get('equipmentConstraints') or {})
    from .support_geometry import validate_support_geometry, validate_supported_shoe_orientation
    # Evaluate support both on exported knots and on the rendered path. Timed
    # contact evidence is mapped by cursor for dense samples; untimed observed
    # torso/hand geometry still receives its whole-clip check.
    stored_body_support = validate_support_geometry(payload, originals, names)
    dense_body_support = validate_support_geometry(
        payload, points, names, frame_positions=cursors)
    stored_shoe_orientation = validate_supported_shoe_orientation(payload)
    dense_shoe_orientation = validate_supported_shoe_orientation(
        payload, points=points, cursors=cursors)
    body_support = {
        **stored_body_support,
        'passed': stored_body_support.get('passed') is True
                  and dense_body_support.get('passed') is True,
        'densePlayback': dense_body_support,
    }
    shoe_orientation = {
        **stored_shoe_orientation,
        'passed': stored_shoe_orientation.get('passed') is True
                  and dense_shoe_orientation.get('passed') is True,
        'densePlayback': dense_shoe_orientation,
    }
    from .foot_geometry import (
        canonical_material_shoe_evidence, canonical_shoe_calibration_evidence,
        validate_material_shoes,
    )
    canonical_shoes = canonical_shoe_calibration_evidence(payload)
    canonical_material_shoes = canonical_material_shoe_evidence(payload, points, cursors)
    material_shoes = validate_material_shoes(
        payload, points, cursors, floor_limit=PLAYBACK_FLOOR_LIMIT_METERS,
        contact_limit=PLAYBACK_CONTACT_LIMIT_METERS)
    native_height_material = {
        'applicable': False, 'available': False, 'passed': True,
        'sampleCount': 0, 'storedFrameSampleCount': 0,
        'maximumErrorMeters': 0., 'storedFrameMaximumErrorMeters': 0.,
    }
    if (isinstance(contact_tracks, dict) and contact_tracks.get('version') == 2
            and any(str(episode.get('mode')) == 'verticalOnly'
                    for side in ('left', 'right')
                    for episode in (contact_tracks.get(side) or {}).get('episodes', []))):
        from .contact_interpolation import native_height_material_plane_residuals
        from .foot_geometry import _sample_material_foot_geometry, foot_scale_from_pose
        native_height_material['applicable'] = True
        material_scale = float(foot_scale_from_pose(originals[0], names))
        stored_geometry = _sample_material_foot_geometry(
            payload, np.arange(count, dtype=float), originals)
        _, stored_metrics = native_height_material_plane_residuals(
            originals, names, contact_tracks, np.arange(count, dtype=float),
            side_axes={side: values['lateral']
                       for side, values in stored_geometry.items()},
            native_geometry=payload.get('nativeFootGeometry'),
            foot_scale=material_scale, return_metrics=True)
        dense_geometry = _sample_material_foot_geometry(
            payload, cursors, points, side_axes_override=playback_side_axes)
        _, dense_metrics = native_height_material_plane_residuals(
            points, names, contact_tracks, cursors,
            side_axes={side: values['lateral']
                       for side, values in dense_geometry.items()},
            native_geometry=payload.get('nativeFootGeometry'),
            foot_scale=material_scale, return_metrics=True)
        stored_error = float(stored_metrics.get('maximumErrorMeters') or 0.)
        dense_error = float(dense_metrics.get('maximumErrorMeters') or 0.)
        native_height_material.update({
            'available': bool(stored_metrics.get('available')
                              and dense_metrics.get('available')),
            'storedFrameSampleCount': int(stored_metrics.get('sampleCount') or 0),
            'sampleCount': int(dense_metrics.get('sampleCount') or 0),
            'storedFrameMaximumErrorMeters': stored_error,
            'maximumErrorMeters': dense_error,
            'bySide': dense_metrics.get('bySide') or {},
            'storedFrameBySide': stored_metrics.get('bySide') or {},
        })
        native_height_material['passed'] = bool(
            native_height_material['available']
            and native_height_material['storedFrameSampleCount'] > 0
            and native_height_material['sampleCount'] > 0
            and stored_error <= PLAYBACK_FLOOR_LIMIT_METERS
            and dense_error <= PLAYBACK_FLOOR_LIMIT_METERS)
        # Native height-only ownership is the shoe material plane, not the
        # nominal foot joint. Feed it through the existing height-only metrics
        # so a suppressed (empty) joint mask cannot read as success.
        vertical_error = max(vertical_error, dense_error)
        frame_vertical_error = max(frame_vertical_error, stored_error)
    from .support_alignment import validate_payload_alignment
    alignment = validate_payload_alignment(payload, points, cursors)
    mirrored_arms = mirrored_arm_policy_evidence(payload, points)
    canonical_execution = canonical_execution_policy_evidence(
        payload, points, sample_positions=cursors, side_axes=playback_side_axes)
    passed=(sample_error<1e-7 and physical['passed'] and support_readiness['passed']
            and contact_error<=PLAYBACK_CONTACT_LIMIT_METERS
            and vertical_error<=PLAYBACK_FLOOR_LIMIT_METERS
            and frame_vertical_error<=PLAYBACK_FLOOR_LIMIT_METERS
            and floor_error<=PLAYBACK_FLOOR_LIMIT_METERS and variation<RIG_NUMERICAL_CONSISTENCY_METERS
            and equipment['passed'] and body_support['passed']
            and shoe_orientation['passed'] and material_shoes['passed'] and canonical_shoes['passed']
            and canonical_material_shoes['passed']
            and native_height_material['passed']
            and alignment['passed'] and mirrored_arms['passed']
            and canonical_execution['passed'] and velocity_continuous)
    return {'passed':bool(passed),'sampleCount':len(points),'subdivisions':subdivisions,
            'maximumSamplePoseMismatchMeters':sample_error,'maximumContactErrorMeters':contact_error,
            'maximumHeightOnlyContactErrorMeters':vertical_error,
            'maximumStoredFrameHeightOnlyContactErrorMeters':frame_vertical_error,
            'nativeHeightOnlyMaterialShoes': native_height_material,
            'maximumHeelContactErrorMeters':heel_error,
            'equipment': equipment,
            'bodySupport': body_support,
            'supportContactReadiness': support_readiness,
            'shoeOrientation': shoe_orientation,
            'materialShoes': material_shoes,
            'canonicalShoeCalibration': canonical_shoes,
            'canonicalMaterialShoes': canonical_material_shoes,
            'supportAlignment': alignment,
            'mirroredArms': mirrored_arms,
            'canonicalExecutionPolicy': canonical_execution,
            'loopMotionDiscontinuity': loop_motion,
            'interpolation': rig.get('interpolation', 'linear_slerp'),
            'maximumFrameBoundaryVelocityJumpMetersPerSecond': velocity_jump,
            'velocityContinuous': bool(velocity_continuous),
            'maximumStoredFrameContactErrorMeters':frame_contact_error,'maximumFloorPenetrationMeters':floor_error,
            'maximumBoneLengthVariationMeters':variation,'physicalReasons':physical['reasons'],
            'physicalEvents':physical['events'][:8], **seam_metrics,
            'loopTransition':'continuous' if seam_safe else 'requires_cycle_repair'}
