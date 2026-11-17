"""Compact root-relative positional-range objective."""

import numpy as np
from scipy.sparse import coo_matrix


def positional_spans(points, root):
    relative = points - points[:, root:root + 1]
    return np.linalg.norm(np.ptp(relative, axis=0), axis=-1)


def residual(candidate, target, root, scale):
    target_span = positional_spans(target, root)
    result_span = positional_spans(candidate, root)
    shortfall = np.maximum(0., .92 * target_span - result_span)
    return np.where(target_span > .1 * scale, 12000. / scale * shortfall, 0.)


def jacobian(candidate, target, root, scale):
    frame_count, joint_count, _ = candidate.shape
    target_span = positional_spans(target, root)
    result_span = positional_spans(candidate, root)
    active = np.flatnonzero(
        (target_span > .1 * scale) & (.92 * target_span > result_span)
        & (result_span > 0.))
    rows, columns, values = [], [], []
    axes = np.arange(3)
    weight = 12000. / scale
    stride = joint_count * 3
    for joint in active:
        relative = candidate[:, joint] - candidate[:, root]
        lower = np.argmin(relative, axis=0)
        upper = np.argmax(relative, axis=0)
        delta = relative[upper, axes] - relative[lower, axes]
        nonzero = delta > 0.
        lower, upper, axes_nz = lower[nonzero], upper[nonzero], axes[nonzero]
        coefficient = -weight * delta[nonzero] / result_span[joint]
        columns.append(np.stack((
            upper * stride + joint * 3 + axes_nz,
            upper * stride + root * 3 + axes_nz,
            lower * stride + joint * 3 + axes_nz,
            lower * stride + root * 3 + axes_nz,
        ), axis=1).reshape(-1))
        values.append(np.stack((
            coefficient, -coefficient, -coefficient, coefficient,
        ), axis=1).reshape(-1))
        rows.append(np.full(coefficient.size * 4, joint))
    matrix = coo_matrix(
        (np.concatenate(values) if values else np.empty(0),
         (np.concatenate(rows) if rows else np.empty(0, dtype=int),
          np.concatenate(columns) if columns else np.empty(0, dtype=int))),
        shape=(joint_count, frame_count * stride))
    matrix.sum_duplicates()
    matrix.eliminate_zeros()
    return matrix.tocsr()
