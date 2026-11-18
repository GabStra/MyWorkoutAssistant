"""Contact-aware fixed-rig sampling that preserves closed leg chains."""

from __future__ import annotations

import numpy as np
from scipy.spatial.transform import Rotation

from .rig_interpolation import hermite_samples


class ContactFootIKUnreachable(ValueError):
    """A planted ankle target lies outside its measured two-bone chain."""

    def __init__(self, side, indexes, hip, target_ankle, minimum, maximum, distance):
        self.side = str(side)
        self.samples = np.asarray(indexes, dtype=int)
        self.hip = np.asarray(hip, dtype=float)
        self.target_ankle = np.asarray(target_ankle, dtype=float)
        self.minimum = np.asarray(minimum, dtype=float)
        self.maximum = np.asarray(maximum, dtype=float)
        self.distance = np.asarray(distance, dtype=float)
        super().__init__(
            f'{self.side} contact foot IK is unreachable at samples '
            f'{self.samples[:8].tolist()}')

    def evidence(self):
        rows = []
        for index in self.samples[:32]:
            i = int(index)
            distance = float(self.distance[i])
            minimum = float(self.minimum[i])
            maximum = float(self.maximum[i])
            rows.append({
                'sampleIndex': i,
                'hipTargetMeters': self.hip[i].tolist(),
                'ankleTargetMeters': self.target_ankle[i].tolist(),
                'hipToAnkleTargetDistanceMeters': distance,
                'minimumReachMeters': minimum,
                'maximumReachMeters': maximum,
                'lowerReachDeficitMeters': max(0., minimum - distance),
                'upperReachExcessMeters': max(0., distance - maximum),
            })
        return {
            'side': self.side,
            'unreachableSampleCount': int(len(self.samples)),
            'samplesTruncated': bool(len(self.samples) > len(rows)),
            'samples': rows,
        }


def build_contact_foot_tracks(rig, keypoints, pinned_mask, *, anchor_ids=None):
    """Build immutable world-space toe and direction tracks for pinned feet."""
    names = list(rig.names if hasattr(rig, 'names') else rig['jointNames'])
    points = np.asarray(keypoints, dtype=float)
    pinned = np.asarray(pinned_mask, dtype=bool)
    if points.ndim != 3 or points.shape[1:] != (len(names), 3):
        raise ValueError('keypoints must have shape (frames, joints, 3)')
    if pinned.shape != points.shape[:2]:
        raise ValueError('pinned_mask must have shape (frames, joints)')
    identities = None if anchor_ids is None else np.asarray(anchor_ids, dtype=object)
    if identities is not None and identities.shape != pinned.shape:
        raise ValueError('anchor_ids must have shape (frames, joints)')
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
        if identities is not None:
            tracks[side]['anchorIds'] = identities[:, toe_index].tolist()
    return {'version': 1, **tracks}


def native_material_contact_tracks(rig, keypoints, pinned_mask, side_axes, episodes,
                                   *, anchor_ids=None, cyclic=False):
    """Build v2 tracks after every active native episode has a bound material point."""
    names = list(rig.names if hasattr(rig, 'names') else rig['jointNames'])
    points = np.asarray(keypoints, dtype=float)
    pinned = np.asarray(pinned_mask, dtype=bool)
    axes = {side: np.asarray((side_axes or {}).get(side), dtype=float)
            for side in ('left', 'right')}
    identities = None if anchor_ids is None else np.asarray(anchor_ids, dtype=object)
    count = len(points)
    if (points.ndim != 3 or points.shape[1:] != (len(names), 3)
            or pinned.shape != points.shape[:2] or not np.isfinite(points).all()
            or identities is not None and identities.shape != pinned.shape):
        raise ValueError('native contact track inputs are malformed')
    result = {'version': 2}
    for side in ('left', 'right'):
        foot_name, ankle_name = f'{side}_foot', f'{side}_ankle'
        if foot_name not in names or ankle_name not in names:
            continue
        side_axis = axes[side]
        if side_axis.shape != (count, 3) or not np.isfinite(side_axis).all():
            raise ValueError(f'{side} native contact track needs finite pose-aware side axes')
        ankle_i, foot_i = names.index(ankle_name), names.index(foot_name)
        direction = points[:, foot_i] - points[:, ankle_i]
        lengths = np.linalg.norm(direction, axis=1)
        if np.any(lengths <= 1e-9):
            raise ValueError(f'{side} native contact track has a zero-length foot bone')
        active = pinned[:, foot_i]
        side_episodes = list((episodes or {}).get(side, []))
        result[side] = {
            'active': active.tolist(),
            'directions': (direction / lengths[:, None]).tolist(),
            'sideAxes': side_axis.tolist(),
            'anchorIds': (identities[:, foot_i].tolist() if identities is not None
                          else [None] * count),
            'episodes': side_episodes,
        }
        _validated_native_side_track(result[side], count, side)
    if cyclic:
        reconcile_cyclic_seam_material_targets(result)
    return result


def _same_native_material_identity(first, second, tolerance=1e-6):
    """True only when two episodes describe the same stationary shoe material point."""
    if str(first.get('mode')) != 'stationary' or str(second.get('mode')) != 'stationary':
        return False
    anchor = first.get('anchorId')
    if anchor is None or anchor != second.get('anchorId'):
        return False
    if (first.get('primitiveId') != second.get('primitiveId')
            or first.get('regionRole') != second.get('regionRole')):
        return False
    try:
        if int(first['triangleIndex']) != int(second['triangleIndex']):
            return False
        first_bary = np.asarray(first['barycentric'], dtype=float)
        second_bary = np.asarray(second['barycentric'], dtype=float)
        first_offset = np.asarray(first['materialOffsetLocalMeters'], dtype=float)
        second_offset = np.asarray(second['materialOffsetLocalMeters'], dtype=float)
        first_reference = float(first['referenceLengthMeters'])
        second_reference = float(second['referenceLengthMeters'])
        first_normal = np.asarray(first['surfaceNormal'], dtype=float)
        second_normal = np.asarray(second['surfaceNormal'], dtype=float)
        first_plane = float(first['planeOffsetMeters'])
        second_plane = float(second['planeOffsetMeters'])
    except (KeyError, TypeError, ValueError, OverflowError):
        return False
    return (first_bary.shape == (3,) and second_bary.shape == (3,)
            and np.allclose(first_bary, second_bary, atol=tolerance, rtol=0.)
            # The cached local material offset and its reference bone length
            # define the physical shoe point; identical triangles/barycentrics
            # can still describe a different point through these fields.
            and first_offset.shape == (3,) and second_offset.shape == (3,)
            and np.allclose(first_offset, second_offset, atol=tolerance, rtol=0.)
            and np.isfinite(first_reference) and np.isfinite(second_reference)
            and abs(first_reference - second_reference) <= tolerance
            and first_normal.shape == (3,) and second_normal.shape == (3,)
            and np.allclose(first_normal, second_normal, atol=tolerance, rtol=0.)
            and abs(first_plane - second_plane) <= tolerance)


def reconcile_cyclic_seam_material_targets(tracks):
    """Give one stationary material contact split by the loop seam a single world target.

    A cyclic clip can represent one continuous stationary shoe contact as two
    episodes: the run ending at the last frame and the run starting at frame 0.
    Each run is bound independently, so the two halves can derive different
    ``targetWorld`` anchors for the *same* material point. The loop seam then
    pins the same material to two world points, and playback interpolation
    between them registers as a stationary-contact residual.

    This reconciles only the two loop-seam halves of one stationary contact
    (identical anchor, geometry, plane and material triangle). They are given
    the midpoint world anchor so the shared material has one target across the
    seam. Released, sliding, repositioned, full-sole, height-only or otherwise
    distinct contacts keep their own targets.
    """
    if not isinstance(tracks, dict) or tracks.get('version') != 2:
        return tracks
    for side in ('left', 'right'):
        track = tracks.get(side)
        if not isinstance(track, dict):
            continue
        episodes = track.get('episodes')
        active = track.get('active')
        if not isinstance(episodes, list) or not isinstance(active, (list, tuple)):
            continue
        count = len(active)
        if count < 2 or not episodes:
            continue
        start_episodes = [episode for episode in episodes
                          if episode.get('startFrame') == 0]
        end_episodes = [episode for episode in episodes
                        if episode.get('endFrame') == count - 1]
        for first in start_episodes:
            for last in end_episodes:
                if first is last or not _same_native_material_identity(first, last):
                    continue
                first_target = np.asarray(first.get('targetWorld'), dtype=float)
                last_target = np.asarray(last.get('targetWorld'), dtype=float)
                if (first_target.shape != (3,) or last_target.shape != (3,)
                        or not np.isfinite(first_target).all()
                        or not np.isfinite(last_target).all()):
                    continue
                shared = 0.5 * (first_target + last_target)
                first['targetWorld'] = shared.tolist()
                last['targetWorld'] = shared.tolist()
    return tracks


def _priority_ordered_native_contacts(contacts, foot_name, count):
    """Order stationary foot contacts so narrower exact episodes own their frames.

    A reviewed stance can publish a broad forefoot/sole umbrella plus exact
    chunk episodes for the same anchor group. The narrower episode is the exact
    representation of the reviewed interval; the umbrella only fills the frames
    those exact episodes do not cover.
    """
    from .contact_constraints import (contact_frame_bounds, is_stationary_contact)

    eligible = []
    for index, contact in enumerate(contacts):
        if (contact.get('jointName') != foot_name
                or contact.get('contactState') not in {'heel_only', 'forefoot', 'toe_only', 'full_sole'}
                or not is_stationary_contact(contact)):
            continue
        start, end = contact_frame_bounds(contact, count)
        if end < start:
            continue
        eligible.append((index, contact, start, end))
    anchor_spans = {}
    for _, contact, start, end in eligible:
        anchor = contact.get('anchorGroupId')
        if anchor:
            anchor_spans.setdefault(str(anchor), []).append((start, end))

    def sort_key(item):
        index, contact, start, end = item
        spans = anchor_spans.get(str(contact.get('anchorGroupId'))) or []
        nested = len(spans) > 1
        return (0 if nested else 1, (end - start) if nested else 0, index)

    return sorted(eligible, key=sort_key)


def _bind_native_material_episode(vertices, triangles, points, side_axes, active_frames,
                                  ankle_i, foot_i, role, normal, plane_offset,
                                  side_geometry, side):
    """Bind one exact material triangle across a contiguous active frame run."""
    from .body_surface_geometry import (native_shoe_region_candidates,
                                        select_native_shoe_material_point)
    from .native_foot_geometry import native_foot_bone_frame

    candidates = native_shoe_region_candidates(
        vertices, triangles, points[:, ankle_i], points[:, foot_i],
        side_axes, active_frames, role)
    binding = select_native_shoe_material_point(
        vertices, triangles, candidates, active_frames, normal, plane_offset)
    triangle_index = binding['triangleIndex']
    barycentric = np.asarray(binding['barycentric'], dtype=float)
    material = np.einsum('v,fvc->fc', barycentric,
                         vertices[active_frames][:, triangles[triangle_index]])
    local_offsets = []
    reference_length = float(side_geometry['ankleToFootJointLengthMeters'])
    for frame, point in zip(active_frames, material):
        forward, lateral, up, length = native_foot_bone_frame(
            points[frame, ankle_i], points[frame, foot_i], side_axes[frame])
        factor = float(length[0]) / reference_length
        delta = point - points[frame, ankle_i]
        local_offsets.append(np.array([np.dot(delta, forward),
                                       np.dot(delta, lateral),
                                       np.dot(delta, up)]) / factor)
    local_offset = np.median(np.asarray(local_offsets), axis=0)
    # The compact offset is only a cache; verify it against the exact selected
    # native triangle at every episode frame before publishing.
    for frame, point, offset in zip(active_frames, material, local_offsets):
        forward, lateral, up, length = native_foot_bone_frame(
            points[frame, ankle_i], points[frame, foot_i], side_axes[frame])
        rebuilt = points[frame, ankle_i] + (forward * offset[0]
            + lateral * offset[1] + up * offset[2]) * (float(length[0]) / reference_length)
        if not np.allclose(rebuilt, point, atol=1e-8, rtol=0.):
            raise ValueError(f'{side} native material binding cache changes across the episode')
    episode = {
        'triangleIndex': triangle_index, 'barycentric': binding['barycentric'],
        'materialOffsetLocalMeters': local_offset.tolist(),
        'referenceLengthMeters': reference_length,
        'surfaceNormal': normal.tolist(), 'planeOffsetMeters': plane_offset,
        'targetWorld': np.asarray(binding['targetWorld'], dtype=float).tolist(),
    }
    if role == 'full_sole':
        # A stationary full sole is a material plane, not a single anchor: its
        # rendered sole orientation travels with the track so every consumer can
        # impose the same ankle/sole physical pose.
        episode['soleNormalLocalMeters'] = _native_sole_normal_local(
            vertices, active_frames, points, ankle_i, foot_i, side_axes, side).tolist()
    return episode


def _native_sole_normal_local(vertices, frames, points, ankle_i, foot_i,
                              side_axes, side):
    """Rendered sole-plane normal expressed in the rigid ankle/foot body frame.

    The six sole-ring samples of the native shoe are coplanar and rigidly
    attached to the ``(forward, lateral, up)`` material frame, so a single
    body-frame normal describes the rendered sole orientation at every episode
    frame. Storing it here lets every downstream consumer (encoder, sampler and
    playback) share one physical full-sole pose basis without re-deriving the
    shoe geometry.
    """
    from .native_foot_geometry import native_foot_bone_frame
    from .support_geometry import _NATIVE_SHOE_SOLE_RING_VERTICES

    frames = np.asarray(frames, dtype=int)
    if not len(frames):
        raise ValueError(f'{side} native sole normal needs at least one frame')
    sole = np.asarray(vertices, dtype=float)[frames][:, _NATIVE_SHOE_SOLE_RING_VERTICES]
    centered = sole - sole.mean(axis=1, keepdims=True)
    _, _, vectors = np.linalg.svd(centered, full_matrices=False)
    normals = vectors[:, -1, :]
    local = []
    for frame, normal in zip(frames, normals):
        forward, lateral, up, _ = native_foot_bone_frame(
            points[frame, ankle_i], points[frame, foot_i], side_axes[frame])
        if float(np.dot(normal, up)) < 0.:
            normal = -normal
        local.append([float(np.dot(normal, forward)),
                      float(np.dot(normal, lateral)),
                      float(np.dot(normal, up))])
    body = np.median(np.asarray(local, dtype=float), axis=0)
    length = float(np.linalg.norm(body))
    if not np.isfinite(length) or length <= 1e-9:
        raise ValueError(f'{side} native sole normal is degenerate')
    return body / length


def build_native_foot_contact_tracks(rig, keypoints, pinned_mask, side_axes, evidence,
                                     native_geometry, *, floor=None, rest_pitches=None,
                                     cyclic=False):
    """Bind one inferred native shoe point per stationary source contact episode."""
    from .body_surface_geometry import (native_shoe_region_candidates,
                                        select_native_shoe_material_point)
    from .contact_constraints import (contact_frame_bounds, is_observed_ground_contact,
                                      is_observed_support_contact, is_stationary_contact,
                                      motion_support_contacts)
    from .foot_geometry import foot_scale_from_pose, shoe_vertices
    from .material_region_support import shoe_triangles
    from .native_foot_geometry import validated_native_foot_geometry, native_foot_bone_frame

    names = list(rig.names if hasattr(rig, 'names') else rig['jointNames'])
    points = np.asarray(keypoints, dtype=float)
    pinned = np.asarray(pinned_mask, dtype=bool)
    geometry = validated_native_foot_geometry(native_geometry)
    if geometry is None:
        raise ValueError('native contact binding requires validated nativeFootGeometry')
    if (points.ndim != 3 or points.shape[1:] != (len(names), 3)
            or pinned.shape != points.shape[:2] or not np.isfinite(points).all()):
        raise ValueError('native contact binding inputs are malformed')
    count = len(points)
    scale = float(foot_scale_from_pose(points[0], names))
    if not np.isfinite(scale) or scale <= 0.:
        raise ValueError('native contact binding footScale is invalid')
    tracks = {'version': 2}
    owned = np.zeros_like(pinned)
    episodes_by_side = {}
    ids_by_side = {}
    contacts = motion_support_contacts(evidence)
    planes = {}
    body_support = evidence.get('bodySupport') or {}
    for group in body_support.get('coplanarGroups', []):
        joints = group.get('joints') or []
        foot_name = next((name for name in joints if str(name).endswith('_foot')), None)
        if foot_name and group.get('planeOffsetMeters') is not None:
            planes[foot_name] = (group.get('normal'), group.get('planeOffsetMeters'))
    for side in ('left', 'right'):
        ankle_name, foot_name = f'{side}_ankle', f'{side}_foot'
        if ankle_name not in names or foot_name not in names:
            continue
        if side not in side_axes:
            raise ValueError(f'{side} native binding has no resolved pose-side track')
        current_side_axes = np.asarray(side_axes[side], dtype=float)
        if current_side_axes.shape != (count, 3) or not np.isfinite(current_side_axes).all():
            raise ValueError(f'{side} native binding pose-side track is malformed')
        ankle_i, foot_i = names.index(ankle_name), names.index(foot_name)
        side_geometry = geometry['sides'][side]
        vertices = np.asarray([
            shoe_vertices(points[index, ankle_i], points[index, foot_i],
                          current_side_axes[index], (rest_pitches or {}).get(side), scale,
                          native_geometry=side_geometry)
            for index in range(count)
        ], dtype=float)
        triangles = shoe_triangles()
        side_episodes, identities = [], [None] * count
        owner_anchor = np.full(count, None, dtype=object)
        owner_contact = np.full(count, -1, dtype=int)
        owner_role = np.full(count, None, dtype=object)
        contact_spans = {}
        for contact_index, contact, start, end in _priority_ordered_native_contacts(
                contacts, foot_name, count):
            contact_spans[contact_index] = (start, end)
            ground_contact = is_observed_ground_contact(contact, evidence)
            if not ground_contact and foot_name not in planes:
                if is_observed_support_contact(contact, evidence):
                    raise ValueError(f'{side} observed native contact has no qualified support plane')
                continue
            role = ('heel' if contact.get('contactState') == 'heel_only' else
                    'full_sole' if contact.get('contactState') == 'full_sole' else 'forefoot')
            vertical_only = (contact.get('verticalOnly') is True or
                             (contact.get('contactState') == 'toe_only'
                              and contact.get('verticalOnly') is not False))
            plane = planes.get(foot_name)
            if plane is not None:
                normal = np.asarray(plane[0], dtype=float)
                plane_offset = float(plane[1])
                if normal.shape != (3,) or not np.isfinite(normal).all() or np.linalg.norm(normal) <= 1e-9:
                    raise ValueError(f'{side} native contact support plane is malformed')
                normal /= np.linalg.norm(normal)
            elif ground_contact and floor is not None:
                normal, plane_offset = np.array([0., 1., 0.]), float(floor)
            else:
                raise ValueError(f'{side} native contact has no authoritative support plane')
            anchor_id = str(contact.get('anchorGroupId') or
                            f'native-material:{side}:{contact_index}:{start}:{end}')
            frame_range = np.arange(start, end + 1, dtype=int)
            occupied = frame_range[owned[frame_range, foot_i]]
            if occupied.size:
                for frame in occupied:
                    owner = int(owner_contact[frame])
                    if owner < 0:
                        continue
                    if str(owner_anchor[frame]) != anchor_id:
                        raise ValueError(f'{side} native stationary contact episodes overlap')
                    owner_start, owner_end = contact_spans[owner]
                    nested = ((owner_start <= start and end <= owner_end)
                              or (start <= owner_start and owner_end <= end))
                    if not nested:
                        raise ValueError(f'{side} native stationary contact episodes overlap')
                    if ((start, end) == (owner_start, owner_end)
                            and owner != contact_index
                            and owner_role[frame] != role):
                        raise ValueError(f'{side} native stationary contact episodes overlap')
                frame_range = frame_range[~owned[frame_range, foot_i]]
                if frame_range.size == 0:
                    continue
            runs = np.split(frame_range, np.flatnonzero(np.diff(frame_range) > 1) + 1)
            for run in runs:
                run_start, run_end = int(run[0]), int(run[-1])
                active_frames = np.arange(run_start, run_end + 1, dtype=int)
                binding = _bind_native_material_episode(
                    vertices, triangles, points, current_side_axes, active_frames,
                    ankle_i, foot_i, role, normal, plane_offset, side_geometry, side)
                binding.update({
                    'startFrame': run_start, 'endFrame': run_end,
                    'anchorId': anchor_id, 'regionRole': role,
                    'mode': 'verticalOnly' if vertical_only else 'stationary',
                    'primitiveId': f'wearShoe:{ankle_name}->{foot_name}',
                })
                if vertical_only:
                    binding.pop('targetWorld', None)
                side_episodes.append(binding)
                owned[run_start:run_end + 1, foot_i] = True
                owner_anchor[run_start:run_end + 1] = anchor_id
                owner_contact[run_start:run_end + 1] = contact_index
                owner_role[run_start:run_end + 1] = role
                identities[run_start:run_end + 1] = [anchor_id] * (run_end - run_start + 1)
        episodes_by_side[side] = side_episodes
        ids_by_side[side] = identities
    if not np.any(owned):
        return None, owned
    identities = np.full(pinned.shape, None, dtype=object)
    for side, side_ids in ids_by_side.items():
        foot_name = f'{side}_foot'
        if foot_name in names:
            identities[:, names.index(foot_name)] = side_ids
    tracks = native_material_contact_tracks(
        rig, points, owned, side_axes, episodes_by_side,
        anchor_ids=identities, cyclic=cyclic)
    for side in ('left', 'right'):
        if side not in tracks:
            continue
        tracks[side]['anchorIds'] = ids_by_side.get(side, [None] * count)
        _validated_native_side_track(tracks[side], count, side)
    return tracks, owned


def reselect_native_material_episode_at_pose(tracks, side, names, pose, side_axis,
                                             native_geometry, foot_scale, frame_index):
    """Rebind one inferred contact point when calibration changes shoe orientation.

    Contact identity, plane, region, episode bounds, and stationary target remain
    owned by the existing episode. Only the inferred triangle/barycentric cache
    is selected again against the corrected pose.
    """
    from .body_surface_geometry import (native_shoe_region_candidates,
                                        select_native_shoe_material_point)
    from .foot_geometry import shoe_vertices
    from .material_region_support import shoe_triangles
    from .native_foot_geometry import (native_foot_bone_frame,
                                       validated_native_foot_geometry)

    if side not in {'left', 'right'} or not isinstance(tracks, dict) or tracks.get('version') != 2:
        raise ValueError('native material episode rebind requires a v2 track and side')
    names = list(names)
    row = np.asarray(pose, dtype=float)
    if row.ndim != 2 or row.shape != (len(names), 3):
        raise ValueError('native material corrected pose must include named joints')
    geometry = validated_native_foot_geometry(native_geometry)
    if geometry is None:
        raise ValueError('native material rebind needs validated geometry')
    track = tracks.get(side) or {}
    index = int(frame_index)
    episode_index = next((i for i, ep in enumerate(track.get('episodes') or [])
                          if int(ep.get('startFrame', -1)) <= index <= int(ep.get('endFrame', -2))), None)
    if episode_index is None:
        return tracks, False
    episode = track['episodes'][episode_index]
    role = episode.get('regionRole')
    if role not in {'forefoot', 'heel', 'full_sole'}:
        raise ValueError('native material episode has no supported anatomical region')
    ankle_i, foot_i = names.index(f'{side}_ankle'), names.index(f'{side}_foot')
    ankle, foot = row[ankle_i], row[foot_i]
    axis = np.asarray(side_axis, dtype=float)
    if axis.shape != (3,) or not np.isfinite(axis).all():
        raise ValueError('native material corrected side axis is malformed')
    mesh = shoe_vertices(ankle, foot, axis, None, float(foot_scale),
                         native_geometry=geometry['sides'][side])
    triangles = shoe_triangles()
    eligible = native_shoe_region_candidates(
        mesh[None], triangles, ankle[None], foot[None], axis[None], [0], role)
    binding = select_native_shoe_material_point(
        mesh[None], triangles, eligible, [0],
        np.asarray(episode['surfaceNormal'], dtype=float),
        float(episode['planeOffsetMeters']))
    old_identity = (int(episode['triangleIndex']),
                    tuple(float(x) for x in episode['barycentric']))
    new_identity = (int(binding['triangleIndex']),
                    tuple(float(x) for x in binding['barycentric']))
    if old_identity == new_identity:
        return tracks, False

    point = np.asarray(binding['barycentric'], dtype=float) @ mesh[
        triangles[binding['triangleIndex']]]
    old_point = np.asarray(episode['barycentric'], dtype=float) @ mesh[
        triangles[old_identity[0]]]
    normal = np.asarray(episode['surfaceNormal'], dtype=float)
    plane = float(episode['planeOffsetMeters'])
    if episode.get('mode') == 'verticalOnly':
        old_shift = (plane - float(np.dot(old_point, normal))) * normal
        new_shift = (plane - float(np.dot(point, normal))) * normal
    else:
        target = np.asarray(episode['targetWorld'], dtype=float)
        old_shift, new_shift = target - old_point, target - point
    old_penetration = max(0., plane - float(np.min((mesh + old_shift) @ normal)))
    new_penetration = max(0., plane - float(np.min((mesh + new_shift) @ normal)))
    if new_penetration >= old_penetration - 1e-8:
        return tracks, False
    forward, lateral, up, length = native_foot_bone_frame(
        ankle[None], foot[None], axis[None])
    reference_length = float(episode['referenceLengthMeters'])
    factor = float(np.asarray(length).reshape(-1)[0]) / reference_length
    delta = point - ankle
    local_offset = np.array([np.dot(delta, forward[0]),
                             np.dot(delta, lateral[0]),
                             np.dot(delta, up[0])]) / factor
    bound = tracks[side]['episodes'][episode_index]
    bound['triangleIndex'] = int(binding['triangleIndex'])
    bound['barycentric'] = binding['barycentric']
    bound['materialOffsetLocalMeters'] = local_offset.tolist()
    rebuilt = ankle + (forward[0] * local_offset[0]
                       + lateral[0] * local_offset[1]
                       + up[0] * local_offset[2]) * factor
    if not np.allclose(rebuilt, point, atol=1e-8, rtol=0.):
        raise ValueError('native material rebind cache does not match selected mesh point')
    _validated_native_side_track(tracks[side], len(tracks[side]['active']), side)
    return tracks, True


def refresh_contact_foot_tracks(rig, keypoints, tracks, *, side_axes=None):
    """Refresh pose-derived geometry without changing contact activity or identity."""
    from copy import deepcopy

    if not isinstance(tracks, dict) or tracks.get('version') not in (1, 2):
        raise ValueError('contactFootTracks has an unsupported or malformed version')
    if tracks.get('version') == 2 and type(tracks.get('version')) is not int:
        raise ValueError('contactFootTracks has an unsupported or malformed version')
    names = list(rig.names if hasattr(rig, 'names') else rig['jointNames'])
    points = np.asarray(keypoints, dtype=float)
    if points.ndim != 3 or points.shape[1:] != (len(names), 3) or not np.isfinite(points).all():
        raise ValueError('keypoints must be finite with shape (frames, joints, 3)')
    refreshed = deepcopy(tracks)
    for side in ('left', 'right'):
        if side not in tracks:
            continue
        if tracks['version'] == 2:
            _validated_native_side_track(tracks[side], len(points), side)
        else:
            _validated_side_track(tracks[side], len(points), side)
        ankle, toe = (names.index(f'{side}_{part}') for part in ('ankle', 'foot'))
        direction = points[:, toe] - points[:, ankle]
        length = np.linalg.norm(direction, axis=1)
        if np.any(length <= 1e-9):
            raise ValueError(f'{side} foot track contains a zero-length ankle-to-toe vector')
        if tracks['version'] == 1:
            refreshed[side]['toes'] = points[:, toe].tolist()
        elif side_axes is not None:
            axes = np.asarray(side_axes.get(side), dtype=float)
            if axes.shape != (len(points), 3) or not np.isfinite(axes).all():
                raise ValueError(f'{side} refreshed side axes are malformed')
            axis_lengths = np.linalg.norm(axes, axis=1)
            if np.any(axis_lengths <= 1e-9):
                raise ValueError(f'{side} refreshed side axes contain a zero vector')
            directions = direction / length[:, None]
            axes = axes / axis_lengths[:, None]
            # `material_side_axes` transports the foot frame through FK, while
            # the ankle-to-foot direction is controlled by its parent chain.
            # Remove the resulting redundant forward component before storing
            # the renderer's orthonormal contact frame. This is the same
            # projection already used by native_foot_bone_frame/shoe sampling.
            axes -= directions * np.sum(axes * directions, axis=1, keepdims=True)
            projected_lengths = np.linalg.norm(axes, axis=1)
            if np.any(projected_lengths <= 1e-9):
                raise ValueError(f'{side} refreshed side axes are collinear with foot direction')
            refreshed[side]['sideAxes'] = (axes / projected_lengths[:, None]).tolist()
        refreshed[side]['directions'] = (direction / length[:, None]).tolist()
    return refreshed


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
    anchor_ids = track.get('anchorIds')
    if anchor_ids is not None and (not isinstance(anchor_ids, (list, tuple))
            or len(anchor_ids) != count
            or any(value is not None and not isinstance(value, str) for value in anchor_ids)):
        raise ValueError(f'{side} contact foot anchor identities are malformed')
    return active, toes, directions / lengths[:, None], anchor_ids


def _validated_native_side_track(track, count, side):
    required = {'active', 'directions', 'sideAxes', 'anchorIds', 'episodes'}
    if not isinstance(track, dict) or set(track) != required:
        raise ValueError(f'{side} native contact foot track is malformed')
    active = np.asarray(track['active'])
    directions = np.asarray(track['directions'], dtype=float)
    side_axes = np.asarray(track['sideAxes'], dtype=float)
    anchor_ids = track['anchorIds']
    if (active.dtype != np.dtype(bool) or active.shape != (count,)
            or directions.shape != (count, 3) or side_axes.shape != (count, 3)
            or not np.isfinite(directions).all() or not np.isfinite(side_axes).all()
            or not isinstance(anchor_ids, (list, tuple)) or len(anchor_ids) != count
            or any(value is not None and not isinstance(value, str) for value in anchor_ids)
            or not isinstance(track['episodes'], list)):
        raise ValueError(f'{side} native contact foot track arrays are malformed')
    norms = np.linalg.norm(directions, axis=1)
    if np.any(norms <= 1e-9) or not np.allclose(norms, 1., atol=1e-4, rtol=1e-4):
        raise ValueError(f'{side} native contact directions must be normalized')
    norms = np.linalg.norm(side_axes, axis=1)
    if np.any(norms <= 1e-9) or not np.allclose(norms, 1., atol=1e-4, rtol=1e-4):
        raise ValueError(f'{side} native contact side axes must be normalized')
    episodes = np.zeros(count, dtype=np.int8)
    for episode in track['episodes']:
        if not isinstance(episode, dict):
            raise ValueError(f'{side} native contact episode is malformed')
        allowed = {'startFrame', 'endFrame', 'anchorId', 'regionRole', 'mode',
                   'primitiveId', 'triangleIndex', 'barycentric',
                   'materialOffsetLocalMeters', 'referenceLengthMeters',
                   'targetWorld', 'surfaceNormal', 'planeOffsetMeters',
                   'soleNormalLocalMeters'}
        if set(episode) - allowed:
            raise ValueError(f'{side} native contact episode has unsupported fields')
        try:
            start, end = episode['startFrame'], episode['endFrame']
            triangle = episode['triangleIndex']
            bary = np.asarray(episode['barycentric'], dtype=float)
            offset = np.asarray(episode['materialOffsetLocalMeters'], dtype=float)
            ref_length = float(episode['referenceLengthMeters'])
            anchor = episode['anchorId']
            role, mode = episode['regionRole'], episode['mode']
            primitive = episode['primitiveId']
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f'{side} native contact episode fields are malformed') from exc
        if (isinstance(start, bool) or not isinstance(start, int)
                or isinstance(end, bool) or not isinstance(end, int)
                or not 0 <= start <= end < count or anchor is None
                or not isinstance(anchor, str) or role not in {'forefoot', 'heel', 'full_sole'}
                or mode not in {'stationary', 'verticalOnly'}
                or primitive != f'wearShoe:{side}_ankle->{side}_foot'
                or isinstance(triangle, bool) or not isinstance(triangle, int) or triangle < 0
                or bary.shape != (3,) or not np.isfinite(bary).all()
                or np.any(bary < 0.) or not np.isclose(bary.sum(), 1., atol=1e-6, rtol=0.)
                or offset.shape != (3,) or not np.isfinite(offset).all()
                or not np.isfinite(ref_length) or ref_length <= 0.):
            raise ValueError(f'{side} native contact episode values are invalid')
        sole_normal = episode.get('soleNormalLocalMeters')
        if sole_normal is not None:
            sole_normal = np.asarray(sole_normal, dtype=float)
            if (sole_normal.shape != (3,) or not np.isfinite(sole_normal).all()
                    or abs(float(np.linalg.norm(sole_normal)) - 1.) > 1e-6
                    or role != 'full_sole'):
                raise ValueError(f'{side} native contact sole normal is invalid')
        if mode == 'stationary':
            target = np.asarray(episode.get('targetWorld'), dtype=float)
            normal = np.asarray(episode.get('surfaceNormal'), dtype=float)
            plane_offset = episode.get('planeOffsetMeters')
            if (target.shape != (3,) or not np.isfinite(target).all()
                    or normal.shape != (3,) or not np.isfinite(normal).all()
                    or abs(np.linalg.norm(normal) - 1.) > 1e-6
                    or isinstance(plane_offset, bool)
                    or not isinstance(plane_offset, (int, float))
                    or not np.isfinite(float(plane_offset))):
                raise ValueError(f'{side} stationary native contact target is invalid')
        else:
            normal = np.asarray(episode.get('surfaceNormal'), dtype=float)
            offset_plane = episode.get('planeOffsetMeters')
            if (normal.shape != (3,) or not np.isfinite(normal).all()
                    or abs(np.linalg.norm(normal) - 1.) > 1e-6
                    or isinstance(offset_plane, bool)
                    or not isinstance(offset_plane, (int, float))
                    or not np.isfinite(float(offset_plane)) or 'targetWorld' in episode):
                raise ValueError(f'{side} vertical-only native contact plane is invalid')
        if np.any(episodes[start:end + 1]):
            raise ValueError(f'{side} native contact episodes overlap')
        if not np.all(active[start:end + 1]):
            raise ValueError(f'{side} native contact episode includes inactive frames')
        for frame_index in range(start, end + 1):
            stored_identity = anchor_ids[frame_index]
            if stored_identity is None:
                # A height-only contact owns a material point and plane, not a
                # tangent XYZ anchor. Its episode span supplies continuity.
                if mode != 'verticalOnly':
                    raise ValueError(
                        f'{side} native contact episode identity does not match track')
            elif stored_identity != anchor:
                raise ValueError(
                    f'{side} native contact episode identity does not match track')
        episodes[start:end + 1] = 1
    if np.any(active != (episodes == 1)):
        raise ValueError(f'{side} active native contact frames need exactly one episode')
    return active, directions / norms[:, None], side_axes / np.linalg.norm(side_axes, axis=1)[:, None], anchor_ids


def _native_episode_by_frame(track):
    """Map every active frame index to its owning native material episode."""
    episodes = {}
    for episode in track['episodes']:
        for frame_index in range(episode['startFrame'], episode['endFrame'] + 1):
            episodes[frame_index] = episode
    return episodes


def _native_vertical_planes_match(left, right, tolerance=1e-6):
    """Only identical observed planes may be treated as one height-only contact."""
    left_normal = np.asarray(left['surfaceNormal'], dtype=float)
    right_normal = np.asarray(right['surfaceNormal'], dtype=float)
    if (left_normal.shape != (3,) or right_normal.shape != (3,)
            or not np.isfinite(left_normal).all() or not np.isfinite(right_normal).all()):
        return False
    try:
        left_plane = float(left['planeOffsetMeters'])
        right_plane = float(right['planeOffsetMeters'])
    except (KeyError, TypeError, ValueError, OverflowError):
        return False
    return (np.isfinite(left_plane) and np.isfinite(right_plane)
            and ((abs(left_plane - right_plane) <= tolerance
                  and np.linalg.norm(left_normal - right_normal) <= tolerance)
                 or (abs(left_plane + right_plane) <= tolerance
                     and np.linalg.norm(left_normal + right_normal) <= tolerance)))


def _native_interval_contact_mask(start_active, end_active, first, last,
                                  episode_by_frame, anchor_ids):
    """Frames an interval only when it belongs to one material contact.

    Stationary contacts keep their non-empty shared anchor identity. A
    height-only contact has no XYZ anchor by design: its identity is the
    episode's own material point and observed plane. Continuous frames of that
    episode therefore remain one contact, while a release, a different episode
    or an incompatible plane breaks the interval instead of blending it.
    """
    same = np.zeros(len(first), dtype=bool)
    for index in np.flatnonzero(np.asarray(start_active, dtype=bool)
                                & np.asarray(end_active, dtype=bool)):
        start_frame, end_frame = int(first[index]), int(last[index])
        start_episode = episode_by_frame.get(start_frame)
        end_episode = episode_by_frame.get(end_frame)
        if start_episode is None or end_episode is None:
            continue
        start_mode, end_mode = str(start_episode['mode']), str(end_episode['mode'])
        if start_mode != end_mode:
            continue
        anchor_start = anchor_ids[start_frame] if anchor_ids is not None else None
        anchor_end = anchor_ids[end_frame] if anchor_ids is not None else None
        if start_mode == 'verticalOnly':
            if not _native_vertical_planes_match(start_episode, end_episode):
                continue
            same_episode = (start_episode is end_episode
                            or (int(start_episode['startFrame']) == int(end_episode['startFrame'])
                                and int(start_episode['endFrame']) == int(end_episode['endFrame'])))
            same[index] = bool(
                same_episode
                or (anchor_start is not None and anchor_end is not None
                    and str(anchor_start) == str(anchor_end)))
            continue
        same[index] = bool(
            anchor_start is not None and anchor_end is not None
            and str(anchor_start) == str(anchor_end))
    return same


def _native_material_point(ankle, foot, side_axis, episode, side_geometry, foot_scale):
    """Material triangle point on the actual calibrated shoe at one pose."""
    from .foot_geometry import shoe_vertices
    from .material_region_support import shoe_triangles

    vertices = shoe_vertices(
        ankle, foot, side_axis, None, float(foot_scale), native_geometry=side_geometry)
    triangle = shoe_triangles()[int(episode['triangleIndex'])]
    barycentric = np.asarray(episode['barycentric'], dtype=float)
    return barycentric @ np.asarray(vertices, dtype=float)[triangle]


def _native_pose_material_point(ankle, foot, side_axis, episode, bone_length):
    """Material point from the candidate pose frame and cached compact offset.

    Mirrors ``supported_contact_rig._material_frame``/``_material_points`` and
    the playback sampler: the ankle-to-foot bone owns the forward axis, the
    transported side axis is projected perpendicular to it, and the cached
    offset is scaled by the serialized foot length over the episode reference.
    The frame itself is delegated to the shared support-rig helper.
    """
    from .supported_contact_rig import _material_frame

    frame, _ = _material_frame(
        np.asarray(ankle, dtype=float)[None],
        np.asarray(foot, dtype=float)[None],
        np.asarray(side_axis, dtype=float)[None])
    local = np.asarray(episode['materialOffsetLocalMeters'], dtype=float)
    reference = float(episode['referenceLengthMeters'])
    if reference <= 1e-9:
        raise ValueError('native material pose reference length is invalid')
    offset = (frame[0] @ local) * (float(bone_length) / reference)
    return np.asarray(ankle, dtype=float) + offset


def native_height_material_plane_residuals(points, names, tracks, positions, *,
                                           side_axes, native_geometry, foot_scale,
                                           wrap=False, return_metrics=False):
    """Actual calibrated shoe material-plane error for height-only episodes.

    This is the rendered-key half of the native height-only contract: the
    material triangle carried by each ``verticalOnly`` episode is evaluated on
    the actual shoe mesh at the supplied pose (the same native geometry, side
    axes and scale the renderer uses), not on the stored track frame used for
    between-key interpolation. The returned residual is the plane-normal
    correction ``(normal*point - plane) * normal``; tangential motion is
    unconstrained. Non-height-only episodes are ignored.
    """
    from .native_foot_geometry import validated_native_foot_geometry

    values = np.asarray(points, dtype=float)
    names = list(names)
    cursors = np.asarray(positions, dtype=float).reshape(-1)
    side_axes = side_axes if isinstance(side_axes, dict) else {}
    metrics = {'available': False, 'sampleCount': 0, 'maximumErrorMeters': 0.,
               'bySide': {}}
    if not isinstance(tracks, dict) or tracks.get('version') != 2:
        return (np.empty((len(cursors), 0), dtype=float), metrics) if return_metrics else np.empty((len(cursors), 0), dtype=float)
    if (values.ndim != 3 or values.shape[1:] != (len(names), 3)
            or values.shape[0] != len(cursors)
            or not np.isfinite(values).all() or not np.isfinite(cursors).all()):
        raise ValueError('native height material residual inputs are malformed')
    geometry = validated_native_foot_geometry(native_geometry)
    try:
        scale = float(foot_scale)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError('native height material residual needs a finite foot scale') from error
    if geometry is None or not np.isfinite(scale) or scale <= 0.:
        raise ValueError('native height material residual needs calibrated native geometry')
    columns = []
    maximum = 0.
    sample_count = 0
    for side in ('left', 'right'):
        track = tracks.get(side)
        if track is None or f'{side}_ankle' not in names or f'{side}_foot' not in names:
            continue
        frame_count = len(track.get('active', ()))
        active, _, _, _ = _validated_native_side_track(track, frame_count, side)
        axis_values = side_axes.get(side)
        if axis_values is None:
            raise ValueError(
                f'{side} native height material side axes are unavailable')
        axis_values = np.asarray(axis_values, dtype=float)
        if axis_values.shape != (len(cursors), 3) or not np.isfinite(axis_values).all():
            raise ValueError(f'{side} native height material side axes are malformed')
        normalized = np.mod(cursors, frame_count) if wrap else np.clip(
            cursors, 0., frame_count - 1.)
        first = np.floor(normalized).astype(int)
        last = (first + 1) % frame_count if wrap else np.minimum(first + 1, frame_count - 1)
        exact_key = np.isclose(normalized, np.round(normalized), atol=1e-12, rtol=0.)
        episode_by_frame = _native_episode_by_frame(track)
        same_contact = _native_interval_contact_mask(
            active[first], active[last], first, last, episode_by_frame,
            track['anchorIds'])
        key_frames = np.rint(normalized).astype(int)
        key_frames = key_frames % frame_count if wrap else np.clip(key_frames, 0, frame_count - 1)
        measured = same_contact | (exact_key & active[key_frames])
        ankle_i, foot_i = names.index(f'{side}_ankle'), names.index(f'{side}_foot')
        residual = np.zeros((len(cursors), 3), dtype=float)
        side_maximum = 0.
        side_count = 0
        for index in np.flatnonzero(measured):
            if exact_key[index]:
                episode = episode_by_frame.get(int(key_frames[index]))
            else:
                episode = episode_by_frame.get(int(first[index]))
            if episode is None or str(episode['mode']) != 'verticalOnly':
                continue
            material = _native_material_point(
                values[index, ankle_i], values[index, foot_i], axis_values[index],
                episode, geometry['sides'][side], scale)
            normal = np.asarray(episode['surfaceNormal'], dtype=float)
            plane = float(episode['planeOffsetMeters'])
            correction = (float(np.dot(normal, material)) - plane) * normal
            residual[index] = correction
            side_maximum = max(side_maximum, float(np.linalg.norm(correction)))
            side_count += 1
        if side_count:
            columns.append(residual)
            metrics['bySide'][side] = {
                'sampleCount': int(side_count),
                'maximumErrorMeters': float(side_maximum),
            }
            sample_count += side_count
            maximum = max(maximum, side_maximum)
    if not columns:
        return (np.empty((len(cursors), 0), dtype=float), metrics) if return_metrics else np.empty((len(cursors), 0), dtype=float)
    residuals = np.concatenate(columns, axis=1)
    metrics.update(available=True, sampleCount=int(sample_count),
                   maximumErrorMeters=float(maximum))
    return (residuals, metrics) if return_metrics else residuals


def suppress_native_foot_pins(pinned, names, tracks, *, support_evidence=None):
    """Drop native-owned foot pins and only their implicit full-sole ankle pins."""
    result = np.asarray(pinned, dtype=bool).copy()
    if not isinstance(tracks, dict) or tracks.get('version') != 2:
        return result
    if set(tracks) - {'version', 'left', 'right'}:
        raise ValueError('contactFootTracks has unsupported fields')
    for side in ('left', 'right'):
        track = tracks.get(side)
        if track is None:
            continue
        _validated_native_side_track(track, len(result), side)
        name = f'{side}_foot'
        if name in names:
            active = np.asarray(track['active'], dtype=bool)
            result[:, names.index(name)] &= ~active
            ankle_name = f'{side}_ankle'
            if ankle_name not in names or support_evidence is None:
                continue
            from .contact_constraints import (contact_frame_bounds,
                                              is_stationary_contact,
                                              motion_support_contacts)
            explicit = np.zeros(len(result), dtype=bool)
            implicit = np.zeros(len(result), dtype=bool)
            evidence = support_evidence if isinstance(support_evidence, dict) else {}
            if ankle_name in (evidence.get('stationaryJoints') or []):
                explicit[:] = True
            for contact in motion_support_contacts(evidence):
                joint = str(contact.get('jointName') or '')
                if (joint not in {ankle_name, name}
                        or contact.get('verticalOnly') is True
                        or (contact.get('contactState') == 'toe_only'
                            and contact.get('verticalOnly') is not False)
                        or not is_stationary_contact(contact)):
                    continue
                try:
                    start, end = contact_frame_bounds(contact, len(result))
                except (TypeError, ValueError):
                    continue
                if end < start:
                    continue
                target = explicit if joint == ankle_name else implicit
                if joint == name and contact.get('contactState') == 'full_sole':
                    target[start:end + 1] = True
                elif joint == ankle_name:
                    target[start:end + 1] = True
            result[:, names.index(ankle_name)] &= ~(active & implicit & ~explicit)
    return result


def validate_native_contact_track_geometry(points, names, side_axes, tracks,
                                           native_geometry, foot_scale):
    """Verify cached local offsets equal their bound point on the native shoe mesh."""
    from .foot_geometry import shoe_vertices
    from .material_region_support import shoe_triangles
    from .native_foot_geometry import native_foot_bone_frame, validated_native_foot_geometry
    points = np.asarray(points, dtype=float)
    names = list(names)
    geometry = validated_native_foot_geometry(native_geometry)
    if geometry is None or not np.isfinite(float(foot_scale)) or float(foot_scale) <= 0.:
        raise ValueError('native contact geometry authority is unavailable')
    if points.ndim != 3 or points.shape[1:] != (len(names), 3) or not np.isfinite(points).all():
        raise ValueError('native contact geometry points are malformed')
    triangles = shoe_triangles()
    for side in ('left', 'right'):
        track = tracks.get(side) if isinstance(tracks, dict) else None
        if track is None:
            continue
        _validated_native_side_track(track, len(points), side)
        axes = np.asarray(side_axes[side], dtype=float)
        ankle_i, foot_i = names.index(f'{side}_ankle'), names.index(f'{side}_foot')
        if axes.shape != (len(points), 3) or not np.isfinite(axes).all():
            raise ValueError(f'{side} native contact pose-side axes are unavailable')
        side_geometry = geometry['sides'][side]
        shoes = np.asarray([shoe_vertices(
            points[i, ankle_i], points[i, foot_i], axes[i], None,
            float(foot_scale), native_geometry=side_geometry)
            for i in range(len(points))])
        reference_length = float(side_geometry['ankleToFootJointLengthMeters'])
        for episode in track['episodes']:
            triangle_index = episode['triangleIndex']
            if triangle_index >= len(triangles):
                raise ValueError(f'{side} native contact triangle index is outside shoe topology')
            bary = np.asarray(episode['barycentric'], dtype=float)
            local = np.asarray(episode['materialOffsetLocalMeters'], dtype=float)
            for frame in range(episode['startFrame'], episode['endFrame'] + 1):
                forward, lateral, up, length = native_foot_bone_frame(
                    points[frame, ankle_i], points[frame, foot_i], axes[frame])
                actual = np.einsum('v,vc->c', bary, shoes[frame, triangles[triangle_index]])
                offset = ((forward * local[0] + lateral * local[1] + up * local[2])
                          * (float(length[0]) / reference_length))
                expected = points[frame, ankle_i] + offset
                if not np.allclose(actual, expected, atol=1e-8, rtol=0.):
                    raise ValueError(f'{side} native contact cache differs from its mesh binding')
    return True


def _sample_leg_track(track, first, last, alpha, *, wrap, smooth_limiter):
    active, toes, directions, anchor_ids = track
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
    if anchor_ids is not None:
        same_anchor = np.asarray([
            bool(anchor_ids[int(a)]) and anchor_ids[int(a)] == anchor_ids[int(b)]
            for a, b in zip(first, last)], dtype=bool)
        weight[start_active & end_active & ~same_anchor] = 0.
    return toe_targets, world_direction, weight


def _solve_knee(hip, knee, ankle, target_ankle, thigh_length, shin_length, side):
    """Reach the ankle with exact two-bone lengths and transported knee pole."""
    from .foot_kinematics import _transport_knee_poles

    def lengths(value, label):
        result = np.asarray(value, dtype=float)
        if result.ndim == 0:
            result = np.full(len(hip), float(result))
        if result.shape != (len(hip),) or not np.isfinite(result).all() or np.any(result <= 0.):
            raise ValueError(f'{side} contact foot IK has invalid {label} length')
        return result

    thigh = lengths(thigh_length, 'thigh')
    shin = lengths(shin_length, 'shin')
    reach = target_ankle - hip
    distance = np.linalg.norm(reach, axis=1)
    minimum = np.abs(thigh - shin)
    maximum = thigh + shin
    reachable = ((distance > 1e-9)
                 & (distance >= minimum - 1e-8)
                 & (distance <= maximum + 1e-8))
    if not np.all(reachable):
        indexes = np.flatnonzero(~reachable)
        raise ContactFootIKUnreachable(
            side, indexes, hip, target_ankle, minimum, maximum, distance)

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
    # Keep the near-zero fallback only where the source pole cannot define an
    # IK plane. With a valid pole, solving through the deadzone keeps exact-key
    # samples continuous with their nearby native-contact samples.
    preserve_degenerate = unchanged_ankle & (
        ~pole_defined | (bend_length <= 1e-9))
    return np.where(preserve_degenerate[:, None], knee, solved)


def _rotate_about_unit_axis(direction, axis, angle):
    """Rotate each row of ``direction`` about the matching unit ``axis``."""
    direction = np.asarray(direction, dtype=float)
    axis = np.asarray(axis, dtype=float)
    angle = np.asarray(angle, dtype=float)[:, None]
    cosine, sine = np.cos(angle), np.sin(angle)
    cross = np.cross(axis, direction)
    dot = np.sum(axis * direction, axis=1, keepdims=True)
    return direction * cosine + cross * sine + axis * dot * (1. - cosine)


def _solve_interpolated_contact_leg(hip, knee, source_ankle, ankle, foot, pivot,
                                    thigh_length, shin_length, side,
                                    side_axis=None):
    """Solve an interpolated contact chain, rotating sub-tolerance reach excess.

    Exact keyframe poses are preserved before contact sampling ever reaches this
    helper. Between keys the contact material track and the hip interpolate
    independently, so a Hermite sample can place the derived ankle slightly
    outside the rigid two-bone maximum even though every stored key is
    reachable. That overshoot is an interpolation property, not an unreachable
    key pose.

    A rigid foot anchored at ``pivot`` (the contact toe point, or the bound shoe
    material point in native mode) still has one rotational degree of freedom
    that can move the ankle without moving the contact. Rotate the whole foot
    about that pivot by the minimal angle that brings the ankle onto the reach
    sphere. The contact point and every bone length stay exact, so the playback
    material gates are unchanged instead of inheriting a translation residual.
    Only a sub-tolerance upper over-reach is repaired. Larger over-reach and any
    under-reach still raise the typed ``ContactFootIKUnreachable`` so genuine
    infeasibility is not hidden.
    """
    hip = np.asarray(hip, dtype=float)
    ankle = np.asarray(ankle, dtype=float)
    foot = np.asarray(foot, dtype=float)
    pivot = np.asarray(pivot, dtype=float)
    reach_axis = None if side_axis is None else np.asarray(side_axis, dtype=float)
    try:
        return (_solve_knee(hip, knee, source_ankle, ankle, thigh_length,
                            shin_length, side), ankle, foot, reach_axis)
    except ContactFootIKUnreachable as error:
        from .rig_playback import PLAYBACK_CONTACT_LIMIT_METERS

        distance = np.asarray(error.distance, dtype=float)
        minimum = np.asarray(error.minimum, dtype=float)
        maximum = np.asarray(error.maximum, dtype=float)
        lower_deficit = minimum - distance
        upper_excess = distance - maximum
        if (np.any(lower_deficit > 1e-8)
                or not np.isfinite(upper_excess).all()
                or float(np.max(upper_excess, initial=0.))
                > PLAYBACK_CONTACT_LIMIT_METERS + 1e-12):
            raise
        radius = ankle - pivot
        radius_length = np.linalg.norm(radius, axis=1)
        arm = hip - pivot
        arm_length = np.linalg.norm(arm, axis=1)
        if (np.any(radius_length <= 1e-9) or np.any(arm_length <= 1e-9)
                or not np.isfinite(radius_length).all()
                or not np.isfinite(arm_length).all()):
            raise
        target = maximum * (1. - 1e-9)
        cosine = ((radius_length ** 2 + arm_length ** 2 - target ** 2)
                  / (2. * radius_length * arm_length))
        cosine = np.clip(cosine, -1., 1.)
        current_cosine = np.sum(radius * arm, axis=1) / (radius_length * arm_length)
        current_cosine = np.clip(current_cosine, -1., 1.)
        angle = np.arccos(current_cosine) - np.arccos(cosine)
        angle = np.where(upper_excess > 0., angle, 0.)
        unit_radius = radius / radius_length[:, None]
        axis = np.cross(unit_radius, arm)
        axis_length = np.linalg.norm(axis, axis=1)
        if np.any(axis_length[angle > 0.] <= 1e-12):
            raise
        axis = axis / np.maximum(axis_length, 1e-12)[:, None]
        rotated_radius = _rotate_about_unit_axis(radius, axis, angle)
        projected = pivot + rotated_radius
        projected_foot = pivot + _rotate_about_unit_axis(foot - pivot, axis, angle)
        if reach_axis is not None:
            reach_axis = _rotate_about_unit_axis(reach_axis, axis, angle)
        knee_solution = _solve_knee(
            hip, knee, source_ankle, projected, thigh_length, shin_length, side)
        return knee_solution, projected, projected_foot, reach_axis


def _unit_row(vector):
    vector = np.asarray(vector, dtype=float)
    length = float(np.linalg.norm(vector))
    if not np.isfinite(length) or length <= 1e-12:
        raise ValueError('supported full-sole frame is degenerate')
    return vector / length


def _fullsole_heading_rotation(source_normal, source_heading,
                               target_normal, target_heading):
    """Closest proper rotation mapping the sole plane while keeping heading.

    Reuses the same construction as the joint-plant full-sole helper: the sole
    plane normal is mapped exactly and the in-plane heading is preserved when it
    is defined, so the horizontal foot direction does not drift.
    """
    source_normal = _unit_row(source_normal)
    target_normal = _unit_row(target_normal)
    source_heading = source_heading - source_normal * np.dot(source_heading, source_normal)
    target_heading = target_heading - target_normal * np.dot(target_heading, target_normal)
    if np.linalg.norm(source_heading) <= 1e-8 or np.linalg.norm(target_heading) <= 1e-8:
        return Rotation.align_vectors(
            target_normal[None, :], source_normal[None, :])[0].as_matrix()
    source_heading = _unit_row(source_heading)
    target_heading = _unit_row(target_heading)
    return Rotation.align_vectors(
        np.stack((target_normal, target_heading)),
        np.stack((source_normal, source_heading)))[0].as_matrix()


def _project_fullsole_contact(support, intermediate, distal, material, target,
                              raw_axis, material_normal, target_normal, side):
    """Lay a stationary full sole on its plane about the material anchor.

    The rendered sole is rigidly attached to the ankle/foot frame. The rotation
    that maps the current sole normal onto the observed support normal (while
    preserving the in-plane heading) is applied to the whole shoe; the ankle is
    then placed so the material anchor stays exactly on its stationary target.
    The proximal leg chain is re-solved by the caller, so only bone lengths (not
    the reconstructed knee position) are preserved.
    """
    count = len(support)
    material_normal = np.asarray(material_normal, dtype=float)
    target_normal = np.asarray(target_normal, dtype=float)
    if material_normal.shape != (count, 3) or target_normal.shape != (count, 3):
        raise ValueError('supported full-sole normals must match the chain shape')
    if not np.isfinite(material_normal).all() or not np.isfinite(target_normal).all():
        raise ValueError('supported full-sole normals must be finite')
    distal_vector = distal - intermediate
    distal_length = np.linalg.norm(distal_vector, axis=1)
    if np.any(distal_length <= 1e-10):
        raise ValueError('supported full-sole projection has a zero-length foot bone')
    forward = distal_vector / distal_length[:, None]
    anchor_offset = material - intermediate
    rotations = np.empty((count, 3, 3), dtype=float)
    new_intermediate = np.empty((count, 3), dtype=float)
    for index in range(count):
        source_normal = _unit_row(material_normal[index])
        plane_normal = _unit_row(target_normal[index])
        rotation = _fullsole_heading_rotation(
            source_normal, forward[index], plane_normal, forward[index])
        offset = anchor_offset[index]
        rotations[index] = rotation
        new_intermediate[index] = target[index] - rotation @ offset
    new_distal = new_intermediate + np.einsum('fij,fj->fi', rotations, distal_vector)
    new_axis = np.einsum('fij,fj->fi', rotations, np.asarray(raw_axis, dtype=float))
    new_bone = new_distal - new_intermediate
    new_bone /= np.linalg.norm(new_bone, axis=1, keepdims=True)
    new_axis -= new_bone * np.sum(new_axis * new_bone, axis=1, keepdims=True)
    new_axis_length = np.linalg.norm(new_axis, axis=1, keepdims=True)
    if np.any(new_axis_length <= 1e-10):
        raise ValueError('supported full-sole projection produced a degenerate side axis')
    new_axis /= new_axis_length
    return new_intermediate, new_distal, new_axis, rotations


def project_supported_material_contact(support_point, intermediate_joint, bone_end,
                                       material_point, target, side_axis, side, *,
                                       material_normal=None, target_normal=None):
    """Reach a material target while keeping the proximal support point fixed.

    The support-to-intermediate and intermediate-to-material lengths define a
    two-link chain. The returned rotation transports both the distal bone and
    its side axis, so callers can re-bake the corresponding terminal FK pose.

    When ``material_normal`` (current rendered sole normal) and ``target_normal``
    (observed support plane normal) are supplied the role-aware full-sole pose is
    enforced: the whole rigid sole is laid on the support plane while the anchor
    and chain reach are preserved. Otherwise the legacy single-point behaviour is
    returned unchanged.
    """
    arrays = [np.asarray(value, dtype=float) for value in (
        support_point, intermediate_joint, bone_end, material_point, target, side_axis)]
    if any(value.ndim != 2 or value.shape[1] != 3 for value in arrays):
        raise ValueError('supported material projection inputs must have shape (frames, 3)')
    count = len(arrays[0])
    if count <= 0 or any(value.shape != (count, 3) for value in arrays):
        raise ValueError('supported material projection inputs must have matching nonempty shapes')
    if any(not np.isfinite(value).all() for value in arrays):
        raise ValueError('supported material projection inputs must be finite')
    support, intermediate, distal, material, destination, raw_axis = arrays
    if material_normal is not None and target_normal is not None:
        return _project_fullsole_contact(
            support, intermediate, distal, material, destination, raw_axis,
            material_normal, target_normal, str(side))
    first_length = np.linalg.norm(intermediate - support, axis=1)
    second_vector = material - intermediate
    second_length = np.linalg.norm(second_vector, axis=1)
    distal_vector = distal - intermediate
    distal_length = np.linalg.norm(distal_vector, axis=1)
    axis_length = np.linalg.norm(raw_axis, axis=1)
    if np.any(first_length <= 1e-10) or np.any(second_length <= 1e-10):
        raise ValueError('supported material projection has a zero-length chain link')
    if np.any(distal_length <= 1e-10) or np.any(axis_length <= 1e-10):
        raise ValueError('supported material projection has an undefined distal frame')

    new_intermediate = _solve_knee(
        support, intermediate, material, destination,
        first_length, second_length, str(side))
    source_direction = second_vector / second_length[:, None]
    target_vector = destination - new_intermediate
    target_length = np.linalg.norm(target_vector, axis=1)
    if np.any(target_length <= 1e-10):
        raise ValueError('supported material projection has an undefined target direction')
    target_direction = target_vector / target_length[:, None]

    rotations = np.empty((count, 3, 3), dtype=float)
    distal_axis = distal_vector / distal_length[:, None]
    projected_axis = raw_axis - distal_axis * np.sum(raw_axis * distal_axis, axis=1, keepdims=True)
    projected_axis_length = np.linalg.norm(projected_axis, axis=1)
    if np.any(projected_axis_length <= 1e-10):
        raise ValueError('supported material projection side axis is collinear with the distal bone')
    projected_axis /= projected_axis_length[:, None]
    for index, (source, target_direction_row) in enumerate(zip(
            source_direction, target_direction)):
        cross = np.cross(source, target_direction_row)
        cosine = float(np.clip(np.dot(source, target_direction_row), -1., 1.))
        skew = np.asarray([[0., -cross[2], cross[1]],
                           [cross[2], 0., -cross[0]],
                           [-cross[1], cross[0], 0.]])
        if cosine > -1. + 1e-10:
            rotations[index] = np.eye(3) + skew + (skew @ skew) / (1. + cosine)
        else:
            axis = projected_axis[index] - source * np.dot(projected_axis[index], source)
            axis_length = np.linalg.norm(axis)
            if axis_length <= 1e-10:
                basis = np.eye(3)[int(np.argmin(np.abs(source)))]
                axis = basis - source * np.dot(basis, source)
                axis_length = np.linalg.norm(axis)
            axis /= axis_length
            rotations[index] = 2. * np.outer(axis, axis) - np.eye(3)

    new_distal = new_intermediate + np.einsum('fij,fj->fi', rotations, distal_vector)
    new_axis = np.einsum('fij,fj->fi', rotations, projected_axis)
    new_bone_direction = new_distal - new_intermediate
    new_bone_direction /= np.linalg.norm(new_bone_direction, axis=1, keepdims=True)
    new_axis -= new_bone_direction * np.sum(new_axis * new_bone_direction, axis=1, keepdims=True)
    new_axis_length = np.linalg.norm(new_axis, axis=1, keepdims=True)
    if np.any(new_axis_length <= 1e-10):
        raise ValueError('supported material projection produced a degenerate side axis')
    new_axis /= new_axis_length
    return new_intermediate, new_distal, new_axis, rotations


def sample_contact_foot_tracks(rig, cursors, points, *, wrap=False, preserve_keys=True,
                               native_foot_geometry=None, foot_scale=None,
                               return_side_axes=False):
    """Apply optional contact foot tracks to already sampled fixed-rig points.

    Exact key samples are returned unchanged. Between keys, a contacted toe
    follows a C1 world-space Hermite track while ankle and knee are rebuilt as
    a rigid, branch-preserving two-bone chain.
    """
    tracks = rig.get('contactFootTracks')
    if tracks is None:
        sampled = np.asarray(points, dtype=float).copy()
        from .native_material_frames import material_axes
        axes = material_axes(rig, cursors, wrap=wrap) or {}
        return (sampled, axes) if return_side_axes else sampled
    if not isinstance(tracks, dict) or tracks.get('version') not in (1, 2):
        raise ValueError('contactFootTracks has an unsupported or malformed version')
    if tracks.get('version') == 2 and type(tracks.get('version')) is not int:
        raise ValueError('contactFootTracks has an unsupported or malformed version')
    if tracks['version'] == 2:
        if set(tracks) - {'version', 'left', 'right'}:
            raise ValueError('contactFootTracks has unsupported fields')
        return _sample_native_material_contact_tracks(
            rig, cursors, points, wrap=wrap, preserve_keys=preserve_keys,
            native_foot_geometry=native_foot_geometry, foot_scale=foot_scale,
            return_side_axes=return_side_axes)

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
        knee, effective_ankle, effective_toe, _ = _solve_interpolated_contact_leg(
            active_hip, sampled[active_queries, knee_index], sampled[active_queries, ankle_index],
            ankle[active_queries], toe[active_queries], toe[active_queries],
            thigh_length, shin_length, side)
        sampled[active_queries, toe_index] = effective_toe
        sampled[active_queries, ankle_index] = effective_ankle
        sampled[active_queries, knee_index] = knee
    return (sampled, {}) if return_side_axes else sampled


def _sample_native_material_contact_tracks(rig, cursors, points, *, wrap, preserve_keys,
                                           native_foot_geometry=None, foot_scale=None,
                                           return_side_axes=False, measure_unprotected_reach=False):
    cursors = np.asarray(cursors, dtype=float).reshape(-1)
    count = len(rig.get('coordinates', ()))
    names = list(rig['jointNames'])
    tracks = rig['contactFootTracks']
    if count < 2 or not np.isfinite(cursors).all():
        raise ValueError('native contact sampling requires finite cursors and at least two rig frames')
    points = np.asarray(points, dtype=float)
    sampled = points.copy()
    reach_rows = np.zeros((len(cursors), 2, 2), dtype=float)
    reach_active = np.zeros((len(cursors), 2), dtype=bool)
    if sampled.shape != (len(cursors), len(names), 3) or not np.isfinite(sampled).all():
        raise ValueError('sampled points must have shape (queries, joints, 3) and be finite')
    normalized = np.mod(cursors, count) if wrap else np.clip(cursors, 0., count - 1.)
    first = np.floor(normalized).astype(int)
    last = (first + 1) % count if wrap else np.minimum(first + 1, count - 1)
    alpha = normalized - first
    exact_key = np.isclose(normalized, np.round(normalized), atol=1e-12, rtol=0.)
    smooth_limiter = rig.get('interpolation') != 'limited_quaternion_hermite_v1'
    offsets = np.asarray(rig['offsets'], dtype=float)
    active_native = any(np.any(np.asarray(track.get('active'), dtype=bool))
                        for side, track in tracks.items() if side in {'left', 'right'})
    geometry = None
    sampled_side_axes = {}
    active_queries_by_side = {}
    contact_weights_by_side = {}
    from .native_material_frames import material_axes
    original_side_axes = material_axes(rig, normalized, wrap=wrap) or {}
    if 'materialFrames' not in rig:
        from .rig_playback import native_material_sampling_payload
        material_payload = native_material_sampling_payload(rig)
        if material_payload is not None:
            from .foot_geometry import _sample_material_foot_geometry
            original_side_axes = {
                side: frame['lateral'] for side, frame in
                _sample_material_foot_geometry(material_payload, normalized, points).items()}
    else:
        sampled_side_axes = {side: axes.copy() for side, axes in original_side_axes.items()}
    protected_joint_masks = {}
    if 'supportJointTracks' in rig:
        from .support_joint_tracks import sample_support_joint_mask
        support_tracks = rig.get('_supportJointTracksForSampling')
        if support_tracks is None:
            raise ValueError('supportJointTracks were not validated for sampling')
        protected_names = [f'{side}_{part}' for side in ('left', 'right')
                           for part in ('knee', 'ankle', 'foot')]
        protected_joint_masks = {
            joint: sample_support_joint_mask(
                support_tracks, joint, cursors, count, wrap=wrap)
            for joint in protected_names
        }
    if active_native:
        from .native_foot_geometry import validated_native_foot_geometry
        geometry = validated_native_foot_geometry(native_foot_geometry)
        try:
            foot_scale = float(foot_scale)
        except (TypeError, ValueError, OverflowError):
            foot_scale = float('nan')
        if geometry is None or not np.isfinite(foot_scale) or foot_scale <= 0.:
            raise ValueError('native contact sampling requires root nativeFootGeometry and canonical footScale')
    for side in ('left', 'right'):
        if side not in tracks:
            continue
        track = _validated_native_side_track(tracks[side], count, side)
        active, directions, side_axes, anchor_ids = track
        indices = {part: names.index(f'{side}_{part}') if f'{side}_{part}' in names else None
                   for part in ('hip', 'knee', 'ankle', 'foot')}
        if any(index is None for index in indices.values()):
            raise ValueError(f'{side} native contact track requires a complete leg chain')
        direction = _sample_track_directions(
            directions, first, last, alpha, wrap=wrap,
            smooth_limiter=smooth_limiter)
        axes = hermite_samples(
            side_axes, first, last, alpha, wrap=wrap,
            smooth_limiter=smooth_limiter)
        axes -= direction * np.sum(axes * direction, axis=1, keepdims=True)
        axis_length = np.linalg.norm(axes, axis=1)
        if np.any((axis_length <= 1e-9) & (active[first] | active[last])):
            raise ValueError(f'{side} native contact side axis is collinear with the foot direction')
        axes /= np.maximum(axis_length[:, None], 1e-12)
        sampled_side_axes[side] = (original_side_axes[side].copy()
                                   if 'materialFrames' in rig else axes.copy())
        original_side_axes.setdefault(side, axes.copy())
        episode_by_frame = _native_episode_by_frame(tracks[side])
        start_active, end_active = active[first], active[last]
        smooth = alpha * alpha * (3. - 2. * alpha)
        weight = np.where(start_active & end_active, 1.,
                          np.where(start_active, 1. - smooth,
                                   np.where(end_active, smooth, 0.)))
        same_contact = _native_interval_contact_mask(
            start_active, end_active, first, last, episode_by_frame, anchor_ids)
        weight[start_active & end_active & ~same_contact] = 0.
        if preserve_keys:
            # Exact keys keep their stored pose. Fade only the between-key
            # contact projection to zero at both endpoints so the sampled path
            # meets those keys continuously (with zero correction slope).
            envelope = 16. * alpha**2 * (1. - alpha)**2
            weight = np.where(exact_key, weight, weight * envelope)
        protected_knee = protected_joint_masks.get(
            f'{side}_knee', np.zeros(len(cursors), dtype=bool))
        supported_active_queries = (weight > 0.) & protected_knee
        legacy_active_queries = ((weight > 0.) & (~exact_key | (not preserve_keys))
                                 & ~protected_knee)
        active_queries = legacy_active_queries | supported_active_queries
        active_queries_by_side[side] = active_queries
        contact_weights_by_side[side] = weight
        episode_for_query = []
        for a, b, start_on, end_on in zip(first, last, start_active, end_active):
            candidate = episode_by_frame.get(int(a)) if start_on else None
            if candidate is None and end_on:
                candidate = episode_by_frame.get(int(b))
            episode_for_query.append(candidate)
        ankle_i, foot_i = indices['ankle'], indices['foot']
        cache_queries = ((weight > 0.) | (exact_key & preserve_keys & active[first]))
        if np.any(cache_queries):
            from .foot_geometry import shoe_vertices
            from .material_region_support import shoe_triangles
            from .native_foot_geometry import native_foot_bone_frame
            triangles = shoe_triangles()
            mesh_ball = sampled[:, ankle_i] + direction * float(np.linalg.norm(offsets[foot_i]))
            shoes = shoe_vertices(
                sampled[:, ankle_i], mesh_ball, axes, None, foot_scale,
                native_geometry=geometry['sides'][side])
            for query in np.flatnonzero(cache_queries):
                episode = episode_for_query[query]
                if episode is None:
                    raise ValueError(f'{side} active native contact query has no episode')
                triangle_index = int(episode['triangleIndex'])
                if triangle_index >= len(triangles):
                    raise ValueError(f'{side} native contact triangle is outside shoe topology')
                bary = np.asarray(episode['barycentric'], dtype=float)
                local = np.asarray(episode['materialOffsetLocalMeters'], dtype=float)
                reference_length = float(episode['referenceLengthMeters'])
                forward, lateral, up, current_length = native_foot_bone_frame(
                    sampled[query, ankle_i], mesh_ball[query], axes[query])
                actual = bary @ shoes[query, triangles[triangle_index]]
                offset = ((forward * local[0] + lateral * local[1] + up * local[2])
                          * (float(current_length[0]) / reference_length))
                expected = sampled[query, ankle_i] + offset
                if not np.allclose(actual, expected, atol=1e-7, rtol=0.):
                    raise ValueError(f'{side} native contact cache differs from its mesh binding')
        if not np.any(active_queries):
            continue
        hip_i, knee_i = indices['hip'], indices['knee']
        bone_length = float(np.linalg.norm(offsets[foot_i]))
        thigh_length = float(np.linalg.norm(offsets[knee_i]))
        shin_length = float(np.linalg.norm(offsets[ankle_i]))
        if min(bone_length, thigh_length, shin_length) <= 1e-9:
            raise ValueError(f'{side} native contact leg lengths are invalid')
        forward, lateral = direction, axes
        ankle = sampled[:, ankle_i].copy()
        foot = sampled[:, foot_i].copy()
        material_pivots = np.zeros_like(ankle)
        # The fitter measures only the unprotected hip-to-ankle branch here.
        # Protected knee/material chains retain their independent hard checks.
        for query in np.flatnonzero(supported_active_queries if not measure_unprotected_reach
                                   else np.zeros(len(cursors), dtype=bool)):
            episode = episode_for_query[query]
            if episode is None:
                raise ValueError(f'{side} protected support query has no native material episode')
            raw_ankle = sampled[query, ankle_i]
            raw_foot = sampled[query, foot_i]
            raw_bone = raw_foot - raw_ankle
            raw_length = float(np.linalg.norm(raw_bone))
            if raw_length <= 1e-10:
                raise ValueError(f'{side} protected support query has a zero-length foot bone')
            raw_forward = raw_bone / raw_length
            original_lateral = original_side_axes[side][query]
            original_lateral = _unit_row(
                original_lateral - raw_forward * float(np.dot(original_lateral, raw_forward)))
            target_lateral = _unit_row(
                axes[query] - raw_forward * float(np.dot(axes[query], raw_forward)))
            raw_lateral = (1. - weight[query]) * original_lateral + weight[query] * target_lateral
            raw_lateral_length = float(np.linalg.norm(raw_lateral))
            if raw_lateral_length <= 1e-10:
                raise ValueError(f'{side} protected support query has a degenerate side axis')
            raw_lateral /= raw_lateral_length
            raw_up = np.cross(raw_lateral, raw_forward)
            local = np.asarray(episode['materialOffsetLocalMeters'], dtype=float)
            reference_length = float(episode['referenceLengthMeters'])
            material_offset = ((raw_forward * local[0] + raw_lateral * local[1]
                                + raw_up * local[2]) * (raw_length / reference_length))
            material_point = raw_ankle + material_offset
            if episode['mode'] == 'verticalOnly':
                normal = np.asarray(episode['surfaceNormal'], dtype=float)
                target = material_point + (
                    float(episode['planeOffsetMeters']) - np.dot(normal, material_point)) * normal
            else:
                target = np.asarray(episode['targetWorld'], dtype=float)
            target = material_point + weight[query] * (target - material_point)
            material_normal = target_normal = None
            sole_local = episode.get('soleNormalLocalMeters')
            if (str(episode.get('regionRole')) == 'full_sole'
                    and str(episode.get('mode')) == 'stationary'
                    and sole_local is not None):
                local_normal = np.asarray(sole_local, dtype=float)
                raw_up = np.cross(raw_lateral, raw_forward)
                material_normal = (raw_forward * local_normal[0]
                                   + raw_lateral * local_normal[1]
                                   + raw_up * local_normal[2])[None, :]
                target_normal = np.asarray(
                    episode['surfaceNormal'], dtype=float)[None, :]
                # Plane alignment is part of the same correction as the
                # material anchor. Fade its rotation with the anchor so a
                # preserved key is not approached through a different shoe
                # orientation.
                blended_normal = raw_up + weight[query] * (
                    target_normal[0] - raw_up)
                blended_length = float(np.linalg.norm(blended_normal))
                if blended_length <= 1e-10:
                    raise ValueError('native full-sole contact normal interpolation is degenerate')
                target_normal = (blended_normal / blended_length)[None, :]
            new_ankle, new_foot, new_axis, _ = project_supported_material_contact(
                sampled[query:query + 1, knee_i],
                sampled[query:query + 1, ankle_i],
                sampled[query:query + 1, foot_i],
                material_point[None, :], target[None, :], raw_lateral[None, :], side,
                material_normal=material_normal, target_normal=target_normal)
            if material_normal is not None:
                # Full-sole flattening is a rigid shoe patch, so re-solve the
                # knee from the fixed hip; bone lengths are preserved and the
                # reconstructed knee is free to articulate.
                try:
                    new_knee = _solve_knee(
                        sampled[query:query + 1, hip_i],
                        sampled[query:query + 1, knee_i],
                        sampled[query:query + 1, ankle_i], new_ankle,
                        np.array([np.linalg.norm(offsets[knee_i])]),
                        np.array([np.linalg.norm(offsets[ankle_i])]), side)
                except ValueError:
                    # Unreachable flat anchored sole: keep the legacy point
                    # projection instead of fabricating reach.
                    new_ankle, new_foot, new_axis, _ = (
                        project_supported_material_contact(
                            sampled[query:query + 1, knee_i],
                            sampled[query:query + 1, ankle_i],
                            sampled[query:query + 1, foot_i],
                            material_point[None, :], target[None, :],
                            raw_lateral[None, :], side))
                else:
                    sampled[query, knee_i] = new_knee[0]
            sampled[query, ankle_i] = new_ankle[0]
            sampled[query, foot_i] = new_foot[0]
            axes[query] = new_axis[0]
            sampled_side_axes[side][query] = new_axis[0]

        for query in np.flatnonzero(legacy_active_queries):
            episode = episode_for_query[query]
            if episode is None:
                raise ValueError(f'{side} active native contact query has no episode')
            weight_at_query = float(weight[query])
            raw_ankle = ankle[query]
            raw_bone = foot[query] - raw_ankle
            raw_length = float(np.linalg.norm(raw_bone))
            if raw_length <= 1e-10:
                raise ValueError(f'{side} legacy support query has a zero-length foot bone')
            raw_forward = raw_bone / raw_length
            # The stored key pose and the intended material contact can use
            # different foot directions. Blend the correction frame with the
            # same projection weight so both the ankle shift and the foot
            # heading approach the raw pose as that weight vanishes. The distal
            # bone length stays fixed, so blending the frame cannot shorten a
            # bone the way interpolating output points would.
            blended_forward = ((1. - weight_at_query) * raw_forward
                               + weight_at_query * forward[query])
            blended_forward_length = float(np.linalg.norm(blended_forward))
            if blended_forward_length <= 1e-10:
                raise ValueError(f'{side} legacy contact foot direction is undefined')
            blended_forward /= blended_forward_length
            raw_axis = original_side_axes[side][query]
            raw_lateral = raw_axis - raw_forward * float(np.dot(raw_axis, raw_forward))
            raw_lateral_length = float(np.linalg.norm(raw_lateral))
            if raw_lateral_length <= 1e-10:
                raise ValueError(f'{side} legacy support query has a degenerate side axis')
            raw_lateral /= raw_lateral_length
            blended_lateral = ((1. - weight_at_query) * raw_lateral
                               + weight_at_query * lateral[query])
            blended_lateral -= blended_forward * float(
                np.dot(blended_lateral, blended_forward))
            blended_lateral_length = float(np.linalg.norm(blended_lateral))
            if blended_lateral_length <= 1e-10:
                raise ValueError(f'{side} legacy contact side axis is degenerate')
            blended_lateral /= blended_lateral_length
            sampled_side_axes[side][query] = blended_lateral
            blended_up = np.cross(blended_lateral, blended_forward)
            local = np.asarray(episode['materialOffsetLocalMeters'], dtype=float)
            material_offset = ((blended_forward * local[0]
                                + blended_lateral * local[1]
                                + blended_up * local[2])
                               * (bone_length / float(episode['referenceLengthMeters'])))
            material_point = raw_ankle + material_offset
            if episode['mode'] == 'verticalOnly':
                normal = np.asarray(episode['surfaceNormal'], dtype=float)
                target = material_point + (
                    float(episode['planeOffsetMeters']) - np.dot(normal, material_point)) * normal
            else:
                target = np.asarray(episode['targetWorld'], dtype=float)
            target = material_point + weight_at_query * (target - material_point)
            ankle[query] = target - material_offset
            foot[query] = ankle[query] + blended_forward * bone_length
            material_pivots[query] = target
        if np.any(legacy_active_queries):
            if measure_unprotected_reach:
                side_index = ('left', 'right').index(side)
                distance = np.linalg.norm(
                    ankle[legacy_active_queries] - sampled[legacy_active_queries, hip_i], axis=1)
                reach_rows[legacy_active_queries, side_index, 0] = np.maximum(
                    max(abs(thigh_length - shin_length), 1e-9) - distance, 0.)
                reach_rows[legacy_active_queries, side_index, 1] = np.maximum(
                    distance - (thigh_length + shin_length), 0.)
                reach_active[legacy_active_queries, side_index] = True
                continue
            knee, effective_ankle, effective_foot, effective_axis = _solve_interpolated_contact_leg(
                sampled[legacy_active_queries, hip_i], sampled[legacy_active_queries, knee_i],
                sampled[legacy_active_queries, ankle_i], ankle[legacy_active_queries],
                foot[legacy_active_queries], material_pivots[legacy_active_queries],
                thigh_length, shin_length, side,
                side_axis=sampled_side_axes[side][legacy_active_queries])
            sampled[legacy_active_queries, ankle_i] = effective_ankle
            sampled[legacy_active_queries, foot_i] = effective_foot
            sampled[legacy_active_queries, knee_i] = knee
            if effective_axis is not None:
                sampled_side_axes[side][legacy_active_queries] = effective_axis

    if measure_unprotected_reach:
        return reach_rows, reach_active

    execution = rig.get('_canonicalExecutionForSampling') or {}
    if execution.get('legs') == 'mirrored' and sampled_side_axes:
        left_active = active_queries_by_side.get('left', np.zeros(len(cursors), dtype=bool))
        right_active = active_queries_by_side.get('right', np.zeros(len(cursors), dtype=bool))
        unilateral = left_active ^ right_active
        if preserve_keys:
            unilateral &= ~exact_key
        if np.any(unilateral):
            from .foot_geometry import transport_sides
            left_hip_i = names.index('left_hip')
            right_hip_i = names.index('right_hip')
            left_indices = [names.index(f'left_{part}') for part in ('hip', 'knee', 'ankle', 'foot')]
            right_indices = [names.index(f'right_{part}') for part in ('hip', 'knee', 'ankle', 'foot')]
            offset_lengths = np.asarray([
                np.linalg.norm(offsets[names.index(f'{side}_{part}')])
                for side in ('left', 'right') for part in ('knee', 'ankle', 'foot')
            ]).reshape(2, 3)
            if not np.allclose(offset_lengths[0], offset_lengths[1], atol=1e-6, rtol=1e-6):
                raise ValueError('mirrored native contact sampling requires equal paired leg lengths')
            hip_axis = sampled[:, right_hip_i] - sampled[:, left_hip_i]
            hip_length = np.linalg.norm(hip_axis, axis=1)
            if np.any(hip_length[unilateral] <= 1e-9):
                raise ValueError('mirrored native contact sampling requires distinct hip anchors')
            hip_axis /= np.maximum(hip_length[:, None], 1e-12)
            for query in np.flatnonzero(unilateral):
                normal = hip_axis[query]

                def reflect(vector):
                    return vector - 2.0 * float(np.dot(vector, normal)) * normal

                driver_is_left = bool(left_active[query])
                driver_side = 'left' if driver_is_left else 'right'
                mirror_weight = float(contact_weights_by_side[driver_side][query])
                driver_indices = left_indices if driver_is_left else right_indices
                opposite_indices = right_indices if driver_is_left else left_indices
                opposite_side = 'right' if driver_is_left else 'left'
                opposite_ankle_protected = protected_joint_masks.get(
                    f'{opposite_side}_ankle', np.zeros(len(cursors), dtype=bool))[query]
                opposite_foot_protected = protected_joint_masks.get(
                    f'{opposite_side}_foot', np.zeros(len(cursors), dtype=bool))[query]
                if opposite_ankle_protected or opposite_foot_protected:
                    # Preserve validated contralateral supports; the canonical
                    # validator remains responsible for any unresolved symmetry conflict.
                    continue
                opposite_knee_protected = protected_joint_masks.get(
                    f'{opposite_side}_knee', np.zeros(len(cursors), dtype=bool))[query]
                start = 2 if opposite_knee_protected else 1
                for segment in range(start, len(driver_indices)):
                    driver_parent, driver_joint = driver_indices[segment - 1:segment + 1]
                    opposite_parent, opposite_joint = opposite_indices[segment - 1:segment + 1]
                    original = points[query, opposite_joint] - points[query, opposite_parent]
                    mirrored = reflect(sampled[query, driver_joint] - sampled[query, driver_parent])
                    rotation, _ = Rotation.align_vectors(mirrored[None, :], original[None, :])
                    # Rotate each rigid segment; Cartesian blending would shorten bones.
                    offset = Rotation.from_rotvec(rotation.as_rotvec() * mirror_weight).apply(original)
                    sampled[query, opposite_joint] = sampled[query, opposite_parent] + offset

                driver_axis = sampled_side_axes.get(driver_side)
                if driver_axis is not None:
                    if (driver_axis.shape != (len(cursors), 3)
                            or not np.isfinite(driver_axis[query]).all()):
                        raise ValueError('mirrored native contact driver side axis is unavailable')
                    inferred_axis = -reflect(driver_axis[query])
                    opposite_ankle = sampled[query, opposite_indices[2]]
                    opposite_foot = sampled[query, opposite_indices[3]]
                    forward = opposite_foot - opposite_ankle
                    forward_length = np.linalg.norm(forward)
                    if forward_length <= 1e-9:
                        raise ValueError('mirrored native contact sampling produced a zero-length foot bone')
                    forward /= forward_length
                    inferred_axis -= forward * float(np.dot(inferred_axis, forward))
                    axis_length = np.linalg.norm(inferred_axis)
                    if axis_length <= 1e-9:
                        raise ValueError('mirrored native contact side axis became collinear')
                    inferred_axis /= axis_length
                    original_forward = (points[query, opposite_indices[3]]
                                        - points[query, opposite_indices[2]])
                    original_forward /= np.linalg.norm(original_forward)
                    original_axis = original_side_axes.get(opposite_side)
                    if original_axis is None:
                        original_axis = -reflect(original_side_axes[driver_side][query])
                    else:
                        original_axis = original_axis[query]
                    original_axis = transport_sides(
                        original_axis[None, :], original_forward[None, :],
                        forward[None, :], original_axis[None, :])[0]
                    twist = np.arctan2(np.dot(forward, np.cross(original_axis, inferred_axis)),
                                       np.dot(original_axis, inferred_axis)) * mirror_weight
                    blended_axis = (original_axis * np.cos(twist)
                                    + np.cross(forward, original_axis) * np.sin(twist))
                    if opposite_side not in sampled_side_axes:
                        sampled_side_axes[opposite_side] = np.full(
                            (len(cursors), 3), np.nan, dtype=float)
                    sampled_side_axes[opposite_side][query] = blended_axis

    return (sampled, sampled_side_axes) if return_side_axes else sampled


def native_material_playback_residuals(points, names, offsets, tracks, positions, *,
                                       wrap=False, interpolation=None,
                                       return_metrics=False, key_side_axes=None,
                                       native_geometry=None, foot_scale=None,
                                       fractional_side_axes=None):
    """Playback-clock material contact residuals for active native episodes.

    The playback sampler reconstructs a contacted shoe material point from the
    episode's cached material offset expressed in the pose-transported material
    frame. Supply ``fractional_side_axes`` (the same FK-transported axes used to
    serialize contact tracks) to measure that candidate frame at fractional
    samples; without it the stored track direction/side axis is still sampled so
    existing public callers and the published artifact remain supported. A fit
    that ignores the candidate frame scores a stale source frame and pins the
    inferred original ankle placement, rejecting legal rotation about the real
    material anchor.

    This evaluator reproduces the playback material geometry and clock exactly:
    same episode offset/reference length, same stored direction/side-axis
    interpolation, same anchor and endpoint weighting, and the same fade
    envelope that preserves exact keys. Between keys the residual is the
    world-space correction playback would request. Height-only episodes are
    also measured at exact keys because playback deliberately leaves stored
    poses untouched there; when actual key geometry is supplied the key row is
    evaluated on that calibrated shoe, otherwise the stored track frame is the
    only available clock. Stationary full-XYZ keys are measured on the
    calibrated actual shoe when that geometry is supplied (the keyframe anchor
    proof); without it they stay excluded because the playback clock preserves
    exact key poses. Metrics split every sample by clock (keyframe/playback) and
    by authority mode (stationary XYZ / height-only plane).
    """
    values = np.asarray(points, dtype=float)
    names = list(names)
    cursors = np.asarray(positions, dtype=float).reshape(-1)
    empty = np.empty((len(cursors), 0), dtype=float)
    clock_mode_keys = {
        f'{clock}{kind}{suffix}': 0 if suffix == 'SampleCount' else 0.
        for clock in ('keyframe', 'playback')
        for kind in ('Stationary', 'Height')
        for suffix in ('SampleCount', 'MaximumErrorMeters')
    }
    metrics = {'available': False, 'sampleCount': 0, 'maximumErrorMeters': 0.,
               'bySide': {}, **clock_mode_keys}
    if not isinstance(tracks, dict) or tracks.get('version') != 2:
        return (empty, metrics) if return_metrics else empty
    if (values.ndim != 3 or values.shape[1:] != (len(names), 3)
            or not np.isfinite(values).all() or not np.isfinite(cursors).all()):
        raise ValueError('native material playback residual inputs are malformed')
    offsets = np.asarray(offsets, dtype=float)
    if offsets.shape != (len(names), 3) or not np.isfinite(offsets).all():
        raise ValueError('native material playback residual needs finite rig offsets')
    columns = []
    maximum = 0.
    sample_count = 0
    clock_mode_totals = {
        f'{clock}{kind}': {'sampleCount': 0, 'maximumErrorMeters': 0.}
        for clock in ('keyframe', 'playback')
        for kind in ('Stationary', 'Height')
    }
    smooth_limiter = str(interpolation) != 'limited_quaternion_hermite_v1'
    for side in ('left', 'right'):
        track = tracks.get(side)
        if track is None:
            continue
        if not all(name in names for name in
                   (f'{side}_ankle', f'{side}_foot')):
            continue
        count = len(track.get('active', ()))
        active, directions, side_axes, anchor_ids = _validated_native_side_track(
            track, count, side)
        ankle_i, foot_i = names.index(f'{side}_ankle'), names.index(f'{side}_foot')
        bone_length = float(np.linalg.norm(offsets[foot_i]))
        if not np.isfinite(bone_length) or bone_length <= 1e-9:
            raise ValueError(f'{side} native material playback foot length is invalid')
        normalized = np.mod(cursors, count) if wrap else np.clip(cursors, 0., count - 1.)
        first = np.floor(normalized).astype(int)
        last = (first + 1) % count if wrap else np.minimum(first + 1, count - 1)
        alpha = normalized - first
        exact_key = np.isclose(normalized, np.round(normalized), atol=1e-12, rtol=0.)
        direction = _sample_track_directions(
            directions, first, last, alpha, wrap=wrap,
            smooth_limiter=smooth_limiter)
        axes = hermite_samples(
            side_axes, first, last, alpha, wrap=wrap,
            smooth_limiter=smooth_limiter)
        axes -= direction * np.sum(axes * direction, axis=1, keepdims=True)
        axis_length = np.linalg.norm(axes, axis=1)
        if np.any((axis_length <= 1e-9) & (active[first] | active[last])):
            raise ValueError(f'{side} native material playback side axis is degenerate')
        axes /= np.maximum(axis_length[:, None], 1e-12)
        episode_by_frame = _native_episode_by_frame(track)
        start_active, end_active = active[first], active[last]
        smooth = alpha * alpha * (3. - 2. * alpha)
        weight = np.where(start_active & end_active, 1.,
                          np.where(start_active, 1. - smooth,
                                   np.where(end_active, smooth, 0.)))
        same_contact = _native_interval_contact_mask(
            start_active, end_active, first, last, episode_by_frame, anchor_ids)
        weight[start_active & end_active & ~same_contact] = 0.
        if np.any(weight > 0.):
            envelope = 16. * alpha**2 * (1. - alpha)**2
            weight = np.where(exact_key, weight, weight * envelope)
        key_frames = np.rint(normalized).astype(int)
        key_frames = key_frames % count if wrap else np.clip(key_frames, 0, count - 1)
        key_episodes = [episode_by_frame.get(int(frame)) for frame in key_frames]
        height_only_key = np.zeros(len(cursors), dtype=bool)
        stationary_key = np.zeros(len(cursors), dtype=bool)
        for key_index in np.flatnonzero(exact_key & active[key_frames]):
            episode = key_episodes[key_index]
            if episode is None:
                continue
            mode = str(episode['mode'])
            height_only_key[key_index] = mode == 'verticalOnly'
            stationary_key[key_index] = mode == 'stationary'
        key_axes = None if key_side_axes is None else np.asarray(
            (key_side_axes or {}).get(side), dtype=float)
        if key_axes is not None and (key_axes.shape != (len(cursors), 3)
                                     or not np.isfinite(key_axes).all()):
            raise ValueError(f'{side} native key material side axes are malformed')
        playback_axes = None if fractional_side_axes is None else np.asarray(
            (fractional_side_axes or {}).get(side), dtype=float)
        if playback_axes is not None and (playback_axes.shape != (len(cursors), 3)
                                          or not np.isfinite(playback_axes).all()):
            raise ValueError(
                f'{side} native playback material side axes are malformed')
        key_geometry = None
        if key_axes is not None and native_geometry is not None:
            from .native_foot_geometry import validated_native_foot_geometry
            key_geometry = validated_native_foot_geometry(native_geometry)
            try:
                key_scale = float(foot_scale)
            except (TypeError, ValueError, OverflowError) as error:
                raise ValueError(
                    f'{side} native key material needs a finite foot scale') from error
            if key_geometry is None or not np.isfinite(key_scale) or key_scale <= 0.:
                raise ValueError(f'{side} native key material needs calibrated geometry')
        # Height-only keys are always a keyframe plane contract. A stationary
        # keyframe XYZ anchor is measured on the calibrated actual shoe when
        # that geometry is supplied; the playback clock keeps excluding exact
        # keys because playback deliberately preserves them.
        measured_key = height_only_key | (stationary_key & (key_geometry is not None))
        weight[height_only_key] = 1.
        weight[stationary_key] = 1.
        query = (weight > 0.) & (~exact_key | measured_key)
        if not np.any(query):
            continue
        residual = np.zeros((len(cursors), 3), dtype=float)
        side_maximum = 0.
        side_count = 0
        side_totals = {
            key: {'sampleCount': 0, 'maximumErrorMeters': 0.}
            for key in clock_mode_totals
        }
        for query_index in np.flatnonzero(query):
            key_clock = bool(exact_key[query_index])
            if key_clock:
                episode = key_episodes[query_index]
            else:
                a, b = int(first[query_index]), int(last[query_index])
                episode = (episode_by_frame.get(a) if start_active[query_index]
                           else episode_by_frame.get(b))
            if episode is None:
                raise ValueError(f'{side} active native material query has no episode')
            local = np.asarray(episode['materialOffsetLocalMeters'], dtype=float)
            reference = float(episode['referenceLengthMeters'])
            if (local.shape != (3,) or not np.isfinite(local).all()
                    or not np.isfinite(reference) or reference <= 0.):
                raise ValueError(f'{side} native material episode offset is invalid')
            if (key_clock and key_geometry is not None
                    and str(episode['mode']) in ('verticalOnly', 'stationary')):
                material = _native_material_point(
                    values[query_index, ankle_i], values[query_index, foot_i],
                    key_axes[query_index], episode,
                    key_geometry['sides'][side], key_scale)
            elif playback_axes is not None:
                material = _native_pose_material_point(
                    values[query_index, ankle_i], values[query_index, foot_i],
                    playback_axes[query_index], episode, bone_length)
            else:
                forward = direction[query_index]
                lateral = axes[query_index]
                up = np.cross(lateral, forward)
                material_offset = ((forward * local[0] + lateral * local[1]
                                    + up * local[2]) * (bone_length / reference))
                material = values[query_index, ankle_i] + material_offset
            if str(episode['mode']) == 'verticalOnly':
                normal = np.asarray(episode['surfaceNormal'], dtype=float)
                plane = float(episode['planeOffsetMeters'])
                target = material + (plane - float(np.dot(normal, material))) * normal
            else:
                target = np.asarray(episode['targetWorld'], dtype=float)
            correction = weight[query_index] * (material - target)
            residual[query_index] = correction
            side_maximum = max(side_maximum, float(np.linalg.norm(correction)))
            side_count += 1
            kind = (('keyframe' if key_clock else 'playback')
                    + ('Height' if str(episode['mode']) == 'verticalOnly'
                       else 'Stationary'))
            side_totals[kind]['sampleCount'] += 1
            side_totals[kind]['maximumErrorMeters'] = max(
                side_totals[kind]['maximumErrorMeters'],
                float(np.linalg.norm(correction)))
        columns.append(residual)
        metrics['bySide'][side] = {
            'sampleCount': int(side_count),
            'maximumErrorMeters': float(side_maximum),
            **{f'{key}SampleCount': int(totals['sampleCount'])
               for key, totals in side_totals.items()},
            **{f'{key}MaximumErrorMeters': float(totals['maximumErrorMeters'])
               for key, totals in side_totals.items()},
        }
        for key, totals in side_totals.items():
            clock_mode_totals[key]['sampleCount'] += int(totals['sampleCount'])
            clock_mode_totals[key]['maximumErrorMeters'] = max(
                clock_mode_totals[key]['maximumErrorMeters'],
                float(totals['maximumErrorMeters']))
        sample_count += side_count
        maximum = max(maximum, side_maximum)
    if not columns:
        return (empty, metrics) if return_metrics else empty
    residuals = np.concatenate(columns, axis=1)
    metrics.update(available=True, sampleCount=int(sample_count),
                   maximumErrorMeters=float(maximum),
                   **{f'{key}SampleCount': int(totals['sampleCount'])
                      for key, totals in clock_mode_totals.items()},
                   **{f'{key}MaximumErrorMeters': float(totals['maximumErrorMeters'])
                      for key, totals in clock_mode_totals.items()})
    return (residuals, metrics) if return_metrics else residuals


def native_material_key_sample_requirements(tracks):
    """Exact keyframe counts by native material authority mode.

    Every active integer key is a stored keyframe that playback preserves, so
    its material anchor must be measured explicitly. Returns the required
    stationary-XYZ and height-only-plane key sample counts for the calibrated
    actual-shoe half of the native material contract.
    """
    required = {'keyframeStationarySampleCount': 0, 'keyframeHeightSampleCount': 0}
    if not isinstance(tracks, dict) or tracks.get('version') != 2:
        return required
    for side in ('left', 'right'):
        track = tracks.get(side)
        if not isinstance(track, dict):
            continue
        try:
            active, _, _, _ = _validated_native_side_track(
                track, len(track.get('active', ())), side)
        except (KeyError, TypeError, ValueError, IndexError):
            continue
        episode_by_frame = _native_episode_by_frame(track)
        for frame in np.flatnonzero(active):
            episode = episode_by_frame.get(int(frame))
            if episode is None:
                continue
            mode = str(episode.get('mode'))
            if mode == 'stationary':
                required['keyframeStationarySampleCount'] += 1
            elif mode == 'verticalOnly':
                required['keyframeHeightSampleCount'] += 1
    return required


def _sample_track_directions(directions, first, last, alpha, *, wrap, smooth_limiter):
    raw_yaw = np.arctan2(directions[:, 0], directions[:, 2])
    if wrap:
        count = len(raw_yaw)
        yaw = np.unwrap(np.tile(raw_yaw, 3))[:, None]
        yaw_first, yaw_last = first + count, last + count
        yaw_last += (last <= first) * count
    else:
        yaw = np.unwrap(raw_yaw)[:, None]
        yaw_first, yaw_last = first, last
    pitch = np.arctan2(directions[:, 1],
                       np.linalg.norm(directions[:, [0, 2]], axis=1))[:, None]
    sampled_yaw = hermite_samples(
        yaw, yaw_first, yaw_last, alpha, wrap=False,
        smooth_limiter=smooth_limiter)[:, 0]
    sampled_pitch = hermite_samples(
        pitch, first, last, alpha, wrap=wrap,
        smooth_limiter=smooth_limiter)[:, 0]
    return np.column_stack((np.cos(sampled_pitch) * np.sin(sampled_yaw),
                            np.sin(sampled_pitch),
                            np.cos(sampled_pitch) * np.cos(sampled_yaw)))
