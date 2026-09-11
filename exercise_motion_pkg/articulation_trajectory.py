"""Temporal fitting in rotation space without shortening articulated bones."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
from scipy.spatial.transform import Rotation

from .models import MotionClip, MotionFrame


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
