"""Temporal fitting in rotation space without shortening articulated bones."""

from __future__ import annotations

from dataclasses import replace
from time import monotonic

import numpy as np
from scipy.spatial.transform import Rotation

from .models import MotionClip, MotionFrame


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
    if timeout_seconds <= 0 or max_evaluations < 1:
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
        rotated = Rotation.from_rotvec(parameters[:, :bone_width].reshape(-1, 3)).apply(bones.reshape(-1, 3)).reshape(bones.shape)
        points = original.copy()
        if fit_root_translation:
            points[:, root] += parameters[:, bone_width:]
        for edge_index, (parent, child) in enumerate(edges):
            points[:, indices[child]] = points[:, indices[parent]] + rotated[:, edge_index]
        return points

    best = [float('inf'), np.zeros(count * width)]
    objective_terms = {}
    def residual(values, enforce_deadline=True):
        if enforce_deadline and monotonic() - started > timeout_seconds:
            raise TimeoutError('pose_temporal_fit_budget_exhausted')
        points = decode(values)
        velocity, acceleration, jerk = derivatives(points[:, moved] - (
            reference_root if reference_root is not None else points[:, root:root + 1]))
        pose_residual = (points[:, moved] - target[:, moved]) * np.sqrt(weights[..., None]) / (scale * .02)
        if projected_observations:
            # Image observations constrain camera X/Y only. Depth is a weak
            # reconstruction prior, not a fabricated measured 3D target.
            pose_residual[:, :, 2] = .05 * (points[:, moved, 2] - original[:, moved, 2]) / (scale * .02)
        blocks = [pose_residual.ravel(),
                  (.03 * values).ravel(),
                  (100 * np.maximum(np.linalg.norm(velocity, axis=-1) - speed_limit, 0) / (scale * .03 * 30)).ravel(),
                  (100 * np.maximum(np.linalg.norm(acceleration, axis=-1) - acceleration_limit, 0) / (scale * .012 * 30**2)).ravel(),
                  (np.maximum(np.linalg.norm(jerk, axis=-1) - jerk_limit[None, :], 0) / jerk_limit[None, :]).ravel()]
        blocks.append((100 * np.maximum(np.linalg.norm(jerk, axis=-1)-local_jerk_limit, 0)/local_jerk_limit).ravel())
        if pair:
            blocks.append((10 * (np.linalg.norm(points[:, pair[0]] - points[:, pair[1]], axis=-1) - pair_distance) / max(.005, pair_distance * .02)).ravel())
        if pair_reference:
            axis = points[:, pair_reference[1]] - points[:, pair_reference[0]]
            axis /= np.maximum(np.linalg.norm(axis, axis=-1)[:, None], 1e-9)
            separation = points[:, pair[1]] - points[:, pair[0]]
            center_delta = (points[:, pair[1]] + points[:, pair[0]]
                            - points[:, pair_reference[1]] - points[:, pair_reference[0]]) / 2
            blocks.append((10 * (separation - pair_distance * axis) / (scale * .02)).ravel())
            blocks.append((10 * np.sum(center_delta * axis, axis=-1) / (scale * .02)).ravel())
        for (a, b), reference in zip(distance_pairs, reference_distances):
            blocks.append((20 * (np.linalg.norm(points[:, a] - points[:, b], axis=-1) - reference) / (scale * .02)).ravel())
        for a, b, direction, evidence in observed_segments:
            vector = points[:, b, :2] - points[:, a, :2]
            unit = vector / np.maximum(np.linalg.norm(vector, axis=-1, keepdims=True), 1e-12)
            blocks.append(((unit - direction) * evidence[:, None] / .2).ravel())
        labels = ['pose', 'rotationPrior', 'speed', 'acceleration', 'jerkRms', 'localJerk']
        labels += ((['rigidPair'] if pair else [])
                   + (['rigidPairOrientation', 'rigidPairCenter'] if pair_reference else [])
                   + ['coreDistance'] * len(distance_pairs) + ['projectedDirection'] * len(observed_segments))
        objective_terms.clear()
        for label, block in zip(labels, blocks):
            objective_terms[label] = objective_terms.get(label, 0.) + float(np.sum(block ** 2))
        result = np.concatenate(blocks)
        cost = float(result @ result)
        if cost < best[0]:
            best[:] = [cost, values.copy()]
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
    baseline_residual = residual(np.zeros(count * width), enforce_deadline=False)
    initial_cost = float(baseline_residual @ baseline_residual)
    initial_terms = dict(objective_terms)
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
    try:
        solved = least_squares(residual, initial, jac_sparsity=vstack(patterns, format='csr'),
                               max_nfev=max_evaluations, ftol=1e-5, xtol=None, gtol=1e-5,
                               tr_options={'maxiter': 100})
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
    report.update(applied=best[0] < initial_cost, reason=status, evaluations=evaluations,
                  elapsedSeconds=monotonic() - started, initialObjective=initial_cost,
                  finalObjective=best[0], correctedJoints=corrected_names, rigidPair=rigid_pair,
                  initialObjectiveTerms=initial_terms, finalObjectiveTerms=dict(objective_terms),
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


def temporal_quality_comparison(before: MotionClip, proposed: MotionClip) -> dict:
    """Protect local failures, not only average jerk, at one physical scale."""
    from .bake_and_rank import compute_kinematic_plausibility_metrics_from_payload

    def metrics(clip, body_height=None, reference=None):
        payload = {'jointNames': clip.joint_names, 'fps': clip.fps, 'frames': [
            {'timeSec': frame.time_sec, 'joints': {name: list(point) for name, point in frame.joints.items()}}
            for frame in clip.frames]}
        if reference is not None:
            for frame, original in zip(payload['frames'], reference.frames):
                frame['sourceJoints'] = {name: list(point) for name, point in original.joints.items()}
        return compute_kinematic_plausibility_metrics_from_payload(payload, comparison_body_height=body_height)

    baseline = metrics(before)
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
