"""Kinematics and coordinate Jacobians for points fixed to a rigid body frame."""

from __future__ import annotations

import operator

import numpy as np
from scipy.sparse import coo_matrix, diags


def rigid_material_point_kinematics(
        rig, coordinates, origin_joint, rotation_joint, local_vectors,
        active_mask=None, *, project_socket=True):
    """Return attached world points and their sparse Jacobian with respect to rig q.

    Each frame's ``local_vectors[f]`` is fixed in ``rotation_joint``'s local
    coordinates. Inactive frames retain their point value but have zero Jacobian
    rows, so callers can preserve the full frame indexing of their constraints.
    """
    values = np.asarray(coordinates, dtype=float)
    if values.ndim == 1:
        if values.size % int(rig.width):
            raise ValueError('flat coordinates must be divisible by rig.width')
        values = values.reshape(-1, int(rig.width))
    if values.ndim != 2 or values.shape[1] != int(rig.width) or not np.isfinite(values).all():
        raise ValueError('coordinates must be a finite [frames, rig.width] array')

    frame_count = len(values)
    joint_count = len(rig.names)

    def joint_index(value, label):
        if isinstance(value, (bool, np.bool_)):
            raise ValueError(f'{label} must be a joint index')
        try:
            index = operator.index(value)
        except TypeError as exc:
            raise ValueError(f'{label} must be a joint index') from exc
        if index < 0 or index >= joint_count:
            raise ValueError(f'{label} is outside rig joint range')
        return index

    origin_index = joint_index(origin_joint, 'origin_joint')
    rotation_index = joint_index(rotation_joint, 'rotation_joint')
    local = np.asarray(local_vectors, dtype=float)
    if local.shape != (frame_count, 3) or not np.isfinite(local).all():
        raise ValueError('local_vectors must be finite [frames, 3] values')
    if active_mask is None:
        active = np.ones(frame_count, dtype=bool)
    else:
        active = np.asarray(active_mask, dtype=bool)
        if active.shape != (frame_count,):
            raise ValueError('active_mask must have one value per frame')

    points = rig.decode(values, project_socket=project_socket)[:, origin_index].copy()
    world = rig.global_rotations(values, project_socket=project_socket)[rotation_index]
    points += np.einsum('fij,fj->fi', world, local)

    # FK provides the origin derivative, including socket projection coupling.
    fk = rig.fk_jacobian(values, project_socket=project_socket)
    origin_rows = (
        np.arange(frame_count)[:, None] * joint_count * 3
        + origin_index * 3 + np.arange(3)[None, :]
    ).ravel()
    origin_jacobian = fk[origin_rows].tocsr()

    # The material offset follows every rig rotation through the same projected
    # world matrices as decode. Batch each coordinate probe over independent frames.
    rotation_rows, rotation_columns, rotation_data = [], [], []
    difference_scale = np.cbrt(np.finfo(float).eps)
    width = int(rig.width)
    for column in range(3, width):
        step = difference_scale * np.maximum(1., np.abs(values[:, column]))
        plus = values.copy()
        minus = values.copy()
        plus[:, column] += step
        minus[:, column] -= step
        plus_world = rig.global_rotations(plus, project_socket=project_socket)[rotation_index]
        minus_world = rig.global_rotations(minus, project_socket=project_socket)[rotation_index]
        plus_offset = np.einsum('fij,fj->fi', plus_world, local)
        minus_offset = np.einsum('fij,fj->fi', minus_world, local)
        derivative = (plus_offset - minus_offset) / (2. * step[:, None])
        frame_indices = np.flatnonzero(active)
        if not frame_indices.size:
            continue
        rotation_rows.append((frame_indices[:, None] * 3 + np.arange(3)[None, :]).ravel())
        rotation_columns.append((frame_indices * width + column).repeat(3))
        rotation_data.append(derivative[frame_indices].ravel())

    shape = (frame_count * 3, frame_count * width)
    if rotation_data:
        rotation_jacobian = coo_matrix(
            (np.concatenate(rotation_data),
             (np.concatenate(rotation_rows), np.concatenate(rotation_columns))),
            shape=shape,
        ).tocsr()
    else:
        rotation_jacobian = coo_matrix(shape).tocsr()

    row_mask = np.repeat(active.astype(float), 3)
    jacobian = diags(row_mask, format='csr') @ (origin_jacobian + rotation_jacobian)
    return points, jacobian.tocsr()
