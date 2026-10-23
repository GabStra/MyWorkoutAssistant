"""Contact-aware fixed-rig sampling that preserves closed leg chains."""

from __future__ import annotations

import numpy as np

from .rig_interpolation import hermite_samples


def build_contact_foot_tracks(rig, keypoints, pinned_mask):
    """Build immutable world-space toe and direction tracks for pinned feet."""
    names = list(rig.names if hasattr(rig, 'names') else rig['jointNames'])
    points = np.asarray(keypoints, dtype=float)
    pinned = np.asarray(pinned_mask, dtype=bool)
    if points.ndim != 3 or points.shape[1:] != (len(names), 3):
        raise ValueError('keypoints must have shape (frames, joints, 3)')
    if pinned.shape != points.shape[:2]:
        raise ValueError('pinned_mask must have shape (frames, joints)')
    if not np.isfinite(points).all():
        raise ValueError('keypoints contain non-finite values')

    tracks = {}
    for side in ('left', 'right'):
        joint_names = [f'{side}_{part}' for part in ('hip', 'knee', 'ankle', 'foot')]
        if any(name not in names for name in joint_names):
            continue
        ankle_index, toe_index = names.index(f'{side}_ankle'), names.index(f'{side}_foot')
        bone = points[:, toe_index] - points[:, ankle_index]
        lengths = np.linalg.norm(bone, axis=1)
        if np.any(lengths <= 1e-9):
            raise ValueError(f'{side} foot track contains a zero-length ankle-to-toe vector')
        active = pinned[:, toe_index]
        tracks[side] = {
            'active': active.tolist(),
            'toes': points[:, toe_index].tolist(),
            'directions': (bone / lengths[:, None]).tolist(),
        }
    return {'version': 1, **tracks}


def _validated_side_track(track, count, side):
    if not isinstance(track, dict) or not {'active', 'toes', 'directions'} <= track.keys():
        raise ValueError(f'{side} contact foot track is malformed')
    raw_active = np.asarray(track['active'])
    if raw_active.dtype != np.dtype(bool):
        raise ValueError(f'{side} contact foot active states must be booleans')
    active = raw_active
    toes = np.asarray(track['toes'], dtype=float)
    directions = np.asarray(track['directions'], dtype=float)
    if active.shape != (count,) or toes.shape != (count, 3) or directions.shape != (count, 3):
        raise ValueError(f'{side} contact foot track has incompatible frame dimensions')
    if not np.isfinite(toes).all() or not np.isfinite(directions).all():
        raise ValueError(f'{side} contact foot track contains non-finite values')
    lengths = np.linalg.norm(directions, axis=1)
    if np.any(lengths <= 1e-9) or not np.allclose(lengths, 1., atol=1e-4, rtol=1e-4):
        raise ValueError(f'{side} contact foot directions must be normalized')
    return active, toes, directions / lengths[:, None]


def _sample_leg_track(track, first, last, alpha, *, wrap, smooth_limiter):
    active, toes, directions = track
    toe_targets = hermite_samples(
        toes, first, last, alpha, wrap=wrap, smooth_limiter=smooth_limiter)
    raw_yaw = np.arctan2(directions[:, 0], directions[:, 2])
    if wrap:
        count = len(raw_yaw)
        yaw = np.unwrap(np.tile(raw_yaw, 3))[:, None]
        yaw_first, yaw_last = first + count, last + count
        yaw_last = yaw_last + (last <= first) * count
        yaw_wrap = False
    else:
        yaw = np.unwrap(raw_yaw)[:, None]
        yaw_first, yaw_last = first, last
        yaw_wrap = False
    pitch = np.arctan2(directions[:, 1], np.linalg.norm(directions[:, [0, 2]], axis=1))[:, None]
    sampled_yaw = hermite_samples(
        yaw, yaw_first, yaw_last, alpha, wrap=yaw_wrap,
        smooth_limiter=smooth_limiter)[:, 0]
    sampled_pitch = hermite_samples(
        pitch, first, last, alpha, wrap=wrap, smooth_limiter=smooth_limiter)[:, 0]
    world_direction = np.column_stack((
        np.cos(sampled_pitch) * np.sin(sampled_yaw),
        np.sin(sampled_pitch),
        np.cos(sampled_pitch) * np.cos(sampled_yaw),
    ))

    start_active, end_active = active[first], active[last]
    smooth = alpha * alpha * (3. - 2. * alpha)
    weight = np.where(start_active & end_active, 1.,
                      np.where(start_active, 1. - smooth,
                               np.where(end_active, smooth, 0.)))
    return toe_targets, world_direction, weight


def _solve_knee(hip, knee, ankle, target_ankle, thigh_length, shin_length, side):
    """Reach the ankle with exact two-bone lengths and transported knee pole."""
    from .foot_kinematics import _transport_knee_poles

    thigh = np.full(len(hip), float(thigh_length))
    shin = np.full(len(hip), float(shin_length))
    reach = target_ankle - hip
    distance = np.linalg.norm(reach, axis=1)
    minimum = np.abs(thigh - shin)
    maximum = thigh + shin
    reachable = ((distance > 1e-9)
                 & (distance >= minimum - 1e-8)
                 & (distance <= maximum + 1e-8))
    if not np.all(reachable):
        indexes = np.flatnonzero(~reachable)
        raise ValueError(f'{side} contact foot IK is unreachable at samples {indexes[:8].tolist()}')

    axis = reach / distance[:, None]
    along = (thigh**2 - shin**2 + distance**2) / (2. * distance)
    height_squared = thigh**2 - along**2
    if np.any(height_squared < -1e-8):
        indexes = np.flatnonzero(height_squared < -1e-8)
        raise ValueError(f'{side} contact foot IK has invalid knee geometry at samples {indexes[:8].tolist()}')

    source_axes = ankle - hip
    source_axis_lengths = np.linalg.norm(source_axes, axis=1)
    source_axes /= np.maximum(source_axis_lengths[:, None], 1e-12)
    raw_thigh = knee - hip
    poles = raw_thigh - source_axes * np.sum(raw_thigh * source_axes, axis=1, keepdims=True)
    pole_lengths = np.linalg.norm(poles, axis=1)
    pole_defined = (source_axis_lengths > 1e-9) & (pole_lengths > 1e-9)
    unchanged_ankle = np.linalg.norm(target_ankle - ankle, axis=1) <= 1e-9
    if np.any(~pole_defined & ~unchanged_ankle):
        indexes = np.flatnonzero(~pole_defined & ~unchanged_ankle)
        raise ValueError(f'{side} contact foot IK needs an undefined source knee pole at samples {indexes[:8].tolist()}')
    poles /= np.maximum(pole_lengths[:, None], 1e-12)
    transported = _transport_knee_poles(poles, ankle - hip, reach)
    bend = transported - axis * np.sum(transported * axis, axis=1, keepdims=True)
    bend_length = np.linalg.norm(bend, axis=1)
    if np.any((bend_length <= 1e-9) & ~unchanged_ankle):
        indexes = np.flatnonzero((bend_length <= 1e-9) & ~unchanged_ankle)
        raise ValueError(f'{side} contact foot IK has an undefined knee bend plane at samples {indexes[:8].tolist()}')
    bend /= np.maximum(bend_length[:, None], 1e-12)
    solved = hip + axis * along[:, None] + bend * np.sqrt(np.maximum(height_squared, 0.))[:, None]
    return np.where(unchanged_ankle[:, None], knee, solved)


def sample_contact_foot_tracks(rig, cursors, points, *, wrap=False, preserve_keys=True):
    """Apply optional contact foot tracks to already sampled fixed-rig points.

    Exact key samples are returned unchanged. Between keys, a contacted toe
    follows a C1 world-space Hermite track while ankle and knee are rebuilt as
    a rigid, branch-preserving two-bone chain.
    """
    tracks = rig.get('contactFootTracks')
    if tracks is None:
        return np.asarray(points, dtype=float).copy()
    if not isinstance(tracks, dict) or tracks.get('version') != 1:
        raise ValueError('contactFootTracks has an unsupported or malformed version')

    cursors = np.asarray(cursors, dtype=float).reshape(-1)
    count = len(rig.get('coordinates', ()))
    names = list(rig['jointNames'])
    if count < 2 or not np.isfinite(cursors).all():
        raise ValueError('contact foot sampling requires finite cursors and at least two rig frames')
    sampled = np.asarray(points, dtype=float).copy()
    if sampled.shape != (len(cursors), len(names), 3) or not np.isfinite(sampled).all():
        raise ValueError('sampled points must have shape (queries, joints, 3) and be finite')

    normalized = np.mod(cursors, count) if wrap else np.clip(cursors, 0., count - 1.)
    first = np.floor(normalized).astype(int)
    last = (first + 1) % count if wrap else np.minimum(first + 1, count - 1)
    alpha = normalized - first
    exact_key = np.isclose(normalized, np.round(normalized), atol=1e-12, rtol=0.)
    smooth_limiter = rig.get('interpolation') != 'limited_quaternion_hermite_v1'
    offsets = np.asarray(rig['offsets'], dtype=float)

    for side in ('left', 'right'):
        if side not in tracks:
            continue
        indices = {part: names.index(f'{side}_{part}') if f'{side}_{part}' in names else None
                   for part in ('hip', 'knee', 'ankle', 'foot')}
        if any(index is None for index in indices.values()):
            raise ValueError(f'{side} contact foot track requires a complete hip-knee-ankle-foot chain')
        track = _validated_side_track(tracks[side], count, side)
        target_toe, target_direction, weight = _sample_leg_track(
            track, first, last, alpha, wrap=wrap, smooth_limiter=smooth_limiter)
        active_queries = (weight > 0.) & (~exact_key | (not preserve_keys))
        if not np.any(active_queries):
            continue

        hip_index, knee_index = indices['hip'], indices['knee']
        ankle_index, toe_index = indices['ankle'], indices['foot']
        base_toe = sampled[:, toe_index].copy()
        toe = base_toe + weight[:, None] * (target_toe - base_toe)
        base_direction = sampled[:, toe_index] - sampled[:, ankle_index]
        base_length = np.linalg.norm(base_direction, axis=1)
        if np.any(base_length[active_queries] <= 1e-9):
            raise ValueError(f'{side} sampled contact foot has a zero-length direction')
        base_direction /= np.maximum(base_length[:, None], 1e-12)
        direction = (1. - weight[:, None]) * base_direction + weight[:, None] * target_direction
        direction_length = np.linalg.norm(direction, axis=1)
        if np.any(direction_length[active_queries] <= 1e-9):
            raise ValueError(f'{side} sampled contact foot direction is undefined')
        direction /= np.maximum(direction_length[:, None], 1e-12)

        foot_length = float(np.linalg.norm(offsets[toe_index]))
        thigh_length = float(np.linalg.norm(offsets[knee_index]))
        shin_length = float(np.linalg.norm(offsets[ankle_index]))
        if not np.isfinite(foot_length) or foot_length <= 1e-9:
            raise ValueError(f'{side} fixed-rig foot length is invalid')
        if (not np.isfinite(thigh_length) or thigh_length <= 1e-9
                or not np.isfinite(shin_length) or shin_length <= 1e-9):
            raise ValueError(f'{side} fixed-rig leg lengths are invalid')
        ankle = toe - direction * foot_length
        active_hip = sampled[active_queries, hip_index]
        knee = _solve_knee(
            active_hip, sampled[active_queries, knee_index], sampled[active_queries, ankle_index],
            ankle[active_queries], thigh_length, shin_length, side)
        sampled[active_queries, toe_index] = toe[active_queries]
        sampled[active_queries, ankle_index] = ankle[active_queries]
        sampled[active_queries, knee_index] = knee
    return sampled
