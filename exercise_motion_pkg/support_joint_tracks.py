"""Code-derived frame ownership for validated stationary body support."""

from __future__ import annotations

import numpy as np


VERSION = 1
SOURCE = 'validated_stationary_body_support'


def build_support_joint_tracks(evidence, names, count):
    """Materialize stationary support ownership without creating world anchors."""
    if not isinstance(evidence, dict) or count <= 0:
        return None
    from .support_geometry import support_contact_masks
    from .contact_constraints import stationary_contact_anchor_ids

    active, _ = support_contact_masks(evidence, names, count)
    native_tracks = evidence.get('_nativeFootMaterialTracks')
    if isinstance(native_tracks, dict) and native_tracks.get('version') == 2:
        from .contact_interpolation import suppress_native_foot_pins
        active = suppress_native_foot_pins(
            active, names, native_tracks, support_evidence=evidence)
    anchor_ids = stationary_contact_anchor_ids(evidence, names, count)
    tracks = {}
    stationary = set(evidence.get('stationaryJoints') or ())
    status_confirmed = evidence.get('status') == 'confirmed'
    for index, name in enumerate(names):
        frame_ids = [None] * count
        run_id = None
        was_active = False
        run_number = 0
        for frame in range(count):
            if not active[frame, index]:
                was_active = False
                run_id = None
                continue
            existing = anchor_ids[frame, index]
            if isinstance(existing, str) and existing:
                frame_ids[frame] = existing
                was_active = True
                run_id = existing
                continue
            if name not in stationary or not status_confirmed:
                was_active = False
                run_id = None
                continue
            if not was_active:
                run_number += 1
                run_id = f'derived:stationary:{name}:{run_number}'
            frame_ids[frame] = run_id
            was_active = True
        if any(value is not None for value in frame_ids):
            tracks[name] = {'episodeIds': frame_ids}
    if not tracks:
        return None
    return {'version': VERSION, 'source': SOURCE, 'joints': tracks}


def validate_support_joint_tracks(value, names, count):
    """Strictly validate the optional derived mask transported on fixedRig."""
    if (not isinstance(value, dict) or type(value.get('version')) is not int
            or value.get('version') != VERSION or value.get('source') != SOURCE
            or set(value) != {'version', 'source', 'joints'}
            or not isinstance(value.get('joints'), dict)):
        raise ValueError('supportJointTracks is malformed or unsupported')
    joints = {}
    for name, track in value['joints'].items():
        if (name not in names or not isinstance(track, dict)
                or set(track) != {'episodeIds'}
                or not isinstance(track.get('episodeIds'), list)
                or len(track['episodeIds']) != count):
            raise ValueError('supportJointTracks joint episode mapping is malformed')
        ids = []
        for episode_id in track['episodeIds']:
            if episode_id is not None and (not isinstance(episode_id, str) or not episode_id):
                raise ValueError('supportJointTracks episode ids must be nonempty strings or null')
            ids.append(episode_id)
        joints[name] = {'episodeIds': ids}
    return {'version': VERSION, 'source': SOURCE, 'joints': joints}


def sample_support_joint_mask(tracks, joint, cursors, count, *, wrap=False):
    """Sample active support only at exact keys or within one stable episode."""
    cursors = np.asarray(cursors, dtype=float).reshape(-1)
    if not np.isfinite(cursors).all() or count <= 0:
        raise ValueError('support joint sampling requires finite cursors and frame count')
    track = tracks['joints'].get(joint)
    if track is None:
        return np.zeros(len(cursors), dtype=bool)
    ids = track['episodeIds']
    normalized = np.mod(cursors, count) if wrap else np.clip(cursors, 0., count - 1.)
    nearest = np.rint(normalized)
    exact = np.isclose(normalized, nearest, atol=1e-12, rtol=0.)
    output = np.zeros(len(cursors), dtype=bool)
    for row, position in enumerate(normalized):
        if exact[row]:
            key = int(nearest[row]) % count if wrap else min(int(nearest[row]), count - 1)
            output[row] = isinstance(ids[key], str) and bool(ids[key])
            continue
        first = int(np.floor(position))
        last = (first + 1) % count if wrap else min(first + 1, count - 1)
        output[row] = bool(ids[first]) and ids[first] == ids[last]
    return output
