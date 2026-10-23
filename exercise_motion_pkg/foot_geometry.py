"""Calibrated ankle-to-forefoot bones and material shoe support points."""
import numpy as np

from .contact_constraints import (
    contact_frame_bounds, motion_support_contacts, observed_ground_contact_mask,
)

SHOE_LENGTH_RATIO = 1.15


def calibrated_foot_rest_pitches(points, names, evidence, frame_times=None):
    """Only timed, observed full-sole ground samples define each rig-side neutral."""
    points = np.asarray(points, dtype=float)
    from .contact_constraints import (
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


def material_foot_points(ankle, toe, side, rest_pitch):
    """Mirror wearShoe/addShoe: rotate out the bind pitch, pivot at the forefoot."""
    vector = np.asarray(toe) - np.asarray(ankle)
    length = np.linalg.norm(vector, axis=-1, keepdims=True)
    forward = vector / np.maximum(length, 1e-12)
    lateral = np.asarray(side) - forward * np.sum(np.asarray(side) * forward, axis=-1, keepdims=True)
    lateral /= np.maximum(np.linalg.norm(lateral, axis=-1, keepdims=True), 1e-12)
    up = np.cross(lateral, forward)
    sole_forward = forward * np.cos(rest_pitch) - up * np.sin(rest_pitch)
    return np.asarray(toe) - SHOE_LENGTH_RATIO * length * sole_forward, np.asarray(toe)


def shoe_vertices(ankle, toe, side, rest_pitch, foot_scale):
    """The production shoe's three beveled rings and two tips, in vertex order."""
    heel, toe = material_foot_points(ankle, toe, side, rest_pitch)
    length = np.linalg.norm(toe - ankle, axis=-1, keepdims=True)
    forward = (toe - heel) / np.maximum(SHOE_LENGTH_RATIO * length, 1e-12)
    lateral = np.asarray(side) - forward * np.sum(np.asarray(side) * forward, axis=-1, keepdims=True)
    lateral /= np.maximum(np.linalg.norm(lateral, axis=-1, keepdims=True), 1e-12)
    up = np.cross(lateral, forward)
    width = np.maximum(length * .26, foot_scale * .15)
    height = np.maximum(length * .28, foot_scale * .15)
    rings = []
    for fraction, center_height, width_scale, height_scale in (
            (0., -.05, .78, .55), (.36, .12, 1., .72), (1., -.25, .76, .35)):
        center = heel + forward * (SHOE_LENGTH_RATIO * length * fraction) + up * height * (center_height + .60)
        w, h = lateral * width * width_scale, up * height * height_scale
        corners = np.stack([center + w + h, center - w + h,
                            center - w - h, center + w - h], axis=-2)
        ring = np.stack([corners * .7 + np.roll(corners, shift, axis=-2) * .3
                         for shift in (1, -1)], axis=-2).reshape(*corners.shape[:-2], 8, 3)
        rings.append(ring)
    rear_tip = (rings[0][..., 0, :] + rings[0][..., 4, :]) * .5 - forward * height * .20
    toe_tip = (rings[-1][..., 0, :] + rings[-1][..., 4, :]) * .5 + forward * height * .20
    return np.concatenate([*rings, rear_tip[..., None, :], toe_tip[..., None, :]], axis=-2)


def foot_scale_from_pose(points, names):
    def span(a, b):
        return np.linalg.norm(points[names.index(a)] - points[names.index(b)]) if a in names and b in names else 0.
    return max(span('left_hip', 'right_hip') * .98, span('left_shoulder', 'right_shoulder') * .58)


def material_floor_heights(points, names, rest_pitches, foot_scale):
    """Replace ankle floor rows with the lowest material shoe surface."""
    heights = points[:, :, 1].copy()
    for side, pitch in rest_pitches.items():
        ankle, toe = names.index(f'{side}_ankle'), names.index(f'{side}_foot')
        lateral = np.cross(points[:, toe] - points[:, ankle], [0., 1., 0.])
        vertices = shoe_vertices(points[:, ankle], points[:, toe], lateral, pitch, foot_scale)
        heights[:, ankle] = np.minimum(heights[:, ankle], np.min(vertices[:, :, 1], axis=1))
    return heights


def _sample_material_foot_geometry(payload, cursors, points):
    """Resolve rendered shoe heel/toe points and side axes at rig samples."""
    from .temporal_quality import rendered_leg_sides, transport_side

    frames, names = payload['frames'], payload['jointNames']
    cursors = np.asarray(cursors, dtype=float).reshape(-1)
    points = np.asarray(points, dtype=float)
    if points.shape != (len(cursors), len(names), 3):
        raise ValueError('sampled points must have shape (len(cursors), joint_count, 3)')
    resolved = rendered_leg_sides(frames)
    first = np.floor(cursors).astype(int)
    last = np.ceil(cursors).astype(int) % len(frames)
    alpha = cursors - first
    pitches = payload.get('footRestPitchRadians') or {}
    result = {}
    for side in ('left', 'right'):
        ankle_name, toe_name = f'{side}_ankle', f'{side}_foot'
        if ankle_name not in names or toe_name not in names:
            continue
        ankle, toe = names.index(ankle_name), names.index(toe_name)
        key = f'{ankle_name}->{toe_name}'
        axes = []
        for row, (a, b, amount) in enumerate(zip(first, last, alpha)):
            lateral = (np.asarray(resolved[a][key]) * (1. - amount)
                       + np.asarray(resolved[b][key]) * amount)
            if key in frames[a].get('boneSides', {}) and key in frames[b].get('boneSides', {}):
                vector = points[row, toe] - points[row, ankle]
                axis = vector / max(np.linalg.norm(vector), 1e-12)
                ends = []
                for frame in (frames[a], frames[b]):
                    old = np.asarray(frame['joints'][toe_name]) - frame['joints'][ankle_name]
                    old /= max(np.linalg.norm(old), 1e-12)
                    ends.append(transport_side(np.asarray(frame['boneSides'][key]), old, axis))
                angle = np.arctan2(np.dot(axis, np.cross(*ends)), np.dot(*ends)) * amount
                lateral = ends[0] * np.cos(angle) + np.cross(axis, ends[0]) * np.sin(angle)
            axes.append(lateral)
        lateral = np.asarray(axes)
        heel, forefoot = material_foot_points(
            points[:, ankle], points[:, toe], lateral, float(pitches.get(side, 0.)))
        result[side] = {'heel': heel, 'toe': forefoot, 'lateral': lateral}
    return result


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
                   'sideAxis': values['lateral']}
            for side, values in geometry.items()}


def validate_material_shoes(payload, points, cursors, *, floor_limit, contact_limit):
    """Check material soles at the same interpolated poses as rig playback."""
    pitches = payload.get('footRestPitchRadians') or {}
    floor = payload.get('renderFloorY')
    if not pitches or floor is None:
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
    for side, pitch in pitches.items():
        ankle, toe = names.index(f'{side}_ankle'), names.index(f'{side}_foot')
        axes = geometry[side]['lateral']
        vertices = shoe_vertices(points[:, ankle], points[:, toe], axes, pitch, scale)
        penetration = max(penetration, float(floor) - float(vertices[:, :, 1].min()))
        active = (full[first, toe] & full[last, toe] & ground[first, toe] & ground[last, toe])
        if np.any(active):
            heel, forefoot = geometry[side]['heel'], geometry[side]['toe']
            contact_error = max(contact_error, float(np.max(np.abs(
                np.stack([heel[active, 1], forefoot[active, 1]]) - float(floor)))))
    return {'required': True, 'passed': penetration <= floor_limit and contact_error <= contact_limit,
            'maximumSurfacePenetrationMeters': max(0., penetration),
            'maximumFullSoleContactErrorMeters': contact_error}
