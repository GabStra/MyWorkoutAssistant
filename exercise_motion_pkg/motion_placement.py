"""Separate observed articulation from contact-constrained world placement."""
from __future__ import annotations

import numpy as np


def register_contact_placement(points, pinned, root_index, fps, root_reference):
    """Register stance anchors together, before freezing them for kinematic fit.

    Unknowns are one translation per frame and one point per observed stance.
    Source-relative limb positions are unchanged. Temporal terms follow the
    independent root reference, preserving flight rather than preferring rest.
    No contact is added across gaps between observed episodes.
    """
    from scipy.sparse import coo_matrix
    from scipy.sparse.linalg import lsqr

    points = np.asarray(points, dtype=float)
    count = len(points)
    episodes = []
    for joint in range(points.shape[1]):
        bounds = np.flatnonzero(np.diff(np.r_[False, pinned[:, joint], False]))
        episodes.extend((joint, int(start), int(stop)) for start, stop in zip(bounds[::2], bounds[1::2]))
    if not episodes:
        return points.copy(), {'applied': False, 'reason': 'no_stationary_contacts'}
    if (np.max(abs(np.asarray(root_reference)-points[:, root_index])) < 1e-9
            and all(np.max(np.ptp(points[start:stop, joint], axis=0)) < 1e-9
                    for joint, start, stop in episodes)):
        # Preserve an already coherent input exactly. Even picometer changes
        # needlessly perturb the nonlinear fit's numerically redundant rotations.
        return points.copy(), {'applied': False, 'reason': 'placement_already_coherent'}
    rows, columns, coefficients, rhs = [], [], [], []

    def append_row(cols, weights, value):
        rows.extend([len(rhs)]*len(cols))
        columns.extend(cols)
        coefficients.extend(weights)
        rhs.append(value)

    for frame in range(count):
        append_row([frame], [.2], np.zeros(3))
    for episode, (joint, start, stop) in enumerate(episodes):
        for frame in range(start, stop):
            append_row([frame, count+episode], [100., -100.], -100.*points[frame, joint])
    reference_correction = np.asarray(root_reference)-points[:, root_index]
    for order, stencil in ((2, np.array([1., -2., 1.])), (3, np.array([-1., 3., -3., 1.]))):
        weight = 20.*(fps/30.)**order
        target = np.diff(reference_correction, n=order, axis=0)*weight
        for frame, value in enumerate(target):
            append_row(list(range(frame, frame+order+1)), (stencil*weight).tolist(), value)
    matrix = coo_matrix((coefficients, (rows, columns)), shape=(len(rhs), count+len(episodes))).tocsr()
    rhs = np.asarray(rhs)
    solved = [lsqr(matrix, rhs[:, axis], atol=1e-10, btol=1e-10, iter_lim=3000) for axis in range(3)]
    if any(result[1] not in (0, 1, 2) for result in solved):
        return points.copy(), {'applied': False, 'reason': 'placement_registration_did_not_converge',
                               'solverStops': [result[1] for result in solved]}
    translation = np.column_stack([result[0][:count] for result in solved])
    return points+translation[:, None, :], {
        'applied': True, 'policy': 'joint_stance_anchor_registration_v1',
        'observedEpisodes': len(episodes), 'iterations': [result[2] for result in solved],
        'maximumTranslationCorrectionMeters': float(np.linalg.norm(translation, axis=-1).max()),
    }


def contact_consistent_target(target, pinned, anchors):
    """Align each supported pose by translation, using only explicit contacts.

    The common displacement preserves articulation. During releases, interpolate
    that displacement rather than constraining the airborne body or adding a
    contact. Contacted points use their independent stance anchors as targets.
    """
    target = np.asarray(target, dtype=float)
    supported = pinned.any(axis=1)
    shift = np.zeros((len(target), 3))
    if supported.any():
        delta = np.sum((anchors-target)*pinned[:, :, None], axis=1)
        shift[supported] = delta[supported]/pinned.sum(axis=1)[supported, None]
        indices = np.arange(len(target))
        for axis in range(3):
            shift[:, axis] = np.interp(indices, indices[supported], shift[supported, axis])
    grounded = target+shift[:, None, :]
    disagreement = np.linalg.norm((grounded-anchors)[pinned], axis=-1)
    grounded[pinned] = anchors[pinned]
    return grounded, shift, {
        'policy': 'explicit_contact_translation_target_v1',
        'supportedFrames': int(supported.sum()),
        'maximumPlacementCorrectionMeters': float(np.max(np.linalg.norm(shift, axis=-1), initial=0.)),
        'maximumContactDisagreementAfterTranslationMeters': float(np.max(disagreement, initial=0.)),
    }


def align_registered_contacts_above_floor(points, pinned, foot_indices, floor):
    """Resolve registration's global height gauge without changing articulation.

    Use stationary foot anchors, not an airborne extremity, to establish height.
    Relative support heights remain unchanged; this does not force every foot
    onto the same surface or invent a contact.
    """
    heights = []
    if floor is not None:
        for joint in foot_indices:
            bounds = np.flatnonzero(np.diff(np.r_[False, pinned[:, joint], False]))
            heights.extend(float(np.median(points[start:stop, joint, 1]))
                           for start, stop in zip(bounds[::2], bounds[1::2]))
    shift = max(0., float(floor)-min(heights)) if heights else 0.
    return (points.copy() if shift == 0. else points+np.array([0., shift, 0.])), shift


def root_motion_quality(root, fps, scale):
    """Screen abrupt placement changes independently of noisy input motion.

    Constant-speed travel has zero second difference. The 30 Hz normalized
    limit screens rapid changes in translation, not speed, balance, or travel
    direction. This is an animation continuity policy, not a physical force limit.
    """
    root = np.asarray(root, dtype=float)
    if len(root) < 3 or not np.isfinite(root).all() or not np.isfinite(fps) or fps <= 0 or not np.isfinite(scale) or scale <= 0:
        return {'available': False, 'passed': False, 'reason': 'root_motion_unavailable'}
    acceleration = np.linalg.norm(np.diff(root, n=2, axis=0), axis=-1)*(fps/30.)**2
    limit = .05*scale
    events = np.flatnonzero(acceleration > limit)+1
    return {'available': True, 'passed': not bool(len(events)),
            'policy': 'root_translation_continuity_v1',
            'maximumSecondDifferenceMetersAt30Hz': float(acceleration.max()),
            'limitMetersAt30Hz': float(limit), 'frames': events.tolist()}


def root_motion_quality_from_payload(payload):
    from .physical_validation import body_scale

    frames = payload.get('frames') or []
    names = [n for n in payload.get('jointNames', [])
             if all(n in f.get('joints', {}) for f in frames)]
    root = next((n for n in (payload.get('rootJoint'), 'pelvis', 'hips', 'root') if n in names), None)
    if len(frames) < 3 or root is None:
        return {'available': False, 'passed': False, 'reason': 'root_motion_unavailable'}
    points = np.asarray([[f['joints'][n] for n in names] for f in frames], dtype=float)
    return root_motion_quality(points[:, names.index(root)], float(payload.get('fps') or 30.), body_scale(points, names))
