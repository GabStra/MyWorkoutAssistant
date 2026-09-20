"""Exercise-independent, bounded sequence stabilization in skeletal coordinates.

No exercise names or preferred planes: smooth trajectories are preserved
while rapid variation is attenuated regardless of amplitude or coordination. The proposed
trajectory is projected jointly back to bones/contacts and independently checked.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from time import monotonic

import numpy as np
from scipy.optimize import least_squares
from scipy.signal import butter, sosfiltfilt
from scipy.sparse import csr_matrix, diags, eye, kron, vstack

from .contact_constraints import contact_frame_bounds, is_stationary_contact, motion_support_contacts
from .physical_validation import ARTICULATIONS, angles, body_bones, body_scale, validate_physical_motion
from .temporal_quality import body_orientation_axes, refresh_motion_bounds, transport_corrected_bone_sides


def unit(values):
    return values / np.maximum(np.linalg.norm(values, axis=-1, keepdims=True), 1e-12)


def frame_basis(up, lateral):
    up = unit(up)
    side = lateral - up * np.sum(lateral * up, axis=-1, keepdims=True)
    degenerate = np.linalg.norm(side, axis=-1) < 1e-6
    if degenerate.any():
        fallback = np.eye(3)[np.argmin(np.abs(up[degenerate]), axis=-1)]
        side[degenerate] = fallback - up[degenerate] * np.sum(fallback * up[degenerate], axis=-1, keepdims=True)
    side = unit(side)
    return np.stack([side, up, unit(np.cross(side, up))], axis=-1)


class SkeletalCoordinates:
    """Parent-frame bone directions, body orientation, and independent root travel."""

    def __init__(self, points, names):
        from .smpl_joint_names import SMPL_JOINT_NAMES, SMPL_JOINT_PARENTS
        self.names = names
        self.root = names.index('pelvis') if 'pelvis' in names else 0
        self.edges = [(names.index(SMPL_JOINT_NAMES[parent]), names.index(child))
                      for child, parent in zip(SMPL_JOINT_NAMES, SMPL_JOINT_PARENTS)
                      if parent >= 0 and child in names and SMPL_JOINT_NAMES[parent] in names]
        self.parents = {b: a for a, b in self.edges}
        self.lengths = [np.linalg.norm(points[:, b]-points[:, a], axis=1) for a, b in self.edges]
        self.scale = body_scale(points, names)
        axes = body_orientation_axes(points, names)
        self.basis = (frame_basis(axes[:, 1], axes[:, 0]) if axes.shape[1]
                      else np.tile(np.eye(3), (len(points), 1, 1)))
        features = [points[:, self.root] / self.scale, self.basis[:, :, 0], self.basis[:, :, 1]]
        for a, b in self.edges:
            basis = self.parent_basis(points, a, self.basis)
            features.append(np.einsum('fji,fj->fi', basis, unit(points[:, b]-points[:, a])))
        self.features = np.stack(features, axis=1)

    def parent_basis(self, points, joint, body_basis):
        parent = self.parents.get(joint)
        if parent is None:
            return body_basis
        # A frame aligned by rotating body-up onto a downward bone has an
        # antipodal singularity. Follow the incoming bone with a continuous
        # projected side instead, using temporal transport near alignment.
        incoming = unit(points[:, joint]-points[:, parent])
        sides = np.empty_like(incoming)
        for i, up in enumerate(incoming):
            desired = body_basis[i, :, 0]-up*np.dot(body_basis[i, :, 0], up)
            reliability = np.linalg.norm(desired)
            fallback = body_basis[i, :, 2]-up*np.dot(body_basis[i, :, 2], up)
            previous = sides[i-1]-up*np.dot(sides[i-1], up) if i else fallback
            if np.linalg.norm(previous) < 1e-8:
                previous = fallback
            previous = unit(previous)
            desired = unit(desired) if reliability > 1e-8 else previous
            if i and np.dot(desired, previous) < 0:
                desired = -desired
            weight = np.clip((reliability-.1)/.3, 0., 1.)
            weight = weight*weight*(3.-2.*weight)
            sides[i] = unit(desired*weight+previous*(1.-weight))
        return frame_basis(incoming, sides)

    def decode(self, features, original):
        result = original.copy()
        result[:, self.root] = features[:, 0] * self.scale
        basis = frame_basis(features[:, 2], features[:, 1])
        for index, ((a, b), length) in enumerate(zip(self.edges, self.lengths)):
            parent = self.parent_basis(result, a, basis)
            direction = np.einsum('fij,fj->fi', parent, unit(features[:, index+3]))
            result[:, b] = result[:, a] + direction * length[:, None]
        return result


def denoise_features(features, fps):
    """Remove rapid variation, including coherent, periodic and large spikes.

    A zero-phase low-pass defines the desired animation bandwidth in seconds.
    Source extrema are not restored: a one-frame spike is not motion range.
    """
    count = len(features)
    if count < 7:
        return features.copy(), {'changed': False, 'reason': 'insufficient_temporal_context'}
    cutoff = min(3., fps*.2)
    sections = butter(4, cutoff, fs=fps, output='sos')
    result = sosfiltfilt(sections, features, axis=0, padlen=min(count-1, 15))
    correction = features-result
    return result, {'changed': bool(np.max(abs(correction)) > 1e-7),
                    'cutoffHz': cutoff, 'filterOrder': 4, 'zeroPhase': True,
                    'maximumFeatureCorrection': float(np.max(np.linalg.norm(correction, axis=-1))),
                    'policy': 'animation_bandwidth_v3'}


def contact_mask(payload, names, count):
    pinned = np.zeros((count, len(names)), dtype=bool)
    for contact in motion_support_contacts(payload.get('sourceFootSupportEvidence')):
        if contact.get('contactState') == 'heel_only':
            # Heel-only is not a pin in this shoe model. Skip it so other
            # observed plants can still constrain the retained interval.
            continue
        if not is_stationary_contact(contact):
            continue
        name = str(contact.get('jointName', ''))
        if name not in names:
            continue
        start, end = contact_frame_bounds(contact, count)
        pinned[start:end+1, names.index(name)] = True
        if contact.get('contactState') == 'full_sole' and name.endswith(('_ankle', '_foot')):
            for part in ('ankle', 'foot'):
                sibling = name.split('_')[0]+'_'+part
                if sibling in names:
                    pinned[start:end+1, names.index(sibling)] = True
    return pinned


def pose_digest(payload):
    contents = {'fps': payload.get('fps'), 'jointNames': payload.get('jointNames'),
                'frames': [{k: f.get(k) for k in ('timeSec', 'joints', 'sourceJoints', 'cameraPlacementReferenceJoints', 'controlledSourceJoints', 'controlledArticulationReferenceJoints', 'correctedAnatomicalReferenceJoints', 'supportCorrectedReferenceJoints', 'supportContactReferenceJoints', 'supportAlignmentReferenceJoints')} for f in payload.get('frames', [])],
                'supports': payload.get('sourceFootSupportEvidence'), 'floor': payload.get('renderFloorY'),
                'fixedRig': payload.get('fixedRig'), 'loop': payload.get('loop')}
    if 'anatomicalSourceRepair' in payload:
        contents['anatomicalSourceRepair'] = payload['anatomicalSourceRepair']
    if 'equipmentConstraints' in payload:
        contents['equipmentConstraints'] = payload['equipmentConstraints']
    if 'scenePlacement' in payload:
        contents['scenePlacement'] = payload['scenePlacement']
    return hashlib.sha256(json.dumps(contents, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def stabilize_exported_sequence(payload, *, max_evaluations=35, timeout_seconds=30.):
    """Return an atomic candidate or the original payload, never a partial repair."""
    started = monotonic()
    frames = payload.get('frames') or []
    report = {'applied': False, 'strategy': 'skeletal_sequence_stabilization_v3'}
    previous = payload.get('sequenceStabilization') or {}
    if previous.get('strategy') == report['strategy'] and previous.get('outputPoseDigest') == pose_digest(payload):
        return payload, {**previous, 'reused': True}
    if len(frames) < 7 or any(f.get('syntheticLoopBridge') for f in frames):
        return payload, {**report, 'reason': 'insufficient_contiguous_source_frames'}
    if (payload.get('postBakeForefootContactConstraint') or {}).get('requiresReconstruction'):
        return payload, {**report, 'reason': 'upstream_repair_unresolved'}
    times = np.asarray([f.get('timeSec', np.nan) for f in frames], dtype=float)
    fps = float(payload.get('fps', 30.))
    if not np.isfinite(fps) or fps <= 0:
        return payload, {**report, 'reason': 'invalid_sampling_rate'}
    if not np.isfinite(times).all() or np.max(abs(np.diff(times)-1/fps)) > .05/fps:
        return payload, {**report, 'reason': 'irregular_sampling_requires_resampling'}
    names = [n for n in payload.get('jointNames', []) if all(n in f.get('joints', {}) for f in frames)]
    if not names:
        return payload, {**report, 'reason': 'no_joint_tracks'}
    points = np.asarray([[f['joints'][n] for n in names] for f in frames], dtype=float)
    reference = (np.asarray([[f['sourceJoints'][n] for n in names] for f in frames], dtype=float)
                 if all(all(n in (f.get('sourceJoints') or {}) for n in names) for f in frames) else points)
    before = validate_physical_motion(points, names, reference=reference, fps=fps)
    if not before['passed']:
        return payload, {**report, 'reason': 'upstream_anatomy_unresolved'}
    pinned = contact_mask(payload, names, len(frames))
    if pinned is None:
        return payload, {**report, 'reason': 'unrepresented_heel_contact'}
    coordinates = SkeletalCoordinates(points, names)
    filtered, evidence = denoise_features(coordinates.features, fps)
    report['evidence'] = evidence
    report['featureChannels'] = ['root_translation', 'body_lateral_axis', 'body_up_axis'] + [names[a]+'->'+names[b] for a, b in coordinates.edges]
    if not evidence['changed']:
        return payload, {**report, 'reason': 'no_supported_noise_correction'}
    target, _ = denoise_features(points, fps)
    target[pinned] = points[pinned]
    free = np.repeat(~pinned[:, :, None], 3, axis=2).ravel()
    if not free.any():
        return payload, {**report, 'reason': 'all_coordinates_supported'}
    count, joints, _ = points.shape
    bones = list(dict.fromkeys([*body_bones(names), *coordinates.edges]))
    if not bones:
        return payload, {**report, 'reason': 'unsupported_skeleton_topology'}
    first, last = np.asarray(bones).T
    lengths = np.linalg.norm(points[:, first]-points[:, last], axis=-1)
    scale = coordinates.scale
    articulations = [(label, [names.index(n) for n in (a, b, c)], tolerance)
                     for label, a, b, c, tolerance in ARTICULATIONS if all(n in names for n in (a, b, c))]
    if articulations:
        source_angles = np.stack([angles(*(reference[:, i] for i in cols)) for _, cols, _ in articulations], axis=1)
        tolerances = np.deg2rad([tol-.5 for _, _, tol in articulations])
        low, high = source_angles-tolerances, source_angles+tolerances
        for column, (label, _, _) in enumerate(articulations):
            if label.endswith(('_knee', '_elbow')):
                low[:, column] = np.maximum(low[:, column], np.maximum(source_angles[:, column]-np.deg2rad(9.9), source_angles[:, column].min()-np.deg2rad(.9)))
                high[:, column] = np.minimum(high[:, column], np.minimum(source_angles[:, column]+np.deg2rad(9.9), source_angles[:, column].max()+np.deg2rad(.9)))
            if label.endswith('_ankle'):
                low[:, column] = np.maximum(low[:, column], np.deg2rad(35.1))
                high[:, column] = np.minimum(high[:, column], np.deg2rad(164.9))
    def expand(values):
        result = points.copy().ravel()
        result[free] = values
        return result.reshape(points.shape)
    class Deadline(Exception):
        pass
    def residual(values):
        if monotonic()-started > timeout_seconds:
            raise Deadline
        candidate = expand(values)
        angle_penalty = np.empty((count, 0))
        if articulations:
            current_angles = np.stack([angles(*(candidate[:, i] for i in cols)) for _, cols, _ in articulations], axis=1)
            angle_penalty = 300.*(np.minimum(current_angles-low, 0.)+np.maximum(current_angles-high, 0.))
        per_frame = np.concatenate([
            ((candidate-target)/scale).reshape(count, -1),
            1000.*(np.linalg.norm(candidate[:, first]-candidate[:, last], axis=-1)-lengths)/scale,
            angle_penalty,
        ], axis=1)
        # Fit the denoised trajectory. Penalizing changes from the noisy input
        # here would reward retaining exactly the oscillations being removed.
        correction = np.diff((candidate-target)/scale, n=2, axis=0)*3.
        return np.r_[per_frame.ravel(), correction.ravel()]
    bone_dependencies = np.zeros((len(bones), joints*3))
    for row, (a, b) in enumerate(bones):
        bone_dependencies[row, a*3:a*3+3] = 1.
        bone_dependencies[row, b*3:b*3+3] = 1.
    angle_dependencies = np.zeros((len(articulations), joints*3))
    for row, (_, cols, _) in enumerate(articulations):
        for joint in cols:
            angle_dependencies[row, joint*3:joint*3+3] = 1.
    frame_dependencies = vstack([eye(joints*3), csr_matrix(bone_dependencies), csr_matrix(angle_dependencies)], format='csr')
    pattern = vstack([
        kron(eye(count), frame_dependencies),
        kron(diags([np.ones(count-2)]*3, [0, 1, 2], shape=(count-2, count)), eye(joints*3)),
    ], format='csr')[:, free]
    try:
        initial = points.ravel()[free]+.25*np.clip(target.ravel()[free]-points.ravel()[free], -.014*scale, .014*scale)
        fit = least_squares(residual, initial, jac_sparsity=pattern,
                            bounds=(points.ravel()[free]-.015*scale, points.ravel()[free]+.015*scale),
                            max_nfev=max_evaluations, ftol=1e-5, xtol=1e-7, gtol=1e-7,
                            x_scale='jac', diff_step=1e-5,
                            tr_options={'maxiter': 300, 'atol': 1e-7, 'btol': 1e-7})
    except Deadline:
        return payload, {**report, 'reason': 'bounded_stabilization_timeout'}
    result = expand(fit.x)
    physical = validate_physical_motion(result, names, reference=reference, fps=fps)
    length_error = float(np.max(abs(np.linalg.norm(result[:, first]-result[:, last], axis=-1)-lengths)))
    # Preserve the cleaned trajectory range, not raw single-frame extrema.
    # Rapid motion is deliberately removed by the animation bandwidth policy.
    observed = coordinates.features
    actual = SkeletalCoordinates(result, names).features
    span = np.linalg.norm(np.ptp(filtered, axis=0), axis=-1)
    final_span = np.linalg.norm(np.ptp(actual, axis=0), axis=-1)
    protected = span > np.deg2rad(5.)
    protected[0] = span[0] > .03
    range_preserved = bool(np.all(final_span[protected] >= .95*span[protected]))
    floor = payload.get('renderFloorY')
    floor_ok = floor is None or result[:, :, 1].min() >= min(float(floor)-.002, points[:, :, 1].min()-.0001)
    accepted = physical['passed'] and length_error <= .002 and range_preserved and floor_ok
    proposed_denoised, _ = denoise_features(result, fps)
    original_denoised, _ = denoise_features(points, fps)
    noise_before = float(np.sqrt(np.mean(((original_denoised-points)/scale)**2)))
    noise_after = float(np.sqrt(np.mean(((proposed_denoised-result)/scale)**2)))
    noise_improved = noise_after < noise_before*.999
    accepted = accepted and noise_improved
    report.update({'applied': bool(accepted), 'reason': 'validated_sequence_stabilization' if accepted else 'projection_failed_preservation_checks',
                   'maximumBoneLengthErrorMeters': length_error, 'rangePreserved': range_preserved,
                   'maximumCorrectionMeters': float(np.max(np.linalg.norm(result-points, axis=-1))),
                   'physicalReasons': physical['reasons'], 'evaluations': int(fit.nfev),
                   'physicalEvents': physical.get('events', [])[:8],
                   'targetRmsBeforeMeters': float(np.sqrt(np.mean((points-target)**2))),
                   'targetRmsAfterMeters': float(np.sqrt(np.mean((result-target)**2))),
                   'solverOptimality': float(fit.optimality),
                   'residualNoiseBefore': noise_before, 'residualNoiseAfter': noise_after,
                   'noiseImproved': noise_improved,
                   'elapsedSeconds': monotonic()-started})
    if not accepted:
        return payload, report
    candidate = deepcopy(payload)
    for frame, values in zip(candidate['frames'], result):
        frame['joints'].update({n: p.tolist() for n, p in zip(names, values)})
    transport_corrected_bone_sides(payload['frames'], candidate)
    refresh_motion_bounds(candidate)
    from .bake_and_rank import compute_kinematic_plausibility_metrics_from_payload
    final_metrics = compute_kinematic_plausibility_metrics_from_payload(candidate)
    if final_metrics['severeArtifact']:
        return payload, {**report, 'applied': False, 'reason': 'final_kinematic_gate_rejected',
                         'artifactReasons': final_metrics['artifactReasons']}
    report['outputPoseDigest'] = pose_digest(candidate)
    return candidate, report
