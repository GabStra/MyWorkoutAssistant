"""Shared semantics for source-confirmed stationary surface contacts."""

from __future__ import annotations

from typing import Any

import numpy as np

# Contact IK accepts angular residuals at this numerical precision (radians).
# Envelope validation must use the same precision after converting to degrees;
# this is solver roundoff tolerance, separate from source/anatomical allowances.
ANGLE_NUMERICAL_TOLERANCE_RADIANS = 1e-6


def motion_support_contacts(evidence: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Normalize modern and legacy support evidence without inventing contacts."""
    evidence = evidence or {}
    contacts = list(evidence.get("contacts") or []) + list(evidence.get("supportContacts") or [])
    for side, record in (evidence.get("feet") or {}).items():
        if isinstance(record, dict) and record.get("continuousSupport"):
            contacts.append({**record, "jointName": record.get("jointName", f"{side}_ankle"),
                             "startRatio": 0.0, "endRatio": 1.0})
    return [contact for contact in contacts if isinstance(contact, dict)]


def is_stationary_contact(contact: dict[str, Any]) -> bool:
    """Surface proximity alone does not authorize a tangential lock."""
    if contact.get("surfaceKind") == "contract_inferred_support_surface":
        # A generated posture plus a slow image-space joint is not observed
        # physical contact. Treat it as advisory, including cached evidence.
        return False
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
    points: np.ndarray, mask: np.ndarray, *, fps: float | None = None, anchor_ids=None,
) -> tuple[np.ndarray, list[dict[str, Any]]]:
    """One immutable anchor per connected stance, never across a release.

    With timing available, fit anchors together with free spans so independent
    stance medians cannot compress reconstruction drift into a short release.
    Each stance still has exactly one anchor; releases remain unconstrained.
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
    if fps is not None and len(points) >= 3 and episodes:
        from scipy.sparse import csr_matrix, diags, eye
        from scipy.sparse.linalg import spsolve

        groups = np.arange(len(points))
        observed_groups = {}
        for episode in episodes:
            start, stop = episode["startFrame"], episode["endFrame"] + 1
            anchor_id = anchor_ids[start] if anchor_ids is not None else None
            owner = observed_groups.setdefault(anchor_id, start) if anchor_id is not None else start
            groups[start:stop] = owner
        _, columns = np.unique(groups, return_inverse=True)
        mapping = csr_matrix((np.ones(len(points)), (np.arange(len(points)), columns)),
                             shape=(len(points), int(columns.max()) + 1))
        difference = diags([np.ones(len(points) - 2), -2 * np.ones(len(points) - 2),
                            np.ones(len(points) - 2)], [0, 1, 2], shape=(len(points) - 2, len(points)))
        system = eye(len(points)) + (max(fps, 1.) * .15)**4 * difference.T @ difference
        # Robust episode centers supply the data term. Equal columns impose
        # stationary contact exactly rather than smoothing a planted foot.
        anchors = spsolve((mapping.T @ system @ mapping).tocsc(), mapping.T @ targets)
        targets = np.asarray(mapping @ anchors)
        for episode in episodes:
            start, stop = episode["startFrame"], episode["endFrame"] + 1
            anchor = targets[start]
            episode["anchor"] = anchor.tolist()
            episode["baselineMaxDistanceFromAnchor"] = float(np.max(
                np.linalg.norm(points[start:stop] - anchor, axis=1)))
    return targets, episodes


class InfeasibleContactCorrection(ValueError):
    """A contact proposal cannot satisfy its geometric constraints."""


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
    constraint_counts = np.diag(np.bincount(indexes, minlength=count))
    for iteration in range(4000):
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
        # A fixed penalty can stall close to a contact boundary and exhaust
        # the budget on a feasible trajectory. Balance primal feasibility
        # against dual convergence; rescale the scaled dual when rho changes.
        if (iteration + 1) % 50 == 0:
            primal_norm = float(np.linalg.norm(residual))
            dual_norm = penalty * float(np.linalg.norm(projected - previous))
            new_penalty = penalty
            if primal_norm > 10 * dual_norm:
                new_penalty = min(penalty * 2, 1e6)
            elif dual_norm > 10 * primal_norm:
                new_penalty = max(penalty / 2, 1e-4)
            if new_penalty != penalty:
                dual *= penalty / new_penalty
                penalty = new_penalty
                factor = cho_factor(2 * system + penalty * constraint_counts)
    maximum_excess = float(np.max(np.linalg.norm(correction[indexes] - offsets, axis=1) - radii))
    if maximum_excess > 1e-6:
        raise InfeasibleContactCorrection(f"Support trajectory solver did not reach feasibility; reach excess {maximum_excess:.6g}")
    return correction
