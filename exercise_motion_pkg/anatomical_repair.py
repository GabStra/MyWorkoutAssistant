"""Project malformed observations onto the existing fixed rig before fitting."""
from time import monotonic
import hashlib
import json

import numpy as np
from scipy.optimize import least_squares

from .physical_validation import anatomical_structure_residuals, angles, body_scale


ANATOMICAL_REPAIR_STRATEGY = 'fixed_rig_anatomical_projection_v5_local_dof'

# Stop soft polishing once geometry is valid and overall lean matches the
# observation to the same tolerance as the lean-preservation tests.
_ANATOMY_FEASIBLE_LEAN = 1e-5


class _AnatomyFeasible(Exception):
    """Stop least_squares once geometry is already inside repair bounds."""

    def __init__(self, values):
        self.values = np.asarray(values, dtype=float)

# Cap pathological pre-solve burn, but leave room for hard multi-frame repairs.
# Short clips stay near the historical 480 floor. Long clips with widespread
# source violations need ~12–15 evals per bad frame (measured); a fixed 480
# budget left hundreds of independently solvable frames unrepaired.
ANATOMY_REPAIR_MAX_EVALS_PER_FRAME = 60
ANATOMY_REPAIR_MAX_TOTAL_EVALS = 480
ANATOMY_REPAIR_EVALS_PER_BAD_FRAME = 16
ANATOMY_REPAIR_MAX_TOTAL_EVALS_CEILING = 8000


def anatomy_repair_evaluation_budget(bad_frame_count):
    """Scale the eval ceiling with how many frames actually need projection."""
    count = max(0, int(bad_frame_count))
    return int(min(
        ANATOMY_REPAIR_MAX_TOTAL_EVALS_CEILING,
        max(ANATOMY_REPAIR_MAX_TOTAL_EVALS, count * ANATOMY_REPAIR_EVALS_PER_BAD_FRAME),
    ))

# These defects may reach projection; they still must pass final validation.
# Degenerate bones and non-anatomical physical failures are not repair promises.
ANATOMICAL_REPAIR_INPUT_REASONS = frozenset({
    'anatomy_bilateral_proportions', 'anatomy_segment_proportion',
    'anatomy_socket_alignment', 'anatomy_torso_bend',
    'anatomy_chest_attachment', 'anatomy_spine_deviation',
    'anatomy_spine_fold', 'anatomy_neck_fold', 'anatomy_hinge_collapse',
    'anatomy_bone_length_variation', 'anatomy_span_variation',
})


def torso_directions(points, names):
    hips = (points[:, names.index('left_hip')]+points[:, names.index('right_hip')])*.5
    directions = points[:, names.index('neck')]-hips
    return directions/np.maximum(np.linalg.norm(directions, axis=-1, keepdims=True), 1e-9)


def repair_residuals(points, names, span_targets=None):
    structure, labels = anatomical_structure_residuals(points, names)
    rows = [structure]
    for side in ('left', 'right'):
        joints = [side+'_'+n for n in ('knee', 'ankle', 'foot')]
        value = angles(*(points[:, names.index(n)] for n in joints))
        rows.append(np.maximum(np.maximum(np.deg2rad(35.1)-value, value-np.deg2rad(164.9)), 0.)[:, None])
        labels.append('anatomy_ankle_collapse:'+side+'_ankle')
    from .physical_validation import (SPAN_TOLERANCE_METERS, SPAN_TOLERANCE_RATIO,
                                      span_rigidity_violations)
    for label, (deviation, target) in span_rigidity_violations(points, names, span_targets).items():
        rows.append(np.maximum(deviation-max(SPAN_TOLERANCE_METERS, target*SPAN_TOLERANCE_RATIO), 0.)[:, None])
        labels.append('anatomy_span_variation:'+label)
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


def _joints_for_repair_label(label, names, parents):
    reason, joint = label.split(':', 1)
    if reason == 'anatomy_ankle_collapse':
        side = joint.split('_')[0]
        return [side + '_' + part for part in ('knee', 'ankle', 'foot')]
    if reason == 'anatomy_span_variation':
        if joint == 'shoulders':
            return ['left_shoulder', 'right_shoulder', 'left_collar', 'right_collar', 'spine3', 'neck']
        if joint == 'hips':
            return ['left_hip', 'right_hip', 'pelvis', 'spine1']
        return [joint]
    if reason == 'anatomy_degenerate_bone':
        parent = names[parents[names.index(joint)]] if joint in names and parents[names.index(joint)] >= 0 else joint
        return [joint, parent]
    if reason == 'anatomy_bilateral_proportions':
        other = joint.replace('left_', 'right_', 1)
        affected = [joint, other]
        for name in list(affected):
            if name in names and parents[names.index(name)] >= 0:
                affected.append(names[parents[names.index(name)]])
        return affected
    if reason == 'anatomy_segment_proportion':
        return [joint, names[parents[names.index(joint)]]] if joint in names and parents[names.index(joint)] >= 0 else [joint]
    if reason == 'anatomy_socket_alignment':
        suffix = 'hip' if joint == 'pelvis' else 'collar'
        return [joint, 'left_' + suffix, 'right_' + suffix]
    if reason == 'anatomy_hinge_collapse':
        side, hinge = joint.split('_', 1)
        parts = ('hip', 'knee', 'ankle') if hinge == 'knee' else ('shoulder', 'elbow', 'wrist')
        return [side + '_' + part for part in parts]
    if reason == 'anatomy_spine_deviation':
        return ['pelvis', 'neck', joint]
    if reason == 'anatomy_spine_fold':
        parent = names[parents[names.index(joint)]] if joint in names else joint
        return ['pelvis', 'neck', joint, parent]
    if reason == 'anatomy_neck_fold':
        return ['spine3', 'neck', 'head']
    if reason == 'anatomy_torso_bend':
        affected = ['left_hip', 'right_hip', 'spine1']
        affected += ['left_shoulder', 'right_shoulder'] if joint == 'shoulders' else ['neck']
        return affected
    if reason == 'anatomy_chest_attachment':
        affected = ['spine3', 'neck']
        affected += (['left_shoulder', 'right_shoulder'] if joint == 'shoulders'
                     else ['left_collar', 'right_collar'])
        return affected
    if reason == 'anatomy_bone_length_variation':
        return [joint]
    return [joint] if joint in names else []


def free_rotation_columns(rig, active_labels):
    """Limit FD probes to rotations that can fix the active frame violations."""
    names = rig.names
    affected = {'pelvis', 'left_hip', 'right_hip', 'neck'}
    for label in active_labels:
        affected.update(_joints_for_repair_label(label, names, rig.parents))
    columns = set()
    for name in affected:
        if name not in names:
            continue
        ancestor = names.index(name)
        while ancestor >= 0:
            if ancestor in rig.slots:
                columns.update(range(rig.slots[ancestor], rig.slots[ancestor] + 3))
            ancestor = rig.parents[ancestor]
    return sorted(columns) or list(range(3, rig.width))


def repair_rig_anatomy(rig, observed, *, deadline):
    """Correct curvature with fixed root positions, lengths and overall lean.

    This is an initializer for the contact/temporal fit, not a replacement for
    it. Already feasible frames are untouched. No exercise-specific mirroring
    or new body template is introduced. Final playback validation stays strict.
    """
    names = rig.names
    from .fit_runtime import current_fit_session
    session = current_fit_session()
    from .physical_validation import span_rigidity_violations
    span_targets = {label: target
                    for label, (_, target) in span_rigidity_violations(observed, names).items()}
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
    violations, _ = repair_residuals(initial_points, names, span_targets)
    bad = np.any(violations > 1e-6, axis=1)
    evaluation_budget = anatomy_repair_evaluation_budget(int(bad.sum()))
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
    skipped_feasible = 0
    free_column_total = 0
    free_column_frames = 0
    previous_correction = None
    cache = {}
    span_target_key = json.dumps(span_targets, sort_keys=True, separators=(',', ':')).encode()

    for frame in np.flatnonzero(bad):
        if evaluated >= evaluation_budget:
            break
        if monotonic() >= deadline:
            break
        base = rig.initial[frame].copy()
        target = initial_points[frame]-base[:3]
        torso_direction = observed_torso_directions[frame]
        key = hashlib.sha256(ANATOMICAL_REPAIR_STRATEGY.encode() + repr(names).encode()
                             + span_target_key
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

        active_labels = [labels[index] for index in np.flatnonzero(violations[frame] > 1e-6)]
        free_columns = free_rotation_columns(rig, active_labels)
        column_position = {column: index for index, column in enumerate(columns)}
        free_column_total += len(free_columns)
        free_column_frames += 1
        frame_nfev = 0
        seed_full = base[columns]

        def pack(full_values):
            return np.asarray([full_values[column_position[column]] for column in free_columns], dtype=float)

        def unpack(free_values, full_seed):
            full_values = np.asarray(full_seed, dtype=float).copy()
            for column, value in zip(free_columns, free_values):
                full_values[column_position[column]] = value
            return full_values

        def repair_feasible(values):
            current = base.copy()
            current[columns] = values
            candidate = rig.decode(current[None])
            if np.max(repair_residuals(candidate, names, span_targets)[0], initial=0.) > 1e-6:
                return False
            lean = torso_directions(candidate, names) - torso_direction
            return float(np.max(np.abs(lean), initial=0.)) <= _ANATOMY_FEASIBLE_LEAN

        def residual_batch(values):
            nonlocal residual_batches, residual_points, frame_nfev
            from .fit_runtime import fit_should_yield_for_priority
            if fit_should_yield_for_priority() or monotonic() >= deadline:
                raise TimeoutError
            residual_batches += 1
            residual_points += len(values)
            if len(values) == 1:
                frame_nfev += 1
            current = np.tile(base, (len(values), 1))
            for row, free_values in enumerate(values):
                current[row, columns] = unpack(free_values, seed_full)
            candidate = rig.decode(current)
            geometry = repair_residuals(candidate, names, span_targets)[0]
            lean = torso_directions(candidate, names)-torso_direction
            # Soft orientation polishing used to keep burning evals after the
            # initializer bounds were already met. Exit as soon as geometry and
            # lean pass; keep a light fidelity pull so articulation stays near
            # the observation while those bounds are enforced.
            if (len(values) == 1 and np.max(geometry, initial=0.) <= 1e-6
                    and float(np.max(np.abs(lean), initial=0.)) <= _ANATOMY_FEASIBLE_LEAN):
                raise _AnatomyFeasible(unpack(values[0], seed_full))
            fidelity = (candidate-base[:3]-target)/scale
            return np.concatenate([fidelity.reshape(len(values), -1),
                                   10000.*geometry, 10000.*lean], axis=1)

        full_initial = base[columns]
        if previous_correction is not None:
            proposed = full_initial + previous_correction
            try:
                costs = np.sum(residual_batch(np.stack([pack(full_initial), pack(proposed)]))**2, axis=1)
            except TimeoutError:
                # Warm-start scoring uses the same deadline/priority guard as
                # the solver. Return completed frames and their diagnostics
                # even when the budget expires before this frame's solve.
                break
            if costs[1] < costs[0]:
                full_initial = proposed
                seed_full = full_initial
                warm_starts += 1
        if repair_feasible(full_initial):
            rig.initial[frame, columns] = full_initial
            cache[key] = np.asarray(full_initial, dtype=float)
            previous_correction = full_initial - base[columns]
            skipped_feasible += 1
            if session is not None:
                session.repairs[key] = np.asarray(full_initial, dtype=float).tolist()
            continue
        frame_budget = min(
            ANATOMY_REPAIR_MAX_EVALS_PER_FRAME,
            evaluation_budget - evaluated,
        )
        if frame_budget < 1:
            break
        try:
            solved = least_squares(
                lambda values: residual_batch(values[None])[0], pack(seed_full),
                jac=lambda values: batched_forward_jacobian(residual_batch, values),
                max_nfev=frame_budget, ftol=1e-8, xtol=1e-8, gtol=1e-8)
            solved_x = unpack(solved.x, seed_full)
            evaluated += solved.nfev
        except _AnatomyFeasible as done:
            solved_x = done.values
            evaluated += max(frame_nfev, 1)
        except TimeoutError:
            break
        rig.initial[frame, columns] = solved_x
        cache[key] = solved_x
        previous_correction = solved_x-base[columns]
        if session is not None and repair_feasible(solved_x):
            session.repairs[key] = np.asarray(solved_x, dtype=float).tolist()

    corrected = rig.decode(rig.initial)
    after, _ = repair_residuals(corrected, names, span_targets)
    displacement = np.linalg.norm(corrected-observed, axis=-1)
    lean_change = np.rad2deg(np.arccos(np.clip(np.sum(
        torso_directions(corrected, names)*observed_torso_directions, axis=-1), -1., 1.)))
    remaining_bad = int(np.sum(np.any(after > 1e-6, axis=1)))
    return corrected, {
        'strategy': ANATOMICAL_REPAIR_STRATEGY,
        'applied': bool(np.max(displacement) > 1e-8),
        'passed': bool(np.max(after, initial=0.) <= 1e-6),
        'sourceViolations': sorted({labels[i] for i in np.flatnonzero(np.any(before > 1e-6, axis=0))}),
        'remainingViolations': sorted({labels[i] for i in np.flatnonzero(np.any(after > 1e-6, axis=0))}),
        'projectedFrameCount': int(bad.sum()), 'evaluations': evaluated,
        'residualBatchCount': residual_batches, 'residualPointCount': residual_points,
        'warmStartedFrameCount': warm_starts,
        'feasibleSkipFrameCount': skipped_feasible,
        'averageFreeColumnCount': (
            float(free_column_total) / free_column_frames if free_column_frames else float(len(columns))),
        'evaluationBudget': evaluation_budget,
        'unrepairedFrameCount': remaining_bad,
        'maximumCorrectionMeters': float(displacement.max()),
        'maximumTorsoDirectionChangeDegrees': float(lean_change.max()),
    }
