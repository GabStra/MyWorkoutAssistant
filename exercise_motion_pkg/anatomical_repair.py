"""Project malformed observations onto the existing fixed rig before fitting."""
from time import monotonic

import numpy as np
from scipy.optimize import least_squares

from .physical_validation import anatomical_structure_residuals, angles, body_scale


ANATOMICAL_REPAIR_STRATEGY = 'fixed_rig_anatomical_projection_v2_preserve_lean'


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


def repair_rig_anatomy(rig, observed, *, deadline):
    """Correct curvature with fixed root positions, lengths and overall lean.

    This is an initializer for the contact/temporal fit, not a replacement for
    it. Already feasible frames are untouched. No exercise-specific mirroring
    or new body template is introduced. Final playback validation stays strict.
    """
    names = rig.names
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
        key = (base[3:].tobytes(), target.tobytes(), torso_direction.tobytes())
        if key in cache:
            rig.initial[frame, columns] = cache[key]
            continue

        def residual(values):
            if monotonic() >= deadline:
                raise TimeoutError
            current = base.copy()
            current[columns] = values
            candidate = rig.decode(current[None])
            geometry = repair_residuals(candidate, names)[0]
            fidelity = (candidate[0]-base[:3]-target)/scale
            bones = candidate[0, children]-candidate[0, parents]
            directions = bones/np.maximum(np.linalg.norm(bones, axis=-1, keepdims=True), 1e-9)
            orientation = (directions-target_directions)*direction_weights[:, None]
            lean = torso_directions(candidate, names)[0]-torso_direction
            return np.r_[fidelity.ravel(), orientation.ravel(),
                         10000.*geometry.ravel(), 10000.*lean]

        solved = least_squares(residual, base[columns], max_nfev=80,
                               ftol=1e-8, xtol=1e-8, gtol=1e-8)
        evaluated += solved.nfev
        rig.initial[frame, columns] = solved.x
        cache[key] = solved.x
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
        'maximumCorrectionMeters': float(displacement.max()),
        'maximumTorsoDirectionChangeDegrees': float(lean_change.max()),
    }
