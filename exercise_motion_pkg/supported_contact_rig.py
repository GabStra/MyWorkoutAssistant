"""Encode support-corrected native foot material contacts into rig coordinates.

The helper operates on an existing :class:`controlled_motion.FixedRig`.  Only
the ankle and foot local rotations of a protected support side change; the hip,
knee and every untouched joint keep their incoming coordinates.  The returned
array is always a fresh copy of the input coordinates and is the sole result:
no duplicate point truth is stored.
"""

from __future__ import annotations

import numpy as np
from scipy.spatial.transform import Rotation

from .contact_interpolation import _solve_knee, project_supported_material_contact
from .support_geometry import _native_side_axes_for_coordinates
from .support_joint_tracks import (
    sample_support_joint_mask,
    validate_support_joint_tracks,
)

_NATIVE_TRACK_VERSION = 2
_SIDES = ('left', 'right')
_EPS = 1e-10
def _joint_index(rig, name):
    try:
        return rig.names.index(name)
    except ValueError as exc:
        raise ValueError(f'supported contact rig is missing joint {name}') from exc


def _material_frame(ankle, foot, axis):
    """Current axis-derived ankle/foot material frame and foot bone lengths."""
    bone = foot - ankle
    bone_length = np.linalg.norm(bone, axis=1)
    if np.any(bone_length <= _EPS):
        raise ValueError('native foot material frame has a zero-length foot bone')
    forward = bone / bone_length[:, None]
    lateral = axis - forward * np.sum(axis * forward, axis=1, keepdims=True)
    lateral_length = np.linalg.norm(lateral, axis=1)
    if np.any(lateral_length <= _EPS):
        raise ValueError('native foot material frame has an undefined lateral axis')
    lateral = lateral / lateral_length[:, None]
    up = np.cross(lateral, forward)
    return np.stack((forward, lateral, up), axis=2), bone_length


def _material_points(ankle, foot, axis, episode):
    """Material points from the current raw ankle/foot frame and cached offset."""
    frame, bone_length = _material_frame(ankle, foot, axis)
    if 'materialOffsetLocalMeters' not in episode or 'referenceLengthMeters' not in episode:
        raise ValueError('native foot material cache is incomplete')
    local = np.asarray(episode['materialOffsetLocalMeters'], dtype=float)
    if local.shape != (3,) or not np.isfinite(local).all():
        raise ValueError('native foot material offset is malformed')
    if np.all(np.abs(local) <= _EPS):
        raise ValueError('native foot material offset is undefined')
    reference = np.asarray(episode['referenceLengthMeters'], dtype=float)
    if reference.ndim == 0:
        reference = np.full(len(ankle), float(reference))
    if (reference.shape != (len(ankle),) or not np.isfinite(reference).all()
            or np.any(reference <= _EPS)):
        raise ValueError('native foot material reference length is invalid')
    offset = np.einsum('fij,j->fi', frame, local)
    offset *= (bone_length / reference)[:, None]
    return ankle + offset


def _episode_targets(episode, material):
    """Stationary episode target, or the closest point on its support plane."""
    target = episode.get('targetWorld')
    if target is not None:
        target = np.asarray(target, dtype=float)
        if target.shape != (3,) or not np.isfinite(target).all():
            raise ValueError('native foot material target is malformed')
        return np.broadcast_to(target, material.shape).copy()
    normal = np.asarray(episode.get('surfaceNormal', ()), dtype=float)
    offset = episode.get('planeOffsetMeters')
    if normal.shape != (3,) or not np.isfinite(normal).all() or offset is None:
        raise ValueError('native foot material episode has no target or support plane')
    normal_length = np.linalg.norm(normal)
    if normal_length <= _EPS:
        raise ValueError('native foot material support plane normal is undefined')
    normal = normal / normal_length
    offset = float(offset)
    if not np.isfinite(offset):
        raise ValueError('native foot material support plane offset is invalid')
    distance = material @ normal - offset
    return material - distance[:, None] * normal


def _shortest_rotations(source, target):
    """Per-row shortest proper rotations mapping target directions to source."""
    count = len(source)
    result = np.empty((count, 3, 3), dtype=float)
    for index in range(count):
        source_vector = source[index]
        target_vector = target[index]
        source_length = np.linalg.norm(source_vector)
        target_length = np.linalg.norm(target_vector)
        if source_length <= _EPS or target_length <= _EPS:
            raise ValueError('supported contact shin direction is undefined')
        result[index] = Rotation.align_vectors(
            (source_vector / source_length)[None, :],
            (target_vector / target_length)[None, :])[0].as_matrix()
    return result


def _episode_mask(track, episode, active, protected, frames, count):
    """Keys active on the foot, protected on the knee, and inside the episode."""
    start = int(episode.get('startFrame', 0))
    end = int(episode.get('endFrame', count - 1))
    mask = active & protected & (frames >= start) & (frames <= end)
    anchor_ids = track.get('anchorIds')
    anchor = episode.get('anchorId')
    if anchor_ids is not None and anchor is not None:
        anchor_ids = np.asarray(anchor_ids, dtype=object)
        if anchor_ids.shape != (count,):
            raise ValueError('native material anchor ids do not match the rig frame count')
        mask = mask & (anchor_ids == anchor)
    return mask


def _reachable_ankle(hip, ankle, target, material_radius, thigh_length, shin_length,
                     margin=0.002):
    """Closest ankle to ``ankle`` on the fixed-hip reach shell and toe sphere.

    A point material contact fixes the distance from the ankle to the target
    (the rigid shoe offset length). A fixed hip constrains the ankle to a
    spherical shell between the shortest and longest two-bone reach. Their
    intersection is the set of exactly contact-feasible ankles. Returning the
    point nearest the incoming ankle preserves the supplied articulation and
    leaves only the residual foot rotation to the shoe.
    """
    material_radius = np.asarray(material_radius, dtype=float)
    thigh_length = np.asarray(thigh_length, dtype=float)
    shin_length = np.asarray(shin_length, dtype=float)
    reach = target - hip
    distance = np.linalg.norm(reach, axis=1)
    if (np.any(distance <= _EPS) or np.any(material_radius <= _EPS)
            or np.any(thigh_length <= _EPS) or np.any(shin_length <= _EPS)):
        raise ValueError('point contact reach geometry is undefined')
    minimum = np.abs(thigh_length - shin_length) + margin
    maximum = thigh_length + shin_length - margin
    current = np.linalg.norm(ankle - hip, axis=1)
    # The toe sphere and the hip shell must intersect. Clamp to their overlap
    # rather than silently accepting a contact error.
    lower = np.maximum(minimum, np.abs(distance - material_radius) + 1e-6)
    upper = np.minimum(maximum, distance + material_radius - 1e-6)
    if np.any(lower >= upper):
        raise ValueError('point contact target is outside the fixed-hip reach')
    solved = np.clip(current, lower, upper)
    along = (solved ** 2 - material_radius ** 2 + distance ** 2) / (2. * distance)
    height_squared = solved ** 2 - along ** 2
    if np.any(height_squared < -1e-8):
        raise ValueError('point contact reach circle is invalid')
    height = np.sqrt(np.maximum(height_squared, 0.))
    axis = reach / distance[:, None]
    centre = hip + (along / distance)[:, None] * reach
    to_ankle = ankle - centre
    perpendicular = to_ankle - axis * np.sum(to_ankle * axis, axis=1, keepdims=True)
    perpendicular_length = np.linalg.norm(perpendicular, axis=1)
    fallback = np.cross(axis, np.array([1., 0., 0.]))
    fallback_length = np.linalg.norm(fallback, axis=1)
    second = np.cross(axis, np.array([0., 0., 1.]))
    fallback = np.where(
        fallback_length[:, None] > _EPS,
        fallback / np.maximum(fallback_length[:, None], _EPS),
        second / np.maximum(np.linalg.norm(second, axis=1, keepdims=True), _EPS))
    perpendicular = np.where(
        perpendicular_length[:, None] > _EPS,
        perpendicular / np.maximum(perpendicular_length[:, None], _EPS),
        fallback)
    sign = np.sign(np.sum(to_ankle * perpendicular, axis=1))
    sign = np.where(sign == 0., 1., sign)
    return centre + height[:, None] * perpendicular * sign[:, None]


def _distributed_point_contact(rig, q, points, old_world, rows, side, episode,
                               side_axes, hip, knee, ankle, foot,
                               knee_slot, ankle_slot, foot_slot):
    """Pin a point shoe contact by distributing reach across the leg chain.

    The legacy point projection keeps the current knee as a hard pivot, so the
    entire toe-target correction becomes an ankle/foot rotation. When the knee
    is only a transient kinematic pivot (no observed support) and the supplied
    pose already carries source articulation, that concentration can exceed the
    source-relative ankle repair budget even though a feasible leg pose exists.
    This path moves the ankle to the nearest point where the rigid shoe offset
    reaches the target and the fixed hip can still reach, then rotates the shoe
    the remaining amount and re-solves the knee. Contact stays exact while no
    single distal joint absorbs the whole repair.
    """
    current_ankle = points[rows, ankle]
    current_foot = points[rows, foot]
    current_knee = points[rows, knee]
    hip_points = points[rows, hip]
    material = _material_points(current_ankle, current_foot, side_axes[rows], episode)
    target = _episode_targets(episode, material)
    if np.max(np.linalg.norm(target - material, axis=1)) <= 1e-9:
        return
    material_radius = np.linalg.norm(material - current_ankle, axis=1)
    thigh_length = np.linalg.norm(current_knee - hip_points, axis=1)
    shin_length = np.linalg.norm(current_ankle - current_knee, axis=1)
    new_ankle = _reachable_ankle(
        hip_points, current_ankle, target, material_radius,
        thigh_length, shin_length)
    source_offset = material - current_ankle
    target_offset = target - new_ankle
    rotations = np.empty((len(rows), 3, 3), dtype=float)
    for index, (source, destination) in enumerate(zip(source_offset, target_offset)):
        source_length = np.linalg.norm(source)
        destination_length = np.linalg.norm(destination)
        if source_length <= _EPS or destination_length <= _EPS:
            raise ValueError('distributed point contact shoe offset is undefined')
        # align_vectors(a, b) maps b onto a, so pass the target first.
        rotations[index] = Rotation.align_vectors(
            (destination / destination_length)[None, :],
            (source / source_length)[None, :])[0].as_matrix()
    new_knee = _solve_knee(
        hip_points, current_knee, current_ankle, new_ankle,
        thigh_length, shin_length, side)
    knee_rotation = _shortest_rotations(new_knee - hip_points,
                                        current_knee - hip_points)
    new_knee_world = np.einsum('fij,fjk->fik', knee_rotation,
                               old_world[knee][rows])
    q[rows, knee_slot:knee_slot + 3] = Rotation.from_matrix(
        np.einsum('fji,fjk->fik', old_world[hip][rows],
                  new_knee_world)).as_rotvec()
    shin_rotation = _shortest_rotations(new_ankle - new_knee,
                                        current_ankle - current_knee)
    new_ankle_world = np.einsum('fij,fjk->fik', shin_rotation,
                                old_world[ankle][rows])
    q[rows, ankle_slot:ankle_slot + 3] = Rotation.from_matrix(
        np.einsum('fji,fjk->fik', new_knee_world,
                  new_ankle_world)).as_rotvec()
    new_foot_world = np.einsum('fij,fjk->fik', rotations,
                               old_world[foot][rows])
    q[rows, foot_slot:foot_slot + 3] = Rotation.from_matrix(
        np.einsum('fji,fjk->fik', new_ankle_world,
                  new_foot_world)).as_rotvec()


def _apply_side(rig, q, points, side_axes, track, support_tracks, frames,
                count, old_world, side, *, current_knee_pivot=False):
    """Encode corrected ankle/foot rotations for one disjoint body side."""
    active = np.asarray(track.get('active', ()), dtype=bool)
    if active.shape != (count,):
        raise ValueError(f'{side} native material track does not match the rig frame count')
    episodes = track.get('episodes') or ()
    if not isinstance(episodes, (list, tuple)):
        raise ValueError(f'{side} native material episodes are malformed')
    if not episodes:
        return

    hip = _joint_index(rig, f'{side}_hip')
    knee = _joint_index(rig, f'{side}_knee')
    ankle = _joint_index(rig, f'{side}_ankle')
    foot = _joint_index(rig, f'{side}_foot')
    for joint, label in ((knee, 'knee'), (ankle, 'ankle'), (foot, 'foot')):
        if joint not in rig.slots:
            raise ValueError(f'supported contact rig cannot rotate the {side} {label}')
    ankle_slot = rig.slots[ankle]
    knee_slot = rig.slots[knee]
    foot_slot = rig.slots[foot]

    # The native material episode owns the shoe surface point. It must not
    # become an additional fixed foot-joint pin; only independently observed
    # stationary knee support protects this proximal point.
    observed_knee = sample_support_joint_mask(
        support_tracks, f'{side}_knee', frames, count)
    protected = active.copy() if current_knee_pivot else active & observed_knee
    if not protected.any():
        return

    ankles = points[:, ankle]
    feet = points[:, foot]
    knees = points[:, knee]
    for episode in episodes:
        if not isinstance(episode, dict):
            raise ValueError(f'{side} native material episode is malformed')
        mask = _episode_mask(track, episode, active, protected, frames, count)
        rows = np.flatnonzero(mask)
        if len(rows) == 0:
            continue
        if (str(episode.get('regionRole')) != 'full_sole'
                and str(episode.get('mode')) == 'stationary'
                and not np.any(observed_knee[rows])):
            try:
                _distributed_point_contact(
                    rig, q, points, old_world, rows, side, episode, side_axes,
                    hip, knee, ankle, foot, knee_slot, ankle_slot, foot_slot)
            except ValueError:
                # No reachable distributed solution: retain the legacy
                # fixed-knee projection, which keeps the contact exact.
                pass
            else:
                continue
        current_ankle = ankles[rows]
        current_foot = feet[rows]
        current_knee = knees[rows]
        axis = side_axes[rows]
        material = _material_points(current_ankle, current_foot, axis, episode)
        target = _episode_targets(episode, material)
        material_normal = target_normal = None
        sole_local = episode.get('soleNormalLocalMeters')
        if (str(episode.get('regionRole')) == 'full_sole'
                and str(episode.get('mode')) == 'stationary'
                and sole_local is not None):
            frame, _ = _material_frame(current_ankle, current_foot, axis)
            local_normal = np.asarray(sole_local, dtype=float)
            material_normal = np.einsum('fij,j->fi', frame, local_normal)
            target_normal = np.broadcast_to(
                np.asarray(episode['surfaceNormal'], dtype=float),
                material_normal.shape).copy()
        new_ankle, _, _, rotation = project_supported_material_contact(
            current_knee, current_ankle, current_foot, material, target, axis, side,
            material_normal=material_normal, target_normal=target_normal)
        old_ankle_world = old_world[ankle][rows]
        old_foot_world = old_world[foot][rows]
        if material_normal is not None:
            # A full sole is a physical material patch, so the reconstructed
            # knee is re-solved from the fixed hip: only the thigh/shin/foot bone
            # lengths are preserved, not the artefactual knee position.
            from .contact_interpolation import _solve_knee
            hip_points = points[rows, hip]
            thigh_length = np.linalg.norm(current_knee - hip_points, axis=1)
            shin_length = np.linalg.norm(current_ankle - current_knee, axis=1)
            try:
                new_knee = _solve_knee(hip_points, current_knee, current_ankle,
                                       new_ankle, thigh_length, shin_length, side)
            except ValueError:
                # A flat, anchored sole can need more reach than the observed
                # hip allows (a root/placement conflict outside this per-frame
                # encoder). Fail back to the legacy point projection rather than
                # clamp or fabricate reach; the full-sole geometry gate remains
                # authoritative for reporting.
                material_normal = None
                new_ankle, _, _, rotation = project_supported_material_contact(
                    current_knee, current_ankle, current_foot, material, target,
                    axis, side)
                new_knee = None
            if new_knee is not None:
                knee_rotation = _shortest_rotations(new_knee - hip_points,
                                                    current_knee - hip_points)
                new_knee_world = np.einsum('fij,fjk->fik', knee_rotation,
                                           old_world[knee][rows])
                q[rows, knee_slot:knee_slot + 3] = Rotation.from_matrix(
                    np.einsum('fji,fjk->fik', old_world[hip][rows],
                              new_knee_world)).as_rotvec()
                shin_rotation = _shortest_rotations(new_ankle - new_knee,
                                                    current_ankle - current_knee)
                new_ankle_world = np.einsum('fij,fjk->fik', shin_rotation,
                                            old_ankle_world)
                q[rows, ankle_slot:ankle_slot + 3] = Rotation.from_matrix(
                    np.einsum('fji,fjk->fik', new_knee_world,
                              new_ankle_world)).as_rotvec()
            else:
                shin_rotation = _shortest_rotations(new_ankle - current_knee,
                                                    current_ankle - current_knee)
                new_ankle_world = np.einsum('fij,fjk->fik', shin_rotation,
                                            old_ankle_world)
                q[rows, ankle_slot:ankle_slot + 3] = Rotation.from_matrix(
                    np.einsum('fji,fjk->fik', old_world[knee][rows],
                              new_ankle_world)).as_rotvec()
        else:
            shin_rotation = _shortest_rotations(new_ankle - current_knee,
                                                current_ankle - current_knee)
            new_ankle_world = np.einsum('fij,fjk->fik', shin_rotation,
                                        old_ankle_world)
            q[rows, ankle_slot:ankle_slot + 3] = Rotation.from_matrix(
                np.einsum('fji,fjk->fik', old_world[knee][rows],
                          new_ankle_world)).as_rotvec()
        new_foot_world = np.einsum('fij,fjk->fik', rotation, old_foot_world)
        q[rows, foot_slot:foot_slot + 3] = Rotation.from_matrix(
            np.einsum('fji,fjk->fik', new_ankle_world, new_foot_world)).as_rotvec()


def project_supported_native_foot_coordinates(rig, coordinates, native_tracks,
                                              support_tracks, *,
                                              current_knee_pivot=False):
    """Return a corrected coordinate copy for protected native foot support.

    Only ankle/foot local rotations of a side with a native v2 track and a foot
    and knee protected by ``support_tracks`` are rewritten. With
    ``current_knee_pivot=True``, the decoded per-frame knee is a transient
    kinematic pivot for initialization; it does not add a stationary support
    observation. Absent native tracks and legacy input return an unchanged copy.
    """
    q = np.asarray(coordinates, dtype=float).copy()
    if q.ndim != 2 or q.shape[1] != rig.width:
        raise ValueError('rig coordinates must have shape (frames, rig.width)')
    if not np.isfinite(q).all():
        raise ValueError('rig coordinates must be finite')
    count = len(q)
    if count == 0:
        return q
    if (not isinstance(native_tracks, dict)
            or native_tracks.get('version') != _NATIVE_TRACK_VERSION):
        return q
    raw_support_tracks = support_tracks or {}
    if current_knee_pivot and not raw_support_tracks:
        # An empty transient mask describes no observed support. It only lets
        # the caller use each current knee as a per-frame geometric pivot.
        raw_support_tracks = {
            'version': 1, 'source': 'validated_stationary_body_support', 'joints': {},
        }
    support_tracks = validate_support_joint_tracks(
        raw_support_tracks, rig.names, count)
    side_axes = _native_side_axes_for_coordinates(
        rig, q, {'_nativeFootMaterialTracks': native_tracks})
    if not side_axes:
        return q
    frames = np.arange(count)
    old_world = rig.global_rotations(q)
    points = rig.decode(q)
    for side in _SIDES:
        track = native_tracks.get(side)
        if not isinstance(track, dict) or side not in side_axes:
            continue
        _apply_side(rig, q, points, side_axes[side], track, support_tracks,
                    frames, count, old_world, side,
                    current_knee_pivot=bool(current_knee_pivot))
    return q


def _canonical_fixed_rig(rig, coordinates):
    """Fixed-rig serialization expected by the canonical projection."""
    return {
        'jointNames': list(rig.names),
        'parents': list(rig.parents),
        'offsets': np.asarray(rig.offsets, dtype=float).tolist(),
        'order': list(rig.order),
        'rotationJointNames': [rig.names[j] for j in rig.active],
        'coordinates': np.asarray(coordinates, dtype=float).tolist(),
    }


_LEG_CHAIN_PARTS = ('hip', 'knee', 'ankle', 'foot')
# The production pose-policy playback gate uses this exact tolerance. Coupling
# is only allowed to restore a source pair that already satisfies it.
_MIRROR_PAIR_TOLERANCE_METERS = 0.0005


def _mirrored_legs_are_in_phase(rig, coordinates):
    """Whether the supplied clip is already an in-phase mirrored leg pair.

    ``canonical_bilateral_reference`` performs a zero-phase mirror. An in-phase
    mirrored source is a fixed point, so its residual measures both static
    asymmetry and anti-phase (alternating) motion. A clip with a residual above
    the pose-policy tolerance must keep its independent per-frame articulation.
    """
    from .controlled_motion import canonical_bilateral_reference

    points = rig.decode(np.asarray(coordinates, dtype=float))
    reference = canonical_bilateral_reference(
        points, rig.names, {'legs': 'mirrored'})
    leg_joints = [rig.names.index(f'{side}_{part}')
                  for side in _SIDES for part in _LEG_CHAIN_PARTS
                  if f'{side}_{part}' in rig.names]
    if len(leg_joints) != 2 * len(_LEG_CHAIN_PARTS):
        raise ValueError('mirrored leg coupling requires complete bilateral leg chains')
    residual = np.linalg.norm(points[:, leg_joints] - reference[:, leg_joints], axis=-1)
    return float(np.max(residual)) <= _MIRROR_PAIR_TOLERANCE_METERS


def mirrored_leg_coupling_authority(rig, coordinates, native_tracks, execution,
                                    source_contact_pinned):
    """Source-owned leg that may be mirrored, or ``None`` (fail closed).

    Coupling is a post-projection restoration of a declared in-phase mirrored
    pair, never a general symmetry rule. It is declined when:

    * the policy is not ``legs: mirrored``;
    * neither source pin set nor native track identifies exactly one owner;
    * the opposite chain owns any source pin, native episode or active frame
      (bilateral or partially observed opposite contact must stay independent);
    * the supplied pre-projection clip is not already an in-phase mirror pair
      (anti-phase/alternating or legitimately asymmetric motion is preserved).
    """
    q = np.asarray(coordinates, dtype=float)
    if q.ndim != 2 or q.shape[1] != rig.width or not np.isfinite(q).all():
        raise ValueError('rig coordinates must be a finite (frames, rig.width) array')
    execution = execution or {}
    if execution.get('legs') != 'mirrored':
        return None
    if (not isinstance(native_tracks, dict)
            or native_tracks.get('version') != _NATIVE_TRACK_VERSION):
        return None
    if source_contact_pinned is None:
        return None
    from .support_alignment import authoritative_mirror_sides

    authority = authoritative_mirror_sides(
        source_contact_pinned, rig.names, execution).get('legs')
    if authority not in _SIDES:
        return None
    owning_track = native_tracks.get(authority)
    if not isinstance(owning_track, dict):
        return None
    active = np.asarray(owning_track.get('active', ()), dtype=bool)
    if active.shape != (len(q),) or not active.any():
        return None
    other_side = 'right' if authority == 'left' else 'left'
    other_track = native_tracks.get(other_side)
    if isinstance(other_track, dict):
        other_active = np.asarray(other_track.get('active', ()), dtype=bool)
        if other_active.shape != (len(q),) or other_active.any():
            # Both chains own observed native material contacts (or the opposite
            # ownership is malformed); they are not a mirror pair and must keep
            # their independent physical targets.
            return None
        if other_track.get('episodes'):
            # Episodes without a currently active frame are still observed
            # articulation somewhere in the clip; never overwrite them.
            return None
    if not _mirrored_legs_are_in_phase(rig, q):
        return None
    return authority


def _couple_from_authority(rig, coordinates, execution, authority):
    from .canonical_rig_projection import exact_canonical_coordinates

    return exact_canonical_coordinates(
        _canonical_fixed_rig(rig, coordinates), execution,
        authoritative_sides={'legs': authority})


def couple_mirrored_native_foot_projection(rig, coordinates, native_tracks,
                                           execution, source_contact_pinned, *,
                                           original_coordinates=None):
    """Restore the declared mirrored leg policy after a one-sided foot projection.

    ``original_coordinates`` is the pre-projection clip used to verify the
    source pair. When omitted, ``coordinates`` itself must be the in-phase pair;
    post-projection asymmetry alone therefore never authorizes a whole-clip copy.
    """
    q = np.asarray(coordinates, dtype=float).copy()
    original = q if original_coordinates is None else np.asarray(
        original_coordinates, dtype=float)
    authority = mirrored_leg_coupling_authority(
        rig, original, native_tracks, execution, source_contact_pinned)
    if authority is None:
        return q
    return _couple_from_authority(rig, q, execution, authority)


def canonicalize_after_native_foot_projection(rig, coordinates, execution,
                                              leg_authority):
    """Apply the remaining canonical policy without bypassing the coupling decision.

    The production fit re-projects the fixed rig after the native foot
    projection to restore torso/arm representation. Previously that call also
    re-mirrored the legs unconditionally, defeating the coupling guard and
    averaging bilateral contacts. Here leg mirroring is applied only for the
    authority returned by ``mirrored_leg_coupling_authority``; otherwise the
    legs keep their independent projected pose while torso/arms still project.
    """
    q = np.asarray(coordinates, dtype=float).copy()
    if q.ndim != 2 or q.shape[1] != rig.width or not np.isfinite(q).all():
        raise ValueError('rig coordinates must be a finite (frames, rig.width) array')
    canonical_execution = dict(execution or {})
    if canonical_execution.get('legs') == 'mirrored' and leg_authority not in _SIDES:
        canonical_execution.pop('legs')
    if not canonical_execution:
        return q
    from .canonical_rig_projection import exact_canonical_coordinates

    return exact_canonical_coordinates(
        _canonical_fixed_rig(rig, q), canonical_execution,
        authoritative_sides={'legs': leg_authority} if leg_authority in _SIDES else None)


def project_coupled_native_foot_coordinates(rig, coordinates, native_tracks,
                                            support_tracks, *, execution,
                                            source_contact_pinned,
                                            current_knee_pivot=False):
    """Native supported-foot projection followed by safe mirrored-leg coupling."""
    original = np.asarray(coordinates, dtype=float)
    authority = mirrored_leg_coupling_authority(
        rig, original, native_tracks, execution, source_contact_pinned)
    projected = project_supported_native_foot_coordinates(
        rig, coordinates, native_tracks, support_tracks,
        current_knee_pivot=current_knee_pivot)
    if authority is None or np.array_equal(projected, original):
        # Nothing was projected, or the source is not a one-sided in-phase
        # mirrored pair, so there is no safe whole-clip correction to apply.
        return projected
    return _couple_from_authority(rig, projected, execution, authority)


def project_mirrored_native_foot_axes(rig, coordinates, native_tracks):
    """Bake the rendered inferred foot-axis gauge into the unsupported foot q.

    Exact-key frames with exactly one active native foot preserve that physical
    side's world axis and rotate only the opposite foot about its own bone. This
    makes the model-inferred axis agree with the sampler's mirrored-axis rule
    without changing any joint point or source contact authority.
    """
    q = np.asarray(coordinates, dtype=float).copy()
    if q.ndim != 2 or q.shape[1] != rig.width:
        raise ValueError('rig coordinates must have shape (frames, rig.width)')
    if not np.isfinite(q).all():
        raise ValueError('rig coordinates must be finite')
    count = len(q)
    if count == 0 or (not isinstance(native_tracks, dict)
                      or type(native_tracks.get('version')) is not int
                      or native_tracks.get('version') != _NATIVE_TRACK_VERSION):
        return q

    active_by_side, evidence_tracks = {}, {'version': _NATIVE_TRACK_VERSION}
    for side in _SIDES:
        track = native_tracks.get(side)
        if track is None:
            continue
        active = np.asarray(track.get('active', ()))
        if active.dtype != np.dtype(bool) or active.shape != (count,):
            raise ValueError(f'{side} native material active mask is invalid')
        axes = np.asarray(track.get('sideAxes', ()), dtype=float)
        if axes.ndim != 2 or axes.shape[1] != 3 or len(axes) != count or not np.isfinite(axes).all():
            raise ValueError(f'{side} native material side axes are invalid')
        active_by_side[side] = active
        evidence_tracks[side] = {'sideAxes': axes}
    if not active_by_side or any(side not in evidence_tracks for side in _SIDES):
        return q
    left_active = active_by_side.get('left', np.zeros(count, dtype=bool))
    right_active = active_by_side.get('right', np.zeros(count, dtype=bool))
    unilateral = left_active ^ right_active
    if not np.any(unilateral):
        return q

    axes = _native_side_axes_for_coordinates(
        rig, q, {'_nativeFootMaterialTracks': evidence_tracks})
    if not axes or any(side not in axes for side in _SIDES):
        return q
    points = rig.decode(q)
    old_world = rig.global_rotations(q)
    left_hip = _joint_index(rig, 'left_hip')
    right_hip = _joint_index(rig, 'right_hip')
    feet = {side: _joint_index(rig, f'{side}_foot') for side in _SIDES}
    ankles = {side: _joint_index(rig, f'{side}_ankle') for side in _SIDES}
    for side in _SIDES:
        if feet[side] not in rig.slots:
            raise ValueError(f'mirrored native foot axis requires a rotatable {side} foot')

    for row in np.flatnonzero(unilateral):
        active_side = 'left' if left_active[row] else 'right'
        inferred_side = 'right' if active_side == 'left' else 'left'
        hip_delta = points[row, right_hip] - points[row, left_hip]
        hip_length = float(np.linalg.norm(hip_delta))
        if hip_length <= _EPS:
            raise ValueError('mirrored native foot axes require distinct hip anchors')
        normal = hip_delta / hip_length

        def project_axis(axis, side):
            bone = points[row, feet[side]] - points[row, ankles[side]]
            bone_length = float(np.linalg.norm(bone))
            if bone_length <= _EPS:
                raise ValueError(f'{side} native foot axis has a zero-length bone')
            forward = bone / bone_length
            lateral = axis - forward * float(np.dot(axis, forward))
            lateral_length = float(np.linalg.norm(lateral))
            if lateral_length <= _EPS:
                raise ValueError(f'{side} native foot axis is collinear with its bone')
            return lateral / lateral_length, forward

        active_axis, _ = project_axis(axes[active_side][row], active_side)
        current_axis, forward = project_axis(axes[inferred_side][row], inferred_side)
        reflected = active_axis - 2. * normal * float(np.dot(active_axis, normal))
        desired_axis, _ = project_axis(-reflected, inferred_side)
        angle = float(np.arctan2(
            np.dot(forward, np.cross(current_axis, desired_axis)),
            np.clip(np.dot(current_axis, desired_axis), -1., 1.)))
        if abs(angle) <= 1e-12:
            continue

        foot = feet[inferred_side]
        ankle = ankles[inferred_side]
        slot = rig.slots[foot]
        world_swing = Rotation.from_rotvec(forward * angle).as_matrix()
        new_foot_world = world_swing @ old_world[foot][row]
        parent_world = old_world[ankle][row]
        new_local = parent_world.T @ new_foot_world
        q[row, slot:slot + 3] = Rotation.from_matrix(new_local).as_rotvec()
    return q
