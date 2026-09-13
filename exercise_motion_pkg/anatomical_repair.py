"""Project malformed observations onto the existing fixed rig before fitting."""
from time import monotonic
import hashlib

import numpy as np
from scipy.optimize import least_squares

from .physical_validation import anatomical_structure_residuals, angles, body_scale


ANATOMICAL_REPAIR_STRATEGY = 'fixed_rig_anatomical_projection_v3_batched_derivatives'

# These defects may reach projection; they still must pass final validation.
# Degenerate bones and non-anatomical physical failures are not repair promises.
ANATOMICAL_REPAIR_INPUT_REASONS = frozenset({
    'anatomy_bilateral_proportions', 'anatomy_segment_proportion',
    'anatomy_socket_alignment', 'anatomy_torso_bend',
    'anatomy_chest_attachment', 'anatomy_spine_deviation',
    'anatomy_spine_fold', 'anatomy_neck_fold', 'anatomy_hinge_collapse',
    'anatomy_bone_length_variation',
})


def torso_directions(points, names):
    hips = (points[:, names.index('left_hip')]+points[:, names.index('right_hip')])*.5
    directions = points[:, names.index('neck')]-hips
    return directions/np.maximum(np.linalg.norm(directions, axis=-1, keepdims=True), 1e-9)


def repair_residuals(points, names):
    structure, labels = anatomical_structure_residuals(points, names)
    rows = [structure]
    for side in ('left', 'right'):
        joints = [side+'_'+n for n in ('knee', 'ankle', 'foot')]
        value = angles(*(points[:, names.index(n)] for n in joints))
        rows.append(np.maximum(np.maximum(np.deg2rad(35.1)-value, value-np.deg2rad(164.9)), 0.)[:, None])
        labels.append('anatomy_ankle_collapse:'+side+'_ankle')
    return np.concatenate(rows, axis=1), labels


def transport_equivalent_anatomical_repair(observed, corrected, reference, names):
    """Reuse a repair only across a verified rigid coordinate-frame change."""
    root = names.index('pelvis')
    origin = observed[:, root:root+1]
    reference_origin = reference[:, root:root+1]
    local, reference_local = observed-origin, reference-reference_origin
    u, _, vt = np.linalg.svd(local.reshape(-1, 3).T @ reference_local.reshape(-1, 3))
    proper = np.diag([1., 1., np.linalg.det(u @ vt)])
    rotation = u @ proper @ vt
    if not np.allclose(local @ rotation, reference_local, atol=1e-10, rtol=0.):
        return None
    transported = (corrected-origin) @ rotation+reference_origin
    if not np.isfinite(transported).all() or np.max(repair_residuals(transported, names)[0], initial=0.) > 1e-6:
        return None
    return transported


def batched_forward_jacobian(residual_batch, values):
    """Evaluate independent perturbations together, with SciPy's step floor.

    Residual rows must be independent observations, never temporal differences.
    This changes scheduling only: every coordinate still gets its own derivative.
    """
    steps = np.sqrt(np.finfo(float).eps) * np.where(values >= 0., 1., -1.) * np.maximum(1., abs(values))
    probes = np.tile(values, (len(values) + 1, 1))
    probes[np.arange(len(values)) + 1, np.arange(len(values))] += steps
    actual_steps = probes[np.arange(len(values)) + 1, np.arange(len(values))] - values
    residuals = residual_batch(probes)
    return ((residuals[1:] - residuals[0]) / actual_steps[:, None]).T


def repair_rig_anatomy(rig, observed, *, deadline):
    """Correct curvature with fixed root positions, lengths and overall lean.

    This is an initializer for the contact/temporal fit, not a replacement for
    it. Already feasible frames are untouched. No exercise-specific mirroring
    or new body template is introduced. Final playback validation stays strict.
    """
    names = rig.names
    from .fit_runtime import current_fit_session
    session = current_fit_session()
    before, labels = repair_residuals(observed, names)
    # Only impossible proportions are changed; preserve the approved model's
    # dimensions whenever they are already inside the display-rig bounds.
    for side in ('left', 'right'):
        for child, base, low, high in [('elbow','knee',.4,1.2), ('wrist','elbow',.55,1.25),
                                        ('ankle','knee',.65,1.4), ('foot','ankle',.15,.65)]:
            a, b = names.index(side+'_'+child), names.index(side+'_'+base)
            length, base_length = np.linalg.norm(rig.offsets[a]), np.linalg.norm(rig.offsets[b])
            if length > 1e-9 and base_length > 1e-9:
                fitted_length = np.clip(length, base_length*low, base_length*high)
                rig.offsets[a] *= fitted_length/length
    initial_points = rig.decode(rig.initial)
    violations, _ = repair_residuals(initial_points, names)
    bad = np.any(violations > 1e-6, axis=1)
    # Pelvis rotation must remain available: freezing it makes the solver
    # straighten a bent back by standing the upper body up instead of hinging
    # at the hips. Root translation remains fixed.
    columns = list(range(3, rig.width))
    observed_torso_directions = torso_directions(observed, names)
    scale = body_scale(observed, names)
    evaluated = 0
    residual_batches = 0
    residual_points = 0
    warm_starts = 0
    previous_correction = None
    cache = {}
    children = rig.order[1:]
    parents = [rig.parents[j] for j in children]
    direction_weights = np.array([1. if names[j] == 'head' else .3 for j in children])
    for frame in np.flatnonzero(bad):
        base = rig.initial[frame].copy()
        target = initial_points[frame]-base[:3]
        target_bones = target[children]-target[parents]
        target_directions = target_bones/np.maximum(np.linalg.norm(target_bones, axis=-1, keepdims=True), 1e-9)
        torso_direction = observed_torso_directions[frame]
        key = hashlib.sha256(ANATOMICAL_REPAIR_STRATEGY.encode() + repr(names).encode()
                             + rig.offsets.tobytes() + np.float64(scale).tobytes()
                             + base[3:].tobytes() + target.tobytes() + torso_direction.tobytes()).hexdigest()
        if session is not None and key in session.repairs:
            cached = np.asarray(session.repairs[key], dtype=float)
            if cached.shape == (len(columns),) and np.isfinite(cached).all():
                cache[key] = cached
                session.reused_frames += 1
        if key in cache:
            rig.initial[frame, columns] = cache[key]
            continue

        def residual_batch(values):
            nonlocal residual_batches, residual_points
            if monotonic() >= deadline:
                raise TimeoutError
            residual_batches += 1
            residual_points += len(values)
            current = np.tile(base, (len(values), 1))
            current[:, columns] = values
            candidate = rig.decode(current)
            geometry = repair_residuals(candidate, names)[0]
            fidelity = (candidate-base[:3]-target)/scale
            bones = candidate[:, children]-candidate[:, parents]
            directions = bones/np.maximum(np.linalg.norm(bones, axis=-1, keepdims=True), 1e-9)
            orientation = (directions-target_directions)*direction_weights[:, None]
            lean = torso_directions(candidate, names)-torso_direction
            return np.concatenate([fidelity.reshape(len(values), -1),
                                   orientation.reshape(len(values), -1),
                                   10000.*geometry, 10000.*lean], axis=1)

        initial = base[columns]
        if previous_correction is not None:
            proposed = initial + previous_correction
            costs = np.sum(residual_batch(np.stack([initial, proposed]))**2, axis=1)
            if costs[1] < costs[0]:
                initial = proposed
                warm_starts += 1
        solved = least_squares(lambda values: residual_batch(values[None])[0], initial,
                               jac=lambda values: batched_forward_jacobian(residual_batch, values), max_nfev=80,
                               ftol=1e-8, xtol=1e-8, gtol=1e-8)
        evaluated += solved.nfev
        rig.initial[frame, columns] = solved.x
        cache[key] = solved.x
        previous_correction = solved.x-base[columns]
        # Persist only feasible completed frames; a timed-out fit can resume them.
        if session is not None:
            candidate = rig.decode(rig.initial[frame:frame+1])
            if np.max(repair_residuals(candidate, names)[0], initial=0.) <= 1e-6:
                session.repairs[key] = solved.x.tolist()
    corrected = rig.decode(rig.initial)
    after, _ = repair_residuals(corrected, names)
    displacement = np.linalg.norm(corrected-observed, axis=-1)
    lean_change = np.rad2deg(np.arccos(np.clip(np.sum(
        torso_directions(corrected, names)*observed_torso_directions, axis=-1), -1., 1.)))
    return corrected, {
        'strategy': ANATOMICAL_REPAIR_STRATEGY,
        'applied': bool(np.max(displacement) > 1e-8),
        'passed': bool(np.max(after, initial=0.) <= 1e-6),
        'sourceViolations': sorted({labels[i] for i in np.flatnonzero(np.any(before > 1e-6, axis=0))}),
        'remainingViolations': sorted({labels[i] for i in np.flatnonzero(np.any(after > 1e-6, axis=0))}),
        'projectedFrameCount': int(bad.sum()), 'evaluations': evaluated,
        'residualBatchCount': residual_batches, 'residualPointCount': residual_points,
        'warmStartedFrameCount': warm_starts,
        'maximumCorrectionMeters': float(displacement.max()),
        'maximumTorsoDirectionChangeDegrees': float(lean_change.max()),
    }
