"""Temporal fitting in rotation space without shortening articulated bones."""

from __future__ import annotations

import copy
import threading
from collections import OrderedDict
from dataclasses import replace
from time import monotonic

import numpy as np
from scipy.spatial.transform import Rotation
from scipy.optimize._numdiff import approx_derivative, group_columns

from .models import MotionClip, MotionFrame


def _norm(vectors: np.ndarray) -> np.ndarray:
    """Row-wise Euclidean length without np.linalg.norm's dispatch overhead."""
    return np.sqrt(np.einsum('...i,...i->...', vectors, vectors))


def _natural_jacobian_column_groups(pattern) -> np.ndarray:
    """Color a frame-major sparse Jacobian in its temporal locality order."""
    return group_columns(pattern, order=np.arange(pattern.shape[1]))


def fit_pose_and_temporal_trajectories(
    source: MotionClip,
    proposal: MotionClip,
    chains: tuple[tuple[str, ...], ...],
    *,
    observation_weights: list[list[float]] | np.ndarray | None = None,
    rigid_pair: tuple[str, str] | None = None,
    timeout_seconds: float = 20.0,
    max_evaluations: int = 80,
    projected_observations: bool = False,
    rigid_distances: tuple[tuple[str, str], ...] = (),
    fit_root_translation: bool = False,
    projection_segments: tuple[tuple[str, str], ...] = (),
    rigid_pair_reference: tuple[str, str] | None = None,
    lsmr_max_iterations: int = 100,
    lsmr_tolerance: float | None = None,
    x_scale: str | float = 1.0,
) -> tuple[MotionClip, dict[str, object]]:
    """Fit observed pose targets and temporal limits in one rigid-chain solve.

    Roots are immutable unless their translation is explicitly fitted.
    Unrelated joints stay fixed. Rotating each original bone
    preserves its length exactly; no joint-angle acceptance rule is used here.
    Missing observations have zero target weight, not a target of zero correction.
    """
    from scipy.optimize import least_squares
    from scipy.sparse import diags, kron, vstack, eye

    started = monotonic()
    edges = list(dict.fromkeys(edge for chain in chains for edge in zip(chain, chain[1:])))
    count = source.frame_count
    report = {'applied': False, 'strategy': 'joint_pose_temporal_trajectory_v1'}
    if (timeout_seconds <= 0 or max_evaluations < 1 or lsmr_max_iterations < 1
            or (lsmr_tolerance is not None and lsmr_tolerance <= 0)):
        return source, {**report, 'reason': 'fit_budget_exhausted'}
    if count < 5 or not edges or proposal.frame_count != count:
        return source, {**report, 'reason': 'insufficient_matching_trajectory'}
    names = list(source.joint_names)
    indices = {name: i for i, name in enumerate(names)}
    if any(name not in indices for edge in edges for name in edge):
        return source, {**report, 'reason': 'missing_chain_joints'}
    # Shared children require a single kinematic parent. Chains must be ordered
    # root outward so their coordinates have an unambiguous owner.
    children = [child for _, child in edges]
    if len(set(children)) != len(children):
        return source, {**report, 'reason': 'conflicting_chain_parents'}
    original = np.array([[frame.joints[name] for name in names] for frame in source.frames])
    target = np.array([[frame.joints[name] for name in names] for frame in proposal.frames])
    times = np.array([frame.time_sec for frame in source.frames])
    dt = np.diff(times)
    if not np.isfinite(original).all() or not np.isfinite(target).all() or not np.isfinite(dt).all() or np.any(dt <= 0):
        return source, {**report, 'reason': 'invalid_trajectory'}
    moved = [indices[name] for name in children]
    root = indices.get('pelvis', indices.get('hips', indices[edges[0][0]]))
    # Pair distances keep fit weights independent of camera/world orientation.
    scale = max(float(np.median(np.max(np.linalg.norm(
        original[:, :, None] - original[:, None, :], axis=-1), axis=(1, 2)))), .01)
    if fit_root_translation:
        moved.append(root)
    weights = np.ones((count, len(moved))) if observation_weights is None else np.asarray(observation_weights, dtype=float)
    if weights.shape != (count, len(moved)) or not np.isfinite(weights).all() or np.any(weights < 0):
        return source, {**report, 'reason': 'invalid_observation_weights'}
    if not np.any(weights):
        return source, {**report, 'reason': 'no_observed_targets'}
    bones = np.stack([original[:, indices[child]] - original[:, indices[parent]] for parent, child in edges], axis=1)
    reference_root = original[:, root:root + 1] if fit_root_translation else None
    relative = original[:, moved] - (reference_root if reference_root is not None else original[:, root:root + 1])

    def derivatives(points):
        velocity = np.diff(points, axis=0) / dt[:, None, None]
        acceleration = np.diff(velocity, axis=0) / ((dt[:-1] + dt[1:]) * .5)[:, None, None]
        jerk = np.diff(acceleration, axis=0) / ((times[3:] - times[:-3]) / 3)[:, None, None]
        return velocity, acceleration, jerk

    before_velocity, before_acceleration, before_jerk = derivatives(relative)
    # Physical rates, independent of frame rate. Existing faster motion is not
    # flattened merely because its reconstructed source exceeds a default.
    speed_limit = np.maximum(np.linalg.norm(before_velocity, axis=-1) * 1.05, scale * .028 * 30)
    acceleration_limit = np.maximum(np.linalg.norm(before_acceleration, axis=-1) * 1.05, scale * .012 * 30**2)
    jerk_limit = np.maximum(np.sqrt(np.mean(before_jerk**2, axis=(0, 2))), scale * 30)
    # The shared discontinuity gate measures local velocity residuals at 30 Hz.
    # Their equivalent jerk is 2 * residual * fps^3. Leave margin below that
    # gate instead of allowing a clip-wide RMS to hide one new sharp event.
    local_jerk_limit = 2 * .008 * scale * 30**3
    pair = [indices[name] for name in rigid_pair] if rigid_pair and all(name in indices for name in rigid_pair) else None
    pair_reference = ([indices[name] for name in rigid_pair_reference]
                      if pair and rigid_pair_reference and all(name in indices for name in rigid_pair_reference)
                      else None)
    pair_distance = float(np.median(np.linalg.norm(original[:, pair[0]] - original[:, pair[1]], axis=-1))) if pair else None
    distance_pairs = [(indices[a], indices[b]) for a, b in rigid_distances if a in indices and b in indices]
    reference_distances = [np.linalg.norm(original[:, a] - original[:, b], axis=-1) for a, b in distance_pairs]
    moved_index = {index: position for position, index in enumerate(moved)}
    observed_segments = []
    for a, b in projection_segments:
        if a not in indices or b not in indices:
            continue
        ai, bi = indices[a], indices[b]
        if ai not in moved_index or bi not in moved_index:
            continue
        vector = target[:, bi, :2] - target[:, ai, :2]
        length = np.linalg.norm(vector, axis=-1)
        span = np.max(np.ptp(target[:, moved, :2], axis=1), axis=-1)
        evidence = np.minimum(weights[:, moved_index[ai]], weights[:, moved_index[bi]])
        evidence = np.sqrt(evidence * (length > span * .07))
        observed_segments.append((ai, bi, vector / np.maximum(length[:, None], 1e-12), evidence))
    bone_width = len(edges) * 3
    width = bone_width + (3 if fit_root_translation else 0)

    def decode(values):
        parameters = values.reshape(count, width)
        rotated = Rotation.from_rotvec(parameters[:, :bone_width].reshape(-1, 3)).apply(
            bones.reshape(-1, 3)
        ).reshape(bones.shape)
        points = original.copy()
        if fit_root_translation:
            points[:, root] += parameters[:, bone_width:]
        for edge_index, (parent, child) in enumerate(edges):
            points[:, indices[child]] = points[:, indices[parent]] + rotated[:, edge_index]
        return points

    best = [float('inf'), np.zeros(count * width)]
    best_terms = {}
    initial_terms = {}
    objective_progress = []
    residual_evaluations = 0
    residual_evaluation_seconds = 0.0
    next_progress_at = 0.0
    # Invariant across evaluations; hoisted out of the hot residual path.
    observation_scale = np.sqrt(weights[..., None])
    pose_scale = scale * .02
    labels = ['pose', 'rotationPrior', 'speed', 'acceleration', 'jerkRms', 'localJerk']
    labels += ((['rigidPair'] if pair else [])
               + (['rigidPairOrientation', 'rigidPairCenter'] if pair_reference else [])
               + ['coreDistance'] * len(distance_pairs)
               + ['projectedDirection'] * len(observed_segments))

    def terms_for_blocks(blocks):
        terms = {}
        for label, block in zip(labels, blocks):
            terms[label] = terms.get(label, 0.) + float(np.sum(block ** 2))
        return terms

    def residual(values, enforce_deadline=True):
        nonlocal residual_evaluations, residual_evaluation_seconds, next_progress_at
        if enforce_deadline and monotonic() - started > timeout_seconds:
            raise TimeoutError('pose_temporal_fit_budget_exhausted')
        evaluation_started = monotonic()
        residual_evaluations += 1
        points = decode(values)
        velocity, acceleration, jerk = derivatives(
            points[:, moved] - (
                reference_root if reference_root is not None else points[:, root:root + 1]
            )
        )
        pose_residual = (points[:, moved] - target[:, moved]) * observation_scale / pose_scale
        if projected_observations:
            # Image observations constrain camera X/Y only. Depth is a weak
            # reconstruction prior, not a fabricated measured 3D target.
            pose_residual[:, :, 2] = .05 * (
                points[:, moved, 2] - original[:, moved, 2]
            ) / pose_scale
        blocks = [pose_residual.ravel(),
                  (.03 * values).ravel(),
                  (100 * np.maximum(_norm(velocity) - speed_limit, 0) / (scale * .03 * 30)).ravel(),
                  (100 * np.maximum(_norm(acceleration) - acceleration_limit, 0) / (scale * .012 * 30**2)).ravel(),
                  (np.maximum(_norm(jerk) - jerk_limit[None, :], 0) / jerk_limit[None, :]).ravel()]
        blocks.append((100 * np.maximum(_norm(jerk) - local_jerk_limit, 0) / local_jerk_limit).ravel())
        if pair:
            blocks.append((10 * (_norm(points[:, pair[0]] - points[:, pair[1]]) - pair_distance)
                           / max(.005, pair_distance * .02)).ravel())
        if pair_reference:
            axis = points[:, pair_reference[1]] - points[:, pair_reference[0]]
            axis /= np.maximum(_norm(axis)[:, None], 1e-9)
            separation = points[:, pair[1]] - points[:, pair[0]]
            center_delta = (points[:, pair[1]] + points[:, pair[0]]
                            - points[:, pair_reference[1]] - points[:, pair_reference[0]]) / 2
            blocks.append((10 * (separation - pair_distance * axis) / pose_scale).ravel())
            blocks.append((10 * np.sum(center_delta * axis, axis=-1) / pose_scale).ravel())
        for (a, b), reference in zip(distance_pairs, reference_distances):
            blocks.append((20 * (_norm(points[:, a] - points[:, b]) - reference) / pose_scale).ravel())
        for a, b, direction, evidence in observed_segments:
            vector = points[:, b, :2] - points[:, a, :2]
            unit = vector / np.maximum(_norm(vector)[:, None], 1e-12)
            blocks.append(((unit - direction) * evidence[:, None] / .2).ravel())
        result = np.concatenate(blocks)
        cost = float(result @ result)
        if not initial_terms:
            initial_terms.update(terms_for_blocks(blocks))
        if cost < best[0]:
            best[:] = [cost, values.copy()]
            best_terms.clear()
            best_terms.update(terms_for_blocks(blocks))
        elapsed = monotonic() - started
        if enforce_deadline and elapsed >= next_progress_at:
            objective_progress.append({'elapsedSeconds': elapsed,
                                       'evaluations': residual_evaluations,
                                       'bestObjective': best[0],
                                       'residualEvaluationSeconds': residual_evaluation_seconds,
                                       'bestObjectiveTerms': dict(best_terms)})
            next_progress_at = elapsed + 10.0
        residual_evaluation_seconds += monotonic() - evaluation_started
        return result

    # A joint depends only on rotations along its own ancestor path. A dense
    # per-frame mask made unrelated limbs share numerical-Jacobian columns,
    # consuming the fit budget on unnecessary residual evaluations.
    parents = {child: (parent, index) for index, (parent, child) in enumerate(edges)}
    def joint_dependency(name):
        mask = np.zeros(width)
        visited = set()
        while name in parents and name not in visited:
            visited.add(name)
            name, edge_index = parents[name]
            mask[edge_index * 3:edge_index * 3 + 3] = 1
        if fit_root_translation and name == names[root]:
            mask[bone_width:] = 1
        return mask
    joint_masks = np.array([joint_dependency(names[index]) for index in moved])
    def dependency(order, spatial):
        temporal = diags([np.ones(count - order)] * (order + 1), range(order + 1), shape=(count - order, count))
        return kron(temporal, spatial, format='csr')

    patterns = [dependency(0, np.repeat(joint_masks, 3, axis=0)), dependency(0, eye(width)),
                dependency(1, joint_masks), dependency(2, joint_masks), dependency(3, joint_masks),
                dependency(3, joint_masks)]
    if pair:
        patterns.append(dependency(0, np.maximum(joint_dependency(names[pair[0]]), joint_dependency(names[pair[1]]))[None, :]))
    if pair_reference:
        mask = np.maximum.reduce([joint_dependency(names[index]) for index in pair + pair_reference])
        patterns.append(dependency(0, np.tile(mask, (3, 1))))
        patterns.append(dependency(0, mask[None, :]))
    for a, b in distance_pairs:
        patterns.append(dependency(0, np.maximum(joint_dependency(names[a]), joint_dependency(names[b]))[None, :]))
    for a, b, _, _ in observed_segments:
        mask = np.maximum(joint_dependency(names[a]), joint_dependency(names[b]))
        patterns.append(dependency(0, np.tile(mask, (2, 1))))
    jacobian_pattern = vstack(patterns, format='csr')
    variable_count = count * width
    # SciPy's default greedy coloring randomizes columns before visiting them.
    # This residual pattern is temporal and frame-major, so natural ordering
    # reuses colors across independent frame/joint blocks more effectively.
    jacobian_groups = _natural_jacobian_column_groups(jacobian_pattern)
    # Preserve the old SciPy seed-0 ordering as a coordinate permutation. This
    # keeps the sparse solve deterministic while allowing the explicit natural
    # coloring above to reduce finite-difference residual evaluations.
    solver_permutation = np.argsort(np.random.RandomState(0).permutation(variable_count))
    inverse_solver_permutation = np.argsort(solver_permutation)
    solver_jacobian_pattern = jacobian_pattern[:, solver_permutation]
    solver_jacobian_groups = jacobian_groups[solver_permutation]
    baseline_residual = residual(np.zeros(count * width), enforce_deadline=False)
    initial_cost = float(baseline_residual @ baseline_residual)
    initial_rotations = []
    for edge_index, (parent, child) in enumerate(edges):
        target_bone = target[:, indices[child]] - target[:, indices[parent]]
        correction = _direction_rotation(target_bone) * _direction_rotation(bones[:, edge_index]).inv()
        quaternions = correction.as_quat()
        observed = np.flatnonzero(weights[:, edge_index] > 0)
        if len(observed):
            for index in np.flatnonzero(weights[:, edge_index] == 0):
                nearest = observed[np.argmin(abs(times[observed] - times[index]))]
                quaternions[index] = quaternions[nearest]
        else:
            quaternions[:] = [0., 0., 0., 1.]
        initial_rotations.append(_smooth_rotations(Rotation.from_quat(quaternions),
                                                   max(1, round(source.fps * .10))).as_rotvec())
    initial = np.stack(initial_rotations, axis=1).ravel()
    if fit_root_translation:
        initial = np.column_stack([initial.reshape(count, bone_width), np.zeros((count, 3))]).ravel()
    # Independent inverse-projected targets can violate coupled core/support
    # constraints badly. Start from the better feasible state instead of
    # spending the whole budget recovering from a worse initialization.
    if projected_observations:
        candidate_residual = residual(initial, enforce_deadline=False)
        if float(candidate_residual @ candidate_residual) > initial_cost:
            initial = np.zeros(count * width)
    last_residual = {'values': None, 'result': None}

    def permuted_residual(values):
        result = residual(values[inverse_solver_permutation])
        last_residual['values'] = values.copy()
        last_residual['result'] = result
        return result

    def jacobian(values):
        baseline = last_residual['result']
        if (last_residual['values'] is None
                or not np.array_equal(last_residual['values'], values)):
            baseline = permuted_residual(values)
        result = approx_derivative(
            permuted_residual,
            values,
            method='2-point',
            f0=baseline,
            sparsity=(solver_jacobian_pattern, solver_jacobian_groups),
        )
        # Inactive inequality penalties and unobserved targets contribute many
        # exact zeros. Keep the dependency pattern for finite differences, but
        # remove numerical zeros before LSMR repeatedly multiplies the matrix.
        result.eliminate_zeros()
        return result

    try:
        tr_options = {'maxiter': int(lsmr_max_iterations)}
        if lsmr_tolerance is not None:
            tr_options.update(atol=float(lsmr_tolerance), btol=float(lsmr_tolerance))
        solved = least_squares(permuted_residual, initial[solver_permutation], jac=jacobian,
                               max_nfev=max_evaluations, ftol=1e-5, xtol=None, gtol=1e-5,
                               tr_options=tr_options, x_scale=x_scale)
        status, evaluations = 'converged' if solved.success else 'evaluation_limit', solved.nfev
    except TimeoutError:
        status, evaluations = 'time_limit', None
    points = decode(best[1])
    residual(best[1], enforce_deadline=False)
    corrected_names = [names[index] for index in moved]
    frames = [MotionFrame(frame.time_sec, {**frame.joints,
               **{name: tuple(float(v) for v in points[i, indices[name]]) for name in corrected_names}})
              for i, frame in enumerate(source.frames)]
    fitted = replace(source, frames=frames)
    finished_elapsed = monotonic() - started
    if (not objective_progress
            or objective_progress[-1]['elapsedSeconds'] < finished_elapsed - 1e-3):
        objective_progress.append({'elapsedSeconds': finished_elapsed,
                                   'evaluations': residual_evaluations,
                                   'bestObjective': best[0],
                                   'residualEvaluationSeconds': residual_evaluation_seconds,
                                   'bestObjectiveTerms': dict(best_terms)})
    report.update(applied=best[0] < initial_cost, reason=status, evaluations=evaluations,
                  elapsedSeconds=finished_elapsed, initialObjective=initial_cost,
                  finalObjective=best[0], correctedJoints=corrected_names, rigidPair=rigid_pair,
                  initialObjectiveTerms=initial_terms, finalObjectiveTerms=dict(best_terms),
                  objectiveProgress=objective_progress,
                  jacobianColorGroups=int(jacobian_groups.max() + 1),
                  jacobianVariableCount=variable_count,
                  lsmrMaxIterations=int(lsmr_max_iterations),
                  lsmrTolerance=lsmr_tolerance,
                  xScale=x_scale,
                  jacobianMethod="scipy_sparse_2_point",
                  residualEvaluationSeconds=residual_evaluation_seconds,
                  residualEvaluationShare=(residual_evaluation_seconds / max(finished_elapsed, 1e-9)),
                  poseTargetRmsBefore=float(np.sqrt(np.mean((original[:, moved] - target[:, moved])**2))),
                  poseTargetRmsAfter=float(np.sqrt(np.mean((points[:, moved] - target[:, moved])**2))))
    if pair:
        report['maximumPairSpacingError'] = float(np.max(abs(
            np.linalg.norm(points[:, pair[0]] - points[:, pair[1]], axis=-1) - pair_distance)))
    return fitted, report


def _direction_rotation(vectors: np.ndarray) -> Rotation:
    """Shortest rotation from the local downward axis to each bone."""
    direction = vectors / np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-12)
    reference = np.broadcast_to([0., -1., 0.], direction.shape)
    cross = np.cross(reference, direction)
    sine = np.linalg.norm(cross, axis=1)
    cosine = np.clip(np.sum(reference * direction, axis=1), -1., 1.)
    axes = cross / np.maximum(sine[:, None], 1e-12)
    axes[(sine < 1e-9) & (cosine < 0)] = [1., 0., 0.]
    return Rotation.from_rotvec(axes * np.arctan2(sine, cosine)[:, None])


def _smooth_rotations(rotations: Rotation, radius: int) -> Rotation:
    # Quaternion means have no +/- pi discontinuity and do not average
    # opposite representations of the same rotation into a zero rotation.
    fitted = []
    for index in range(len(rotations)):
        start, end = max(0, index - radius), min(len(rotations), index + radius + 1)
        offsets = np.arange(start, end) - index
        weights = np.exp(-.5 * (offsets / max(radius / 2., 1.))**2)
        fitted.append(rotations[start:end].mean(weights=weights).as_quat())
    return Rotation.from_quat(fitted)


def fit_chain_rotations(
    source: MotionClip,
    chain: tuple[str, ...],
    *,
    proposal: MotionClip | None = None,
) -> MotionClip:
    """Smooth bone rotations, or a proposed correction to the source motion.

    Reconstruct outward from the unchanged chain root. Every frame retains
    its source bone lengths. The body's moving coordinate frame prevents a
    whole-body turn from being mistaken for articulation noise.
    """
    from .structural_refinement import _body_local_frame

    if source.frame_count < 3 or any(
        name not in frame.joints for frame in source.frames for name in chain
    ):
        return source
    frames = [MotionFrame(frame.time_sec, dict(frame.joints)) for frame in source.frames]
    bases = []
    for frame in source.frames:
        body = _body_local_frame(frame)
        bases.append(np.column_stack([body.right, body.up, body.forward]) if body is not None else np.eye(3))
    bases = np.asarray(bases)
    radius = max(1, round(source.fps * .10))
    for parent, child in zip(chain, chain[1:]):
        original = np.array([np.subtract(frame.joints[child], frame.joints[parent]) for frame in source.frames])
        local = np.einsum('nji,nj->ni', bases, original)
        rotations = _direction_rotation(local)
        if proposal is not None:
            target = np.array([np.subtract(frame.joints[child], frame.joints[parent]) for frame in proposal.frames])
            proposed_rotations = _direction_rotation(np.einsum('nji,nj->ni', bases, target))
            fitted = _smooth_rotations(proposed_rotations * rotations.inv(), radius) * rotations
        else:
            fitted = _smooth_rotations(rotations, radius)
        lengths = np.linalg.norm(original, axis=1)
        directions = np.einsum('nij,nj->ni', bases, fitted.apply(np.tile([0., -1., 0.], (len(frames), 1))))
        for index, frame in enumerate(frames):
            frame.joints[child] = tuple(float(value) for value in
                                       np.asarray(frame.joints[parent]) + directions[index] * lengths[index])
    return replace(source, frames=frames)


_TEMPORAL_BASELINE_CACHE: "OrderedDict[str, dict]" = OrderedDict()
_TEMPORAL_BASELINE_CACHE_LIMIT = 64
_TEMPORAL_BASELINE_CACHE_LOCK = threading.Lock()


def _clip_payload_digest(clip) -> str:
    from .pose_fidelity import _payload_digest
    payload = {'jointNames': clip.joint_names, 'fps': clip.fps, 'frames': [
        {'timeSec': frame.time_sec, 'joints': {name: list(point) for name, point in frame.joints.items()}}
        for frame in clip.frames]}
    return _payload_digest(payload)


def temporal_quality_comparison(before: MotionClip, proposed: MotionClip) -> dict:
    """Protect local failures, not only average jerk, at one physical scale."""
    from .bake_and_rank import (
        compute_bone_length_instability_metrics,
        compute_distal_step_spike_metrics,
        compute_joint_angle_step_metrics,
        skeleton_joint_tracks_and_body_height,
    )
    from .temporal_quality import introduced_joint_spikes

    def metrics(clip, body_height=None, reference=None):
        payload = {'jointNames': clip.joint_names, 'fps': clip.fps, 'frames': [
            {'timeSec': frame.time_sec, 'joints': {name: list(point) for name, point in frame.joints.items()}}
            for frame in clip.frames]}
        if reference is not None:
            for frame, original in zip(payload['frames'], reference.frames):
                frame['sourceJoints'] = {name: list(point) for name, point in original.joints.items()}
        joint_tracks, measured_body_height = skeleton_joint_tracks_and_body_height(
            payload['frames'], payload['jointNames'],
        )
        resolved_body_height = (
            body_height if body_height is not None and body_height > 1e-6
            else measured_body_height
        )
        if resolved_body_height <= 1e-6:
            return {
                'bodyHeight': 0.0,
                'distalStep': {'severe': False, 'score': 1.0},
                'jointAngleStep': {'severe': False, 'score': 1.0},
                'boneLength': {'severe': False, 'score': 1.0},
                'introducedJointSpikes': {'events': [], 'severe': False},
            }
        root_joint = next(
            (name for name in ('pelvis', 'hips', 'root') if name in joint_tracks),
            '',
        )
        result = {
            'bodyHeight': resolved_body_height,
            'distalStep': compute_distal_step_spike_metrics(
                joint_tracks,
                root_joint=root_joint,
                body_height=resolved_body_height,
                fps=float(clip.fps or 30.0),
            ),
            'jointAngleStep': compute_joint_angle_step_metrics(joint_tracks),
            'boneLength': compute_bone_length_instability_metrics(
                joint_tracks, body_height=resolved_body_height,
            ),
        }
        if reference is not None:
            result['introducedJointSpikes'] = introduced_joint_spikes(payload)
        return result

    # The refinement chain compares every proposal against the same baseline
    # clip; the kinematic plausibility pass is the second dominant repeat cost.
    baseline = None
    try:
        baseline_key = _clip_payload_digest(before)
        with _TEMPORAL_BASELINE_CACHE_LOCK:
            cached_baseline = _TEMPORAL_BASELINE_CACHE.get(baseline_key)
            if cached_baseline is not None:
                _TEMPORAL_BASELINE_CACHE.move_to_end(baseline_key)
                baseline = copy.deepcopy(cached_baseline)
    except (TypeError, ValueError):
        baseline_key = None
    if baseline is None:
        baseline = metrics(before)
        if baseline_key is not None:
            with _TEMPORAL_BASELINE_CACHE_LOCK:
                _TEMPORAL_BASELINE_CACHE[baseline_key] = copy.deepcopy(baseline)
                while len(_TEMPORAL_BASELINE_CACHE) > _TEMPORAL_BASELINE_CACHE_LIMIT:
                    _TEMPORAL_BASELINE_CACHE.popitem(last=False)
    candidate = metrics(proposed, baseline.get('bodyHeight'), before)
    degraded = [name for name in ('distalStep', 'jointAngleStep', 'boneLength')
                if candidate[name].get('severe')
                and candidate[name].get('score', 1.) < baseline[name].get('score', 1.) - 1e-6]
    introduced = candidate['introducedJointSpikes']
    remaining_events = []
    radius = max(1, round(before.fps * .10))
    for event in introduced.get('events', []):
        # Smoothing an existing spike distributes a smaller correction over
        # its neighboring frames. Compare the same fitting neighborhood, not
        # just the previously stationary neighbor receiving that correction.
        index, name = event['frameIndex'], event['joint']
        residuals = []
        for center in range(max(1, index - radius), min(before.frame_count - 1, index + radius + 1)):
            group = before.frames[center - 1:center + 2]
            if any(name not in frame.joints or 'pelvis' not in frame.joints for frame in group):
                continue
            points = [np.asarray(frame.joints[name]) - frame.joints['pelvis'] for frame in group]
            duration = group[2].time_sec - group[0].time_sec
            alpha = (group[1].time_sec - group[0].time_sec) / duration if duration > 0 else .5
            residuals.append(float(np.linalg.norm(points[1] - ((1 - alpha) * points[0] + alpha * points[2]))))
        if event['after'] > max(residuals, default=0.) + 1e-9:
            remaining_events.append(event)
    spike_comparison = {
        'redistributedExistingSpikeCount': len(introduced.get('events', [])) - len(remaining_events),
        'events': remaining_events,
        'severe': bool(remaining_events),
    }
    if remaining_events:
        degraded.append('introducedJointSpikes')
    return {'passed': not degraded, 'degradedCategories': degraded, 'before': baseline,
            'proposed': candidate, 'introducedSpikeComparison': spike_comparison}
