"""Frame-correct temporal smoothing for articulated rig rotations."""

from __future__ import annotations

import numpy as np
from scipy.ndimage import gaussian_filter1d
from scipy.spatial.transform import Rotation


def _nearest_rotation(matrix: np.ndarray, fallback: np.ndarray) -> np.ndarray:
    """Project a weighted matrix mean onto SO(3), with safe degeneracy fallback."""
    if not np.isfinite(matrix).all():
        return fallback
    try:
        u, singular, vt = np.linalg.svd(matrix)
    except np.linalg.LinAlgError:
        return fallback
    if singular[0] <= 1e-12:
        return fallback
    rank_tolerance = 32. * np.finfo(float).eps * singular[0]
    if singular[1] <= rank_tolerance:
        # Rank-one means determine an axis but not the rotation around it.
        return fallback
    determinant = float(np.linalg.det(u @ vt))
    # A reflected mean with an ambiguous least singular direction has no stable
    # nearest proper rotation. Keep the observed orientation in that case.
    if determinant < 0. and singular[-2] - singular[-1] <= rank_tolerance:
        return fallback
    correction = np.eye(3)
    correction[-1, -1] = 1. if determinant >= 0. else -1.
    result = u @ correction @ vt
    return result if np.isfinite(result).all() else fallback


def temporal_world_rotation_smooth(coordinates, rig, pinned, *, cyclic, sigma=1.0):
    """Smooth free world orientations and rebase them through the updated rig.

    Root translation and every contact-owned local rotation remain unchanged.
    Free joints are filtered in world space, then converted back to local
    rotations in rig order so parent motion is not independently double-counted.
    """
    values = np.asarray(coordinates, dtype=float)
    if values.ndim != 2 or values.shape[1] != rig.width or len(values) < 2:
        return values.copy()
    if not np.isfinite(values).all():
        return values.copy()
    sigma = float(sigma)
    if not np.isfinite(sigma) or sigma <= 0.:
        return values.copy()

    result = values.copy()
    mode = 'wrap' if cyclic else 'nearest'
    locked = np.zeros((len(values), len(rig.names)), dtype=bool)
    if pinned is not None:
        pins = np.asarray(pinned, dtype=bool)
        if pins.shape != locked.shape:
            raise ValueError('pinned mask must match frame and rig joint dimensions')
        for joint in range(len(rig.names)):
            ancestor = joint
            while ancestor >= 0:
                locked[:, ancestor] |= pins[:, joint]
                ancestor = rig.parents[ancestor]

    original_world = rig.global_rotations(values, project_socket=False)
    desired_world = {}
    # Filtering each matrix component preserves the SO(3) representation across
    # rotvec branch cuts; SVD supplies the closest proper rotation afterward.
    for joint in rig.order:
        source = original_world[joint]
        if joint not in rig.slots:
            desired_world[joint] = source
            continue
        free = ~locked[:, joint]
        filtered = gaussian_filter1d(source, sigma, axis=0, mode=mode)
        target = source.copy()
        for frame in np.flatnonzero(free):
            target[frame] = _nearest_rotation(filtered[frame], source[frame])
        desired_world[joint] = target

    output_world = {}
    for joint in rig.order:
        parent = rig.parents[joint]
        if parent < 0:
            if joint in rig.slots:
                free = ~locked[:, joint]
                result[free, rig.slots[joint]:rig.slots[joint] + 3] = Rotation.from_matrix(
                    desired_world[joint][free]).as_rotvec()
                local = Rotation.from_rotvec(
                    result[:, rig.slots[joint]:rig.slots[joint] + 3]).as_matrix()
            else:
                local = np.broadcast_to(np.eye(3), (len(values), 3, 3))
            output_world[joint] = local
            continue

        if joint not in rig.slots:
            local = np.broadcast_to(np.eye(3), (len(values), 3, 3))
        else:
            local = Rotation.from_rotvec(
                values[:, rig.slots[joint]:rig.slots[joint] + 3]).as_matrix().copy()
            free = ~locked[:, joint]
            if np.any(free):
                local[free] = np.einsum(
                    'fji,fjk->fik', output_world[parent][free], desired_world[joint][free])
                result[free, rig.slots[joint]:rig.slots[joint] + 3] = Rotation.from_matrix(
                    local[free]).as_rotvec()
        output_world[joint] = output_world[parent] @ local
    return result
