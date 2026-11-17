"""Projected native heel-to-toe marker residual, independent of contact claims."""
from __future__ import annotations

import numpy as np

from .native_foot_geometry import _normalized_side, native_foot_marker_world


def _finite_rows(value, width, name):
    try:
        rows = np.asarray(value, dtype=float)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be a finite (N, {width}) array") from exc
    if rows.ndim != 2 or rows.shape[1] != width or not np.isfinite(rows).all():
        raise ValueError(f"{name} must be a finite (N, {width}) array")
    return rows


def _finite_array(value, shape, name):
    try:
        array = np.asarray(value, dtype=float)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be a finite {shape} array") from exc
    if array.shape != shape or not np.isfinite(array).all():
        raise ValueError(f"{name} must be a finite {shape} array")
    return array


def native_heel_toe_image_residual(ankles, balls, side_axes, native_geometry,
                                   projection, observed_vectors):
    """Compare projected native heel-to-toe markers with observed image vectors.

    The caller supplies the current FK side axes, so axial foot rotation stays
    observable even when the ankle and ball joint positions are unchanged.
    ``projection`` is the image projection without offset; any offset or camera
    translation cancels because only the heel-minus-toe difference is used.
    ``observed_vectors`` are already height-normalized square-pixel coordinates.
    """
    ankles = _finite_rows(ankles, 3, "ankles")
    balls = _finite_rows(balls, 3, "balls")
    side_axes = _finite_rows(side_axes, 3, "side_axes")
    if not (len(ankles) == len(balls) == len(side_axes)):
        raise ValueError("ankles, balls and side_axes must share a frame count")
    projection = _finite_array(projection, (2, 3), "projection")
    observed_vectors = _finite_rows(observed_vectors, 2, "observed_vectors")
    if len(observed_vectors) != len(ankles):
        raise ValueError("observed_vectors must match the frame count")
    side_geometry = _normalized_side(native_geometry)
    if side_geometry is None:
        raise ValueError("native foot geometry side is invalid")
    heel, toe = native_foot_marker_world(
        ankles, balls, side_axes, side_geometry)
    return (heel - toe) @ projection.T - observed_vectors


__all__ = ["native_heel_toe_image_residual"]
