"""Infer a scene ground offset from registered 3D ground-contact tracks.

The estimate is a scene gauge for placement, not a measured bare-floor or
padding height. Callers supply the registered up axis and the already verified
ground-contact material anchors; this module does not infer contact identity.
"""
from __future__ import annotations

import numpy as np

PROVENANCE = 'inferred_ground_contact_material_scene_gauge'
_AUTHORITY = 'inferred_scene_placement'


def _unit(vector, label):
    value = np.asarray(vector, dtype=float)
    if value.shape != (3,) or not np.isfinite(value).all():
        raise ValueError(f'{label} must be a finite 3D vector')
    length = float(np.linalg.norm(value))
    if length <= 1e-9:
        raise ValueError(f'{label} must be non-zero')
    return value / length


def _unresolved(reason, surface_kind):
    return {'resolved': False, 'reason': reason, 'surfaceKind': surface_kind,
            'authority': _AUTHORITY, 'provenance': PROVENANCE,
            'observedFloorHeight': False}


def infer_ground_contact_plane(points, *, up, contact_masks=None,
                               surface_kind='ground', minimum_points=1):
    """Return a finite plane offset from caller-verified ground contacts.

    ``points`` are registered 3D material contact anchors, shaped
    ``(..., 3)``. ``contact_masks`` selects the verified ground-contact
    frames/channels and broadcasts to the anchor axes. A non-ground surface
    category is rejected instead of silently becoming a horizontal scene floor.
    """
    category = str(surface_kind or '').casefold()
    if category != 'ground':
        return _unresolved('ground_contact_surface_is_not_ground', category)
    try:
        normal = _unit(up, 'up')
        raw = np.asarray(points, dtype=float)
    except (TypeError, ValueError):
        return _unresolved('ground_contact_up_or_points_invalid', category)
    if raw.ndim < 2 or raw.shape[-1] != 3 or raw.size == 0:
        return _unresolved('ground_contact_points_malformed', category)
    valid = np.isfinite(raw).all(axis=-1)
    if contact_masks is not None:
        try:
            mask = np.broadcast_to(np.asarray(contact_masks, dtype=bool),
                                   raw.shape[:-1])
        except (TypeError, ValueError):
            return _unresolved('ground_contact_masks_malformed', category)
        valid &= mask
    selected = raw[valid].reshape(-1, 3)
    if len(selected) < max(1, int(minimum_points)):
        return _unresolved('no_valid_ground_contact_rows', category)
    heights = selected @ normal
    return {
        'resolved': True,
        'normal': normal.tolist(),
        'offsetMeters': float(np.median(heights)),
        'pointCount': int(len(selected)),
        'spreadMeters': float(np.max(heights) - np.min(heights)),
        'surfaceKind': category,
        'authority': _AUTHORITY,
        'provenance': PROVENANCE,
        'observedFloorHeight': False,
    }
