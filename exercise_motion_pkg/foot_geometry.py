"""Calibrated ankle-to-forefoot bones and material shoe support points."""
from contextlib import contextmanager
from contextvars import ContextVar
import numpy as np

from .contact_constraints import (
    contact_frame_bounds, motion_support_contacts, observed_ground_contact_mask,
)

SHOE_LENGTH_RATIO = 1.15
_SHOE_ORIENTATION_CONTEXT = ContextVar('shoe_orientation_context', default=None)


def _build_shoe_orientation_context(payload, evidence=None):
    from .contact_constraints import (
        fit_frame_foot_patch_states_by_side, motion_space_support_evidence,
        observed_ground_contact_mask,
    )
    frames, names = payload.get('frames') or [], payload.get('jointNames') or []
    evidence = evidence if isinstance(evidence, dict) else motion_space_support_evidence(payload)
    states = fit_frame_foot_patch_states_by_side(evidence, len(frames))
    ground = observed_ground_contact_mask(evidence, names, len(frames))
    if ground.shape != (len(frames), len(names)):
        ground = np.zeros((len(frames), len(names)), dtype=bool)
    body_support = evidence.get('bodySupport') or payload.get('bodySupport') or {}
    support_geometry = (body_support if body_support.get('status') == 'confirmed'
                        else evidence if evidence.get('status') == 'confirmed' else {})
    return {'states': states, 'ground': ground,
            'planeGroups': support_geometry.get('coplanarGroups') or [],
            'evidence': evidence}


@contextmanager
def shoe_orientation_context(context):
    token = _SHOE_ORIENTATION_CONTEXT.set(context)
    try:
        yield
    finally:
        _SHOE_ORIENTATION_CONTEXT.reset(token)


def calibrated_foot_rest_pitches(points, names, evidence, frame_times=None):
    """Only timed, observed full-sole ground samples define each rig-side neutral."""
    points = np.asarray(points, dtype=float)
    from .contact_constraints import (
        fit_frame_foot_patch_states_by_side,
        contact_frame_bounds, is_observed_ground_contact, is_stationary_contact,
        mapped_foot_patch_state_indices, motion_support_contacts,
    )

    patch = (evidence or {}).get('footPatchEvidence') or {}
    states_by_side = (patch.get('feet') or {}) if patch.get('available') is True else {}
    contacts = motion_support_contacts(evidence)
    result = {}
    for side in ('left', 'right'):
        ankle, toe = f'{side}_ankle', f'{side}_foot'
        if ankle not in names or toe not in names:
            continue
        flat = np.zeros(len(points), dtype=bool)
        for contact in contacts:
            if (contact.get('jointName') != toe
                    or contact.get('contactState') != 'full_sole'
                    or not is_stationary_contact(contact)
                    or not is_observed_ground_contact(contact, evidence)):
                continue
            start, end = contact_frame_bounds(contact, len(points))
            flat[start:end + 1] = True
        # The body-support anchor is an even stronger ground authority than a
        # loose contact interval, so do not drop its pitch samples. When a
        # temporal patch exists, still require every sampled frame to be an
        # explicit full-sole state; unknown, heel/toe-only and airborne samples
        # never enter a neutral-pitch estimate.
        patch_foot = states_by_side.get(side) if isinstance(states_by_side, dict) else None
        patch_states = patch_foot.get('states') if isinstance(patch_foot, dict) else None
        if isinstance(patch_states, list) and patch_states:
            fit_states = fit_frame_foot_patch_states_by_side(evidence, len(points))
            aligned_states = fit_states.get(side)
            if aligned_states is not None:
                explicit_full_sole = np.asarray([
                    state == 'full_sole' for state in aligned_states
                ], dtype=bool)
            else:
                source_times = frame_times if frame_times is not None else [None] * len(points)
                state_indexes = mapped_foot_patch_state_indices(
                    evidence, source_times, frame_count=len(points))
                explicit_full_sole = np.asarray([
                    index >= 0 and index < len(patch_states)
                    and str(patch_states[index]).casefold() == 'full_sole'
                    for index in state_indexes
                ], dtype=bool)
            flat &= explicit_full_sole
        vector = points[:, names.index(toe)] - points[:, names.index(ankle)]
        length = np.linalg.norm(vector, axis=-1)
        flat &= length > 1e-8
        if np.count_nonzero(flat) >= 3:
            result[side] = float(np.median(np.arcsin(np.clip(vector[flat, 1] / length[flat], -1., 1.))))
    return result


def material_foot_points(ankle, toe, side, rest_pitch, orientation=None):
    """Mirror wearShoe/addShoe: rotate out the bind pitch, pivot at the forefoot."""
    vector = np.asarray(toe) - np.asarray(ankle)
    length = np.linalg.norm(vector, axis=-1, keepdims=True)
    forward = vector / np.maximum(length, 1e-12)
    lateral = np.asarray(side) - forward * np.sum(np.asarray(side) * forward, axis=-1, keepdims=True)
    lateral /= np.maximum(np.linalg.norm(lateral, axis=-1, keepdims=True), 1e-12)
    up = np.cross(lateral, forward)
    sole_forward = forward * np.cos(rest_pitch) - up * np.sin(rest_pitch)
    if orientation is not None:
        sole_forward = np.asarray(orientation['forward'], dtype=float)
        lateral = np.asarray(orientation['side'], dtype=float)
    return np.asarray(toe) - SHOE_LENGTH_RATIO * length * sole_forward, np.asarray(toe)


def shoe_vertices(ankle, toe, side, rest_pitch, foot_scale, orientation=None):
    """The production shoe's three beveled rings and two tips, in vertex order."""
    heel, toe = material_foot_points(ankle, toe, side, rest_pitch, orientation)
    length = np.linalg.norm(toe - ankle, axis=-1, keepdims=True)
    forward = (np.asarray(orientation['forward'], dtype=float) if orientation is not None
               else (toe - heel) / np.maximum(SHOE_LENGTH_RATIO * length, 1e-12))
    side_axis = np.asarray(orientation['side'], dtype=float) if orientation is not None else np.asarray(side)
    lateral = side_axis - forward * np.sum(side_axis * forward, axis=-1, keepdims=True)
    lateral /= np.maximum(np.linalg.norm(lateral, axis=-1, keepdims=True), 1e-12)
    up = np.cross(lateral, forward)
    width = np.maximum(length * .26, foot_scale * .15)
    height = np.maximum(length * .28, foot_scale * .15)
    rings = []
    for fraction, center_height, width_scale, height_scale in (
            (0., -.05, .78, .55), (.36, .12, 1., .72), (1., -.25, .76, .35)):
        center = heel + forward * (SHOE_LENGTH_RATIO * length * fraction) + up * height * (center_height + .60)
        w, h = lateral * width * width_scale, up * height * height_scale
        top_width = w * .88
        corners = np.stack([center + top_width + h, center - top_width + h,
                            center - w - h, center + w - h], axis=-2)
        ring = np.stack([corners * .7 + np.roll(corners, shift, axis=-2) * .3
                         for shift in (1, -1)], axis=-2).reshape(*corners.shape[:-2], 8, 3)
        rings.append(ring)
    rear_tip = (rings[0][..., 0, :] + rings[0][..., 4, :]) * .5 - forward * height * .20
    toe_tip = (rings[-1][..., 0, :] + rings[-1][..., 4, :]) * .5 + forward * height * .20
    return np.concatenate([*rings, rear_tip[..., None, :], toe_tip[..., None, :]], axis=-2)


def free_foot_floor_translation(ankle, toe, *, floor_y, rest_pitch_radians,
                                foot_scale, side_axis):
    """Return the smallest upward shift that clears the rendered shoe from floor."""
    ankle, toe = np.asarray(ankle, dtype=float), np.asarray(toe, dtype=float)
    side_axis = np.asarray(side_axis, dtype=float)
    values = (ankle, toe, side_axis)
    if any(value.shape != (3,) or not np.isfinite(value).all() for value in values):
        raise ValueError('foot geometry inputs must be finite 3D vectors')
    try:
        floor_y, rest_pitch_radians, foot_scale = map(
            float, (floor_y, rest_pitch_radians, foot_scale))
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError('floor, pitch, and scale must be finite numbers') from error
    foot_forward = toe - ankle
    foot_length_squared = float(np.dot(foot_forward, foot_forward))
    if (not np.isfinite([floor_y, rest_pitch_radians, foot_scale]).all()
            or foot_scale <= 0. or foot_length_squared <= 1e-16):
        raise ValueError('floor, pitch, scale, and foot axes must be valid')
    side_projection = side_axis - foot_forward * (
        np.dot(side_axis, foot_forward) / foot_length_squared)
    if np.linalg.norm(side_projection) <= 1e-8:
        raise ValueError('floor, pitch, scale, and foot axes must be valid')
    lowest = float(shoe_vertices(
        ankle, toe, side_axis, rest_pitch_radians, foot_scale)[:, 1].min())
    return max(0., floor_y - lowest)


def foot_scale_from_pose(points, names):
    def span(a, b):
        return np.linalg.norm(points[names.index(a)] - points[names.index(b)]) if a in names and b in names else 0.
    return max(span('left_hip', 'right_hip') * .98, span('left_shoulder', 'right_shoulder') * .58)


def material_floor_heights(points, names, rest_pitches, foot_scale, side_axes):
    """Replace ankle floor rows with shoes oriented by rendered bone sides."""
    heights = points[:, :, 1].copy()
    for side in ('left', 'right'):
        if f'{side}_ankle' not in names or f'{side}_foot' not in names:
            continue
        pitch = float(rest_pitches.get(side, 0.))
        ankle, toe = names.index(f'{side}_ankle'), names.index(f'{side}_foot')
        value = side_axes[side]
        lateral = np.asarray(value.get('lateral') if isinstance(value, dict) else value,
                             dtype=float)
        orientation = value.get('orientation') if isinstance(value, dict) else None
        vertices = shoe_vertices(points[:, ankle], points[:, toe], lateral, pitch, foot_scale,
                                 orientation=orientation)
        heights[:, ankle] = np.minimum(heights[:, ankle], np.min(vertices[:, :, 1], axis=1))
    return heights


def _sample_material_foot_geometry(payload, cursors, points, *, resolved_sides=None,
                                   keyframe_points=None):
    """Resolve rendered shoe heel/toe points and side axes at rig samples."""
    from .temporal_quality import rendered_leg_sides

    frames, names = payload['frames'], payload['jointNames']
    cursors = np.asarray(cursors, dtype=float).reshape(-1)
    points = np.asarray(points, dtype=float)
    if points.shape != (len(cursors), len(names), 3):
        raise ValueError('sampled points must have shape (len(cursors), joint_count, 3)')
    if keyframe_points is None:
        keyframe_points = np.asarray([
            [frame['joints'][name] for name in names] for frame in frames
        ], dtype=float)
    else:
        keyframe_points = np.asarray(keyframe_points, dtype=float)
    if keyframe_points.shape != (len(frames), len(names), 3):
        raise ValueError('keyframe points must match frame and joint counts')
    resolved = (rendered_leg_sides(frames) if resolved_sides is None
                else resolved_sides)
    first = np.floor(cursors).astype(int)
    last = np.ceil(cursors).astype(int) % len(frames)
    alpha = cursors - first
    pitches = payload.get('footRestPitchRadians') or {}
    orientation_tracks = shoe_orientation_tracks(
        payload, keyframe_points, resolved_sides=resolved)
    stored_keyframe_points = np.asarray([
        [frame['joints'][name] for name in names] for frame in frames
    ], dtype=float)
    if (np.allclose(keyframe_points, stored_keyframe_points, rtol=0., atol=1e-9)
            and frames and all(isinstance(frame.get('shoeOrientation'), dict)
                               for frame in frames)):
        for side in ('left', 'right'):
            if all(isinstance(frame['shoeOrientation'].get(side), dict)
                   and {'forward', 'side'} <= set(frame['shoeOrientation'][side])
                   for frame in frames):
                orientation_tracks[side] = {
                    'forward': _unit_rows(np.asarray([
                        frame['shoeOrientation'][side]['forward'] for frame in frames
                    ], dtype=float)),
                    'side': _unit_rows(np.asarray([
                        frame['shoeOrientation'][side]['side'] for frame in frames
                    ], dtype=float)),
                }
    result = {}
    for side in ('left', 'right'):
        ankle_name, toe_name = f'{side}_ankle', f'{side}_foot'
        if ankle_name not in names or toe_name not in names:
            continue
        ankle, toe = names.index(ankle_name), names.index(toe_name)
        key = f'{ankle_name}->{toe_name}'
        resolved_lateral = np.asarray([
            resolved[index].get(key, frame.get('boneSides', {}).get(key, [0., 0., 1.]))
            for index, frame in enumerate(frames)
        ], dtype=float)
        lateral = (resolved_lateral[first] * (1. - alpha[:, None])
                   + resolved_lateral[last] * alpha[:, None])
        exported = np.asarray([
            key in frames[a].get('boneSides', {}) and key in frames[b].get('boneSides', {})
            for a, b in zip(first, last)
        ], dtype=bool)
        exported_rows = np.flatnonzero(exported)
        if exported_rows.size:
            a, b = first[exported_rows], last[exported_rows]
            sample_vector = points[exported_rows, toe] - points[exported_rows, ankle]
            sample_axis = sample_vector / np.maximum(
                np.linalg.norm(sample_vector, axis=1, keepdims=True), 1e-12)

            def endpoint_side(endpoint):
                source_axis = np.asarray([
                    np.asarray(frames[index]['joints'][toe_name], dtype=float)
                    - np.asarray(frames[index]['joints'][ankle_name], dtype=float)
                    for index in endpoint
                ])
                source_axis /= np.maximum(
                    np.linalg.norm(source_axis, axis=1, keepdims=True), 1e-12)
                candidate_axis = keyframe_points[endpoint, toe] - keyframe_points[endpoint, ankle]
                candidate_axis /= np.maximum(
                    np.linalg.norm(candidate_axis, axis=1, keepdims=True), 1e-12)
                source_side = np.asarray([
                    frames[index]['boneSides'][key] for index in endpoint
                ], dtype=float)
                source_side -= source_axis * np.sum(
                    source_side * source_axis, axis=1, keepdims=True)
                source_side /= np.maximum(
                    np.linalg.norm(source_side, axis=1, keepdims=True), 1e-12)
                candidate_side = transport_sides(
                    source_side, source_axis, candidate_axis, source_side)
                return transport_sides(
                    candidate_side, candidate_axis, sample_axis,
                    lateral[exported_rows].copy())

            start_side, end_side = endpoint_side(a), endpoint_side(b)
            angle = np.arctan2(
                np.sum(sample_axis * np.cross(start_side, end_side), axis=1),
                np.sum(start_side * end_side, axis=1),
            ) * alpha[exported_rows]
            lateral[exported_rows] = (
                start_side * np.cos(angle)[:, None]
                + np.cross(sample_axis, start_side) * np.sin(angle)[:, None]
            )
        orientation = _sample_orientation_track(orientation_tracks.get(side), first, last, alpha)
        material_side = orientation['side'] if orientation is not None else lateral
        heel, forefoot = material_foot_points(
            points[:, ankle], points[:, toe], material_side, float(pitches.get(side, 0.)),
            orientation=orientation)
        result[side] = {'heel': heel, 'toe': forefoot, 'lateral': material_side,
                        'forward': (orientation['forward'] if orientation else None),
                        'orientation': orientation}
    return result


def _unit_rows(values, fallback=None):
    values = np.asarray(values, dtype=float)
    lengths = np.linalg.norm(values, axis=-1, keepdims=True)
    if fallback is None:
        fallback = np.zeros_like(values)
        fallback[..., 0] = 1.
    fallback = np.asarray(fallback, dtype=float)
    return np.where(lengths > 1e-10, values / np.maximum(lengths, 1e-10), fallback)


def _sample_orientation_track(track, first, last, alpha):
    if track is None:
        return None
    forward = track['forward'][first] * (1. - alpha[:, None]) + track['forward'][last] * alpha[:, None]
    side = track['side'][first] * (1. - alpha[:, None]) + track['side'][last] * alpha[:, None]
    forward = _unit_rows(forward)
    side -= forward * np.sum(side * forward, axis=1, keepdims=True)
    side = _unit_rows(side)
    # Keep an orthonormal right-handed frame after cursor interpolation.
    side = _unit_rows(np.cross(forward, np.cross(side, forward)))
    return {'forward': forward, 'side': side}


def shoe_orientation_tracks(payload, points, *, resolved_sides=None):
    """Build material shoe axes from verified full-sole states and preserve free pitch.

    Only timed full-sole observations with a verified ground plane constrain the
    sole normal. Between those anchors, the original/calibrated foot pitch is
    retained and the material side is minimally transported with the foot axis.
    """
    points = np.asarray(points, dtype=float)
    frames, names = payload.get('frames') or [], payload.get('jointNames') or []
    if points.shape != (len(frames), len(names), 3):
        raise ValueError('shoe orientation points must match payload frame/joint shape')
    context = _SHOE_ORIENTATION_CONTEXT.get()
    if context is None or context['ground'].shape != (len(frames), len(names)):
        context = _build_shoe_orientation_context(payload)
    states, ground = context['states'], context['ground']
    floor = payload.get('renderFloorY')
    mode = str(payload.get('groundContactMode') or '').casefold()
    plane_groups = context['planeGroups']
    from .temporal_quality import rendered_leg_sides
    resolved = rendered_leg_sides(frames) if resolved_sides is None else resolved_sides
    pitches = payload.get('footRestPitchRadians') or {}
    result = {}
    for side in ('left', 'right'):
        ankle_name, toe_name = f'{side}_ankle', f'{side}_foot'
        if ankle_name not in names or toe_name not in names:
            continue
        ankle, toe = names.index(ankle_name), names.index(toe_name)
        bone_forward = _unit_rows(points[:, toe] - points[:, ankle])
        key = f'{ankle_name}->{toe_name}'
        fallback_side = np.asarray([
            resolved[i].get(key, frame.get('boneSides', {}).get(key, [0., 0., 1.]))
            for i, frame in enumerate(frames)
        ], dtype=float)
        fallback_side -= bone_forward * np.sum(fallback_side * bone_forward, axis=1, keepdims=True)
        fallback_side = _unit_rows(fallback_side)
        up = _unit_rows(np.cross(fallback_side, bone_forward))
        pitch = float(pitches.get(side, 0.))
        free_forward = _unit_rows(bone_forward * np.cos(pitch) - up * np.sin(pitch))
        side_axis = fallback_side.copy()
        forward = free_forward.copy()
        side_states = states.get(side, ())
        full = np.asarray([str(state).casefold() == 'full_sole' for state in side_states], dtype=bool)
        if full.shape != (len(frames),):
            full = np.zeros(len(frames), dtype=bool)
        normal = None
        side_names = {ankle_name, toe_name}
        for group in plane_groups:
            if (set(group.get('joints') or ()) & side_names
                    and 'normal' in group and 'planeOffsetMeters' in group):
                candidate_normal = np.asarray(group.get('normal'), dtype=float)
                if (candidate_normal.shape == (3,) and np.isfinite(candidate_normal).all()
                        and np.linalg.norm(candidate_normal) > 1e-8):
                    normal = candidate_normal / np.linalg.norm(candidate_normal)
                    break
        ground_plane = floor is not None and mode in {'continuous', 'intermittent'}
        if normal is None and ground_plane:
            normal = np.array([0., 1., 0.])
            grounded = (ground[:, toe] if ground.shape == (len(frames), len(names))
                        else np.zeros(len(frames), dtype=bool))
        elif normal is not None:
            grounded = np.ones(len(frames), dtype=bool)
        else:
            continue
        contact = full & grounded
        anchors = np.flatnonzero(contact)
        if not anchors.size:
            continue
        for index in anchors:
            projected = bone_forward[index] - normal * np.dot(bone_forward[index], normal)
            if np.linalg.norm(projected) <= 1e-8:
                continue
            forward[index] = projected / np.linalg.norm(projected)
            side_axis[index] = np.cross(forward[index], normal)
            side_axis[index] /= max(np.linalg.norm(side_axis[index]), 1e-12)
        valid_anchors = np.flatnonzero(contact & np.isfinite(forward).all(axis=1))
        for index in np.flatnonzero(~contact):
            before = valid_anchors[valid_anchors < index]
            after = valid_anchors[valid_anchors > index]
            left = int(before[-1]) if before.size else None
            right = int(after[0]) if after.size else None
            if left is not None and right is not None:
                start = transport_sides(
                    side_axis[left:left + 1], forward[left:left + 1],
                    free_forward[index:index + 1], fallback_side[index:index + 1])[0]
                end = transport_sides(
                    side_axis[right:right + 1], forward[right:right + 1],
                    free_forward[index:index + 1], fallback_side[index:index + 1])[0]
                amount = (index - left) / max(right - left, 1)
                angle = np.arctan2(
                    np.dot(free_forward[index], np.cross(start, end)),
                    np.dot(start, end))
                side_axis[index] = start * np.cos(amount * angle) + np.cross(
                    free_forward[index], start) * np.sin(amount * angle)
            else:
                anchor = left if left is not None else right
                side_axis[index] = transport_sides(
                    side_axis[anchor:anchor + 1], forward[anchor:anchor + 1],
                    free_forward[index:index + 1], fallback_side[index:index + 1])[0]
        # Contact rows are exact plane frames; free rows preserve the measured
        # pitch and event timing, while transporting only the material side.
        forward[~contact] = free_forward[~contact]
        side_axis -= forward * np.sum(side_axis * forward, axis=1, keepdims=True)
        side_axis = _unit_rows(side_axis)
        result[side] = {'forward': forward, 'side': side_axis,
                        'contactMask': contact}
    return result


def transport_sides(sides, old_axes, new_axes, fallback):
    """Vectorized minimal bone-frame transport for sampled shoe axes."""
    sides = np.asarray(sides, dtype=float)
    old_axes = np.asarray(old_axes, dtype=float)
    new_axes = np.asarray(new_axes, dtype=float)
    fallback = np.asarray(fallback, dtype=float).copy()
    cosine = np.clip(np.sum(old_axes * new_axes, axis=1), -1., 1.)
    cross = np.cross(old_axes, new_axes)
    cross_side = np.cross(cross, sides)
    denominator = np.maximum(1. + cosine, 1e-12)
    transported = sides + cross_side + np.cross(cross, cross_side) / denominator[:, None]
    transported -= new_axes * np.sum(transported * new_axes, axis=1, keepdims=True)
    length = np.linalg.norm(transported, axis=1, keepdims=True)
    fallback -= new_axes * np.sum(fallback * new_axes, axis=1, keepdims=True)
    fallback_length = np.linalg.norm(fallback, axis=1, keepdims=True)
    use_fallback = (cosine < -0.999999) | (length[:, 0] <= 1e-8) | ~np.isfinite(length[:, 0])
    transported = np.where(use_fallback[:, None], fallback, transported)
    length = np.where(use_fallback[:, None], fallback_length, length)
    return transported / np.maximum(length, 1e-12)


def sample_material_foot_points(payload, cursors, *, points=None):
    """Return production-rendered material heel and toe positions at cursors.

    ``points`` is an optional candidate keyframe track with shape
    ``(frame_count, joint_count, 3)``. Candidate positions are linearly
    interpolated at each cursor; without it, the serialized fixed rig is
    sampled with the same interpolation as playback.
    """
    cursors = np.asarray(cursors, dtype=float).reshape(-1)
    wrap = bool((payload.get('loop') or {}).get('enabled'))
    if points is None:
        from .rig_playback import sample_rig
        points = sample_rig(
            payload['fixedRig'], cursors, wrap=wrap)
    else:
        points = np.asarray(points, dtype=float)
        frame_count = len(payload['frames'])
        if points.shape != (frame_count, len(payload['jointNames']), 3):
            raise ValueError('candidate points must have shape (frame_count, joint_count, 3)')
        if frame_count:
            cursors = np.mod(cursors, frame_count) if wrap else np.clip(cursors, 0., frame_count - 1.)
            first = np.floor(cursors).astype(int)
            last = (first + 1) % frame_count if wrap else np.minimum(first + 1, frame_count - 1)
            amount = cursors - first
            points = points[first] * (1. - amount[:, None, None]) + points[last] * amount[:, None, None]
    geometry = _sample_material_foot_geometry(payload, cursors, points)
    return {side: {'heel': values['heel'], 'toe': values['toe'],
                   'sideAxis': values['lateral'], 'forwardAxis': values['forward']}
            for side, values in geometry.items()}


def validate_material_shoes(payload, points, cursors, *, floor_limit, contact_limit):
    """Check material soles at the same interpolated poses as rig playback."""
    pitches = payload.get('footRestPitchRadians') or {}
    floor = payload.get('renderFloorY')
    if floor is None:
        return {'required': False, 'passed': True}
    from .contact_constraints import motion_space_support_evidence
    frames, names = payload['frames'], payload['jointNames']
    geometry = _sample_material_foot_geometry(payload, cursors, points)
    first = np.floor(cursors).astype(int)
    last = np.ceil(cursors).astype(int) % len(frames)
    evidence = motion_space_support_evidence(payload)
    ground = observed_ground_contact_mask(evidence, names, len(frames))
    full = np.zeros_like(ground)
    for contact in motion_support_contacts(evidence):
        if contact.get('contactState') == 'full_sole' and contact.get('jointName') in names:
            start, end = contact_frame_bounds(contact, len(frames))
            full[start:end + 1, names.index(contact['jointName'])] = True
    scale = foot_scale_from_pose(np.asarray([frames[0]['joints'][n] for n in names]), names)
    penetration, contact_error = 0., 0.
    for side in ('left', 'right'):
        if side not in geometry:
            continue
        pitch = float(pitches.get(side, 0.))
        ankle, toe = names.index(f'{side}_ankle'), names.index(f'{side}_foot')
        axes = geometry[side]['lateral']
        vertices = shoe_vertices(points[:, ankle], points[:, toe], axes, pitch, scale,
                                 orientation=geometry[side]['orientation'])
        penetration = max(penetration, float(floor) - float(vertices[:, :, 1].min()))
        active = (full[first, toe] & full[last, toe] & ground[first, toe] & ground[last, toe])
        if np.any(active):
            heel, forefoot = geometry[side]['heel'], geometry[side]['toe']
            contact_error = max(contact_error, float(np.max(np.abs(
                np.stack([heel[active, 1], forefoot[active, 1]]) - float(floor)))))
    return {'required': True, 'passed': penetration <= floor_limit and contact_error <= contact_limit,
            'maximumSurfacePenetrationMeters': max(0., penetration),
            'maximumFullSoleContactErrorMeters': contact_error}
