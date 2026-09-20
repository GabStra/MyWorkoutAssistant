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


def is_observed_ground_contact(contact, evidence):
    """Use explicit surface identity before the legacy shared-ground evidence."""
    surface = str(contact.get('surfaceKind') or '').lower()
    if surface:
        return surface in {'ground', 'floor', 'ground_plane'}
    return (contact.get('supportKind') == 'observed_foot_patch'
            and (evidence or {}).get('sharedSupportPlaneY') is not None)


def observed_ground_contact_mask(evidence, names, count):
    """Only observed stationary toe/sole contacts own a floor-height anchor."""
    result = np.zeros((count, len(names)), dtype=bool)
    support = (evidence or {}).get('bodySupport') or {}
    calibrated = set(support.get('stationaryJoints', [])) if (
        support.get('required') and support.get('status') == 'confirmed') else set()
    for contact in motion_support_contacts(evidence):
        name = str(contact.get('jointName') or '')
        if (name not in names or name in calibrated or not name.endswith('_foot')
                or contact.get('contactState') == 'heel_only'
                or not is_stationary_contact(contact)
                or not is_observed_ground_contact(contact, evidence)):
            continue
        start, end = contact_frame_bounds(contact, count)
        result[start:end+1, names.index(name)] = True
    return result


def stationary_contact_anchor_ids(evidence, names, count):
    """Transport observed anchor identity without adding contact frames."""
    result = np.full((count, len(names)), None, dtype=object)
    for contact in motion_support_contacts(evidence):
        if not is_stationary_contact(contact):
            continue
        name = contact.get('jointName', '')
        identities = {name: contact.get('anchorGroupId')}
        if contact.get('contactState') == 'full_sole' and name.endswith('_foot'):
            identities[name.replace('_foot', '_ankle')] = contact.get('ankleAnchorGroupId')
        start, end = contact_frame_bounds(contact, count)
        for joint, group in identities.items():
            if joint in names and group is not None:
                result[start:end+1, names.index(joint)] = str(group)
    return result


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
    if fps is None and anchor_ids is not None:
        for group in {value for value in anchor_ids[mask] if value is not None}:
            shared = mask & (anchor_ids == group)
            targets[shared] = np.median(points[shared], axis=0)
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


def calibrate_shared_contact_pair(points, mask, anchor_ids, *, distance, ground_mask, floor):
    """Calibrate linked stationary anchors without splitting their identities.

    Each node is one observed anchor, each edge one fixed-length foot. The small
    static solve changes anchor positions, never contact intervals or releases.
    Calibration is bounded to ten percent of the segment length; larger source
    disagreements need new evidence rather than a substantially rewritten stance.
    """
    from scipy.optimize import minimize

    groups = np.full(mask.shape, -1, dtype=int)
    members = []
    for joint in range(2):
        identities = {}
        episode = -1
        for frame in range(len(points)):
            if not mask[frame, joint]:
                continue
            if frame == 0 or not mask[frame - 1, joint]:
                episode += 1
            identity = anchor_ids[frame, joint]
            key = ('observed', identity) if identity is not None else ('episode', episode)
            if key not in identities:
                identities[key] = len(members)
                members.append((joint, []))
            group = identities[key]
            groups[frame, joint] = group
            members[group][1].append(frame)
    reference = np.asarray([np.mean(points[frames, joint], axis=0) for joint, frames in members])
    weights = np.asarray([len(frames) for _, frames in members], dtype=float)
    weights /= weights.max()
    edges = np.unique(groups[np.all(mask, axis=1)], axis=0)
    first, last = edges.T
    length_squared = float(distance)**2
    allowance = .1 * float(distance)
    bounds = [(value - allowance, value + allowance) for value in reference.ravel()]
    for group, (joint, frames) in enumerate(members):
        if floor is not None and np.any(ground_mask[frames, joint]):
            bounds[group * 3 + 1] = (float(floor), float(floor))

    def objective(values):
        delta = values.reshape(-1, 3) - reference
        return .5 * np.sum(weights[:, None] * delta**2) / length_squared

    def gradient(values):
        return (weights[:, None] * (values.reshape(-1, 3) - reference) / length_squared).ravel()

    def lengths(values):
        values = values.reshape(-1, 3)
        return np.sum((values[first] - values[last])**2, axis=1) / length_squared - 1.

    def length_jacobian(values):
        values = values.reshape(-1, 3)
        delta = 2. * (values[first] - values[last]) / length_squared
        jacobian = np.zeros((len(edges), len(reference), 3))
        jacobian[np.arange(len(edges)), first] = delta
        jacobian[np.arange(len(edges)), last] = -delta
        return jacobian.reshape(len(edges), -1)

    def correction_limits(values):
        return 1. - np.sum((values.reshape(-1, 3) - reference)**2, axis=1) / allowance**2

    def correction_jacobian(values):
        jacobian = np.zeros((len(reference), len(reference), 3))
        indexes = np.arange(len(reference))
        jacobian[indexes, indexes] = -2. * (values.reshape(-1, 3) - reference) / allowance**2
        return jacobian.reshape(len(reference), -1)

    solved = minimize(objective, reference.ravel(), jac=gradient, method='SLSQP', bounds=bounds,
                      constraints=[{'type': 'eq', 'fun': lengths, 'jac': length_jacobian},
                                   {'type': 'ineq', 'fun': correction_limits, 'jac': correction_jacobian}],
                      options={'maxiter': 100, 'ftol': 1e-12})
    calibrated = solved.x.reshape(-1, 3)
    errors = np.abs(np.linalg.norm(calibrated[first] - calibrated[last], axis=1) - distance)
    if (not solved.success or not np.isfinite(calibrated).all() or np.max(errors) > 1e-7
            or np.max(np.linalg.norm(calibrated - reference, axis=1)) > allowance + 1e-7):
        raise InfeasibleContactCorrection('Stationary anchors cannot share rigid lengths within the calibration allowance')
    result = points.copy()
    for group, (joint, frames) in enumerate(members):
        result[frames, joint] = calibrated[group]
    return result


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
