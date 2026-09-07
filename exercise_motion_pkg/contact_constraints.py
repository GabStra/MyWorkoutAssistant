"""Shared semantics for source-confirmed stationary surface contacts."""

from __future__ import annotations

from typing import Any

import numpy as np


def is_stationary_contact(contact: dict[str, Any]) -> bool:
    """Surface proximity alone does not authorize a tangential lock."""
    motion = str(contact.get("contactMotion") or "").casefold()
    if motion in {"sliding", "rolling", "moving", "unknown"}:
        return False
    if contact.get("allowSliding") is True:
        return False
    if contact.get("verticalOnly") is True:
        return motion == "stationary"
    return True


def contact_frame_bounds(contact: dict[str, Any], count: int) -> tuple[int, int]:
    start = (
        round(float(contact["startRatio"]) * (count - 1))
        if contact.get("startRatio") is not None else int(contact.get("startFrame", 0))
    )
    end = (
        round(float(contact["endRatio"]) * (count - 1))
        if contact.get("endRatio") is not None else int(contact.get("endFrame", count - 1))
    )
    return max(0, min(count - 1, start)), max(0, min(count - 1, end))


def stationary_target_track(
    points: np.ndarray, mask: np.ndarray,
) -> tuple[np.ndarray, list[dict[str, Any]]]:
    """One immutable anchor per connected stance, never across a release.

    Use a robust stance center to minimize the reach correction. Contact
    positions are hard constraints; any filtering belongs to the free spans.
    """
    targets = points.copy()
    episodes = []
    edges = np.diff(np.r_[False, mask, False].astype(int))
    for start, stop in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)):
        anchor = np.median(points[start:stop], axis=0)
        targets[start:stop] = anchor
        episodes.append({
            "startFrame": int(start), "endFrame": int(stop - 1),
            "anchor": anchor.tolist(),
            "baselineMaxDistanceFromAnchor": float(np.max(
                np.linalg.norm(points[start:stop] - anchor, axis=1)
            )),
        })
    return targets, episodes


def reachable_root_track(
    count: int, fps: float, constraints: list[tuple[np.ndarray, np.ndarray, float]],
) -> np.ndarray:
    """Fit one smooth body translation inside all active chain reach balls.

    Entries contain frame indexes, target-minus-root offsets, and rigid reach.
    This changes neither body proportions nor contact anchors.
    """
    from scipy.linalg import cho_factor, cho_solve

    correction = np.zeros((count, 3))
    if not constraints:
        return correction
    indexes = np.concatenate([item[0] for item in constraints])
    offsets = np.concatenate([item[1] for item in constraints])
    radii = np.concatenate([np.full(len(item[0]), item[2]) for item in constraints])
    if np.all(np.linalg.norm(offsets, axis=1) <= radii):
        return correction
    second_difference = np.diff(np.eye(count), n=2, axis=0)
    system = np.eye(count) + (max(fps, 1.0) * 0.10)**4 * second_difference.T @ second_difference

    # Split smooth trajectory fitting from convex reach-ball projections.
    # The factorization is reused; no per-frame nonlinear optimization.
    penalty = 10.0
    factor = cho_factor(2 * system + penalty * np.diag(np.bincount(indexes, minlength=count)))
    projected = offsets.copy()
    dual = np.zeros_like(projected)
    for _ in range(4000):
        rhs = np.zeros_like(correction)
        np.add.at(rhs, indexes, penalty * (projected - dual))
        correction = cho_solve(factor, rhs)
        previous = projected.copy()
        relative = correction[indexes] + dual - offsets
        projected = offsets + relative * np.minimum(
            1, radii / np.maximum(np.linalg.norm(relative, axis=1), 1e-10)
        )[:, None]
        residual = correction[indexes] - projected
        dual += residual
        if np.max(np.abs(residual)) < 1e-7 and np.max(np.abs(projected - previous)) < 1e-7:
            break
    maximum_excess = float(np.max(np.linalg.norm(correction[indexes] - offsets, axis=1) - radii))
    if maximum_excess > 1e-6:
        raise ValueError(f"No reachable support trajectory; reach excess {maximum_excess:.6g}")
    return correction
