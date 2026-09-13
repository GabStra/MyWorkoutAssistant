"""Separate observed articulation from contact-constrained world placement."""
from __future__ import annotations

import numpy as np


def register_contact_placement(points, pinned, root_index, fps, root_reference, *, ground_contacts=None, floor=None):
    """Register stance anchors together, before freezing them for kinematic fit.

    Unknowns are one translation per frame and one point per observed stance.
    Source-relative limb positions are unchanged. Temporal terms follow the
    independent root reference, preserving flight rather than preferring rest.
    No contact is added across gaps between observed episodes.
    """
    from scipy.sparse import bmat, coo_matrix, eye
    from scipy.sparse.linalg import splu

    points = np.asarray(points, dtype=float)
    count = len(points)
    episodes = []
    for joint in range(points.shape[1]):
        bounds = np.flatnonzero(np.diff(np.r_[False, pinned[:, joint], False]))
        episodes.extend((joint, int(start), int(stop)) for start, stop in zip(bounds[::2], bounds[1::2]))
    if not episodes:
        return points.copy(), {'applied': False, 'reason': 'no_stationary_contacts'}
    ground_episodes = [index for index, (joint, start, stop) in enumerate(episodes)
                       if floor is not None and ground_contacts is not None
                       and np.any(ground_contacts[start:stop, joint])]
    if (np.max(abs(np.asarray(root_reference)-points[:, root_index])) < 1e-9
            and all(np.max(np.ptp(points[start:stop, joint], axis=0)) < 1e-9
                    for joint, start, stop in episodes)
            and all(abs(points[episodes[i][1], episodes[i][0], 1]-floor) < 1e-9
                    for i in ground_episodes)):
        # Preserve an already coherent input exactly. Even picometer changes
        # needlessly perturb the nonlinear fit's numerically redundant rotations.
        return points.copy(), {'applied': False, 'reason': 'placement_already_coherent'}
    rows, columns, coefficients, rhs = [], [], [], []

    def append_row(cols, weights, value):
        rows.extend([len(rhs)]*len(cols))
        columns.extend(cols)
        coefficients.extend(weights)
        rhs.append(value)

    reference_correction = np.asarray(root_reference)-points[:, root_index]
    for frame in range(count):
        # In unconstrained flight follow the independent root reference, rather
        # than pulling back toward a known discontinuous placement input.
        append_row([frame], [.2], .2*reference_correction[frame])
    for episode, (joint, start, stop) in enumerate(episodes):
        for frame in range(start, stop):
            append_row([frame, count+episode], [100., -100.], -100.*points[frame, joint])
    for order, stencil in ((2, np.array([1., -2., 1.])), (3, np.array([-1., 3., -3., 1.]))):
        weight = 20.*(fps/30.)**order
        target = np.diff(reference_correction, n=order, axis=0)*weight
        for frame, value in enumerate(target):
            append_row(list(range(frame, frame+order+1)), (stencil*weight).tolist(), value)
    matrix = coo_matrix((coefficients, (rows, columns)), shape=(len(rhs), count+len(episodes))).tocsr()
    rhs = np.asarray(rhs)
    # Solve r + A x = b, A.T r = 0 with one sparse factorization for all axes.
    # Long free-flight intervals make iterative least squares converge slowly.
    # The augmented system preserves the same objective without explicitly
    # forming A.T A (which squares the matrix's condition number).
    system = bmat([[eye(matrix.shape[0]), matrix], [matrix.T, None]], format='csc')
    system_rhs = np.vstack([rhs, np.zeros((matrix.shape[1], 3))])
    try:
        solved = splu(system).solve(system_rhs)
    except RuntimeError:
        return points.copy(), {'applied': False, 'reason': 'placement_registration_did_not_converge',
                               'solver': 'sparse_augmented_lu', 'solverFailure': 'factorization_failed'}
    residual = system @ solved-system_rhs
    scale = float(abs(system).sum(axis=1).max())*np.max(abs(solved))+np.max(abs(system_rhs))
    backward_error = float(np.max(abs(residual))/max(float(scale), np.finfo(float).tiny))
    if not np.isfinite(solved).all() or not np.isfinite(backward_error) or backward_error > 1e-10:
        return points.copy(), {'applied': False, 'reason': 'placement_registration_did_not_converge',
                               'solver': 'sparse_augmented_lu', 'solverFailure': 'residual_check_failed'}
    translation = solved[matrix.shape[0]:matrix.shape[0]+count]
    if ground_episodes:
        # Eliminate known anchor heights from the vertical solve. A stationary
        # point on an observed floor cannot acquire an arbitrary height after
        # each release. Horizontal anchors and free-flight frames remain free.
        known = np.asarray([count+i for i in ground_episodes])
        free = np.ones(matrix.shape[1], dtype=bool)
        free[known] = False
        reduced = matrix[:, free]
        vertical_rhs = rhs[:, 1]-np.asarray(matrix[:, known].sum(axis=1)).ravel()*float(floor)
        vertical_system = bmat([[eye(matrix.shape[0]), reduced], [reduced.T, None]], format='csc')
        vertical_target = np.r_[vertical_rhs, np.zeros(reduced.shape[1])]
        try:
            vertical_solution = splu(vertical_system).solve(vertical_target)
        except RuntimeError:
            return points.copy(), {'applied': False, 'reason': 'placement_registration_did_not_converge',
                                   'solverFailure': 'ground_factorization_failed'}
        vertical_residual = vertical_system@vertical_solution-vertical_target
        vertical_scale = float(abs(vertical_system).sum(axis=1).max())*np.max(abs(vertical_solution))+np.max(abs(vertical_target))
        vertical_error = float(np.max(abs(vertical_residual))/max(float(vertical_scale), np.finfo(float).tiny))
        if not np.isfinite(vertical_solution).all() or not np.isfinite(vertical_error) or vertical_error > 1e-10:
            return points.copy(), {'applied': False, 'reason': 'placement_registration_did_not_converge',
                                   'solverFailure': 'ground_residual_check_failed'}
        translation[:, 1] = vertical_solution[matrix.shape[0]:matrix.shape[0]+count]
        backward_error = max(backward_error, vertical_error)
    return points+translation[:, None, :], {
        'applied': True, 'policy': 'joint_stance_anchor_registration_v3',
        'observedGroundEpisodes': len(ground_episodes),
        'observedEpisodes': len(episodes), 'solver': 'sparse_augmented_lu',
        'solverBackwardError': backward_error,
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
