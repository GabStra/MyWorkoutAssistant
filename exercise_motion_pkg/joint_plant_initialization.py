"""Bounded common-root and closed-chain initialization for observed foot plants."""
from __future__ import annotations

from time import monotonic

import numpy as np
from scipy.optimize import minimize
from scipy.sparse import diags, eye, lil_matrix
from scipy.sparse.linalg import spsolve

from .contact_heel_repair import (
    _EPS, _INTERIOR_MARGIN_DEGREES, _ROOT_LIMIT_METERS,
    _encode_root_adjusted_pose, _frame_state, _unit,
)
from .foot_kinematics import _source_knee_poles
from .physical_validation import ARTICULATIONS, angles
from .sequence_stabilization import frame_basis
from .temporal_quality import body_orientation_axes

_ROOT_COST_WEIGHT = 1e-3


def contact_conditioned_articulation_reference(reference, pinned, targets, names,
                                               evidence, frame_times):
    """Replace reconstructed foot pitch only on observed, mapped full-sole pins.

    The source knee and ankle remain immutable. On a trusted full-sole sample,
    only the foot vector is taken from the physical contact target; unknown,
    released, partial-contact, and out-of-source-clock rows keep the raw source
    articulation.
    """
    source = np.asarray(reference, dtype=float)
    pins = np.asarray(pinned, dtype=bool)
    contacts = np.asarray(targets, dtype=float)
    if (source.ndim != 3 or source.shape != contacts.shape
            or pins.shape != source.shape[:2] or source.shape[1:] != (len(names), 3)):
        raise ValueError('incompatible contact-conditioned articulation inputs')
    conditioned = source.copy()
    masks, observed_masks = {}, {}
    report = {}
    patch = (evidence or {}).get('footPatchEvidence') or {}
    feet = patch.get('feet') or {}
    if patch.get('available') is not True:
        return conditioned, masks, observed_masks, {
            'available': False, 'reason': 'foot_patch_unavailable'}
    from .contact_constraints import mapped_foot_patch_state_indices
    mapped = np.asarray(
        mapped_foot_patch_state_indices(evidence, frame_times, len(source)), dtype=int)
    indices = mapped
    for side in ('left', 'right'):
        ankle_name, toe_name = f'{side}_ankle', f'{side}_foot'
        foot = feet.get(side)
        states = foot.get('states') if isinstance(foot, dict) else None
        if (ankle_name not in names or toe_name not in names
                or not isinstance(states, list)):
            continue
        if indices.shape != (len(source),):
            continue
        full_sole = np.zeros(len(source), dtype=bool)
        valid = (indices >= 0) & (indices < len(states))
        full_sole[valid] = np.asarray([
            str(states[index]).casefold() == 'full_sole' for index in indices[valid]
        ], dtype=bool)
        ankle_i, toe_i = names.index(ankle_name), names.index(toe_name)
        active = full_sole & pins[:, ankle_i] & pins[:, toe_i]
        if not np.any(valid):
            report[side] = {
                'conditionedFrameCount': 0,
                'mappedFrameCount': 0,
                'mappedFullSoleFrameCount': 0,
                'unmappedFrameCount': int(len(indices)),
                'reason': 'source_patch_clock_unresolved',
            }
            continue
        observed_masks[side] = valid
        masks[side] = active
        if not np.any(active):
            report[side] = {
                'conditionedFrameCount': 0,
                'mappedFrameCount': int(valid.sum()),
                'mappedFullSoleFrameCount': int(full_sole.sum()),
                'unmappedFrameCount': int(np.count_nonzero(indices < 0)),
            }
            continue
        source_ankle = source[active, ankle_i]
        target_vector = contacts[active, toe_i] - contacts[active, ankle_i]
        conditioned[active, toe_i] = source_ankle + target_vector
        report[side] = {
            'conditionedFrameCount': int(active.sum()),
            'mappedFrameCount': int(valid.sum()),
            'mappedFullSoleFrameCount': int(full_sole.sum()),
            'unmappedFrameCount': int(np.count_nonzero(indices < 0)),
        }
    return conditioned, masks, observed_masks, {
        'available': bool(masks), 'reference': 'source_shin_with_observed_full_sole_foot_vector',
        'sides': report,
    }


def _angle_delta(a, b):
    return np.arctan2(np.sin(a - b), np.cos(a - b))


def _foot_pose_report(source, target):
    source = np.asarray(source, dtype=float)
    target = np.asarray(target, dtype=float)
    def heading_pitch(vector):
        return (np.arctan2(vector[..., 0], vector[..., 2]),
                np.arctan2(vector[..., 1], np.linalg.norm(vector[..., [0, 2]], axis=-1)))
    source_heading, source_pitch = heading_pitch(source)
    target_heading, target_pitch = heading_pitch(target)
    return {
        'sourceHeadingDegrees': np.rad2deg(source_heading),
        'targetHeadingDegrees': np.rad2deg(target_heading),
        'sourcePitchDegrees': np.rad2deg(source_pitch),
        'targetPitchDegrees': np.rad2deg(target_pitch),
        'headingDeltaDegrees': np.rad2deg(_angle_delta(target_heading, source_heading)),
        'pitchDeltaDegrees': np.rad2deg(target_pitch - source_pitch),
    }


def source_conditioned_foot_direction_reference(
        reference, pinned, names, desired_world_foot_directions,
        pitch_trajectory_mask_by_side):
    """Carry source foot geometry on mapped trajectories without pinning it."""
    source = np.asarray(reference, dtype=float)
    pins = np.asarray(pinned, dtype=bool)
    directions = np.asarray(desired_world_foot_directions, dtype=float)
    if (source.ndim != 3 or source.shape[1:] != (len(names), 3)
            or pins.shape != source.shape[:2]
            or directions.shape != (len(source), 2, 3)):
        raise ValueError('incompatible source foot direction reference inputs')
    conditioned = source.copy()
    counts = {}
    for side_index, side in enumerate(('left', 'right')):
        ankle_name, toe_name = f'{side}_ankle', f'{side}_foot'
        if ankle_name not in names or toe_name not in names:
            counts[side] = 0
            continue
        ankle_i, toe_i = names.index(ankle_name), names.index(toe_name)
        trajectory = np.asarray(
            (pitch_trajectory_mask_by_side or {}).get(side, np.zeros(len(source))),
            dtype=bool)
        if trajectory.shape != (len(source),):
            raise ValueError(f'{side} pitch trajectory mask must have shape (frames,)')
        rows = trajectory
        lengths = np.linalg.norm(directions[:, side_index], axis=1)
        if np.any(rows & (~np.isfinite(lengths) | (lengths <= _EPS))):
            raise ValueError(f'{side} source foot direction is invalid on its trajectory')
        source_length = float(np.linalg.norm(source[0, toe_i] - source[0, ankle_i]))
        if np.any(rows) and source_length <= _EPS:
            raise ValueError(f'{side} source foot length is unavailable')
        unit_directions = directions[:, side_index] / np.maximum(lengths[:, None], _EPS)
        conditioned[rows, toe_i] = (
            conditioned[rows, ankle_i] + unit_directions[rows] * source_length)
        counts[side] = int(rows.sum())
    return conditioned, counts


def _make_specs(names, points, pinned, targets, reference, *,
                desired_world_foot_directions=None, pitch_authority_mask_by_side=None,
                pitch_trajectory_mask_by_side=None):
    index = {name: i for i, name in enumerate(names)}
    specs, preflight = [], {}
    directions = (None if desired_world_foot_directions is None else
                  np.asarray(desired_world_foot_directions, dtype=float))
    if directions is not None and directions.shape != (len(points), 2, 3):
        raise ValueError('desired foot directions must have shape (frames, 2, 3)')
    root_seed_sum = np.zeros((len(points), 3), dtype=float)
    root_seed_count = np.zeros(len(points), dtype=float)
    for side_index, side in enumerate(('left', 'right')):
        labels = [f'{side}_{part}' for part in ('hip', 'knee', 'ankle', 'foot')]
        if any(name not in index for name in labels):
            continue
        hip_i, knee_i, ankle_i, toe_i = (index[name] for name in labels)
        ankle_pin, toe_pin = pinned[:, ankle_i], pinned[:, toe_i]
        owned = ankle_pin | toe_pin
        if not np.any(owned):
            continue
        source_vector = reference[:, toe_i] - reference[:, ankle_i]
        trajectory = np.zeros(len(points), dtype=bool)
        if directions is not None:
            authority = np.asarray(
                (pitch_authority_mask_by_side or {}).get(side, np.zeros(len(points))),
                dtype=bool).copy()
            trajectory_source = (pitch_trajectory_mask_by_side
                                 if pitch_trajectory_mask_by_side is not None
                                 else pitch_authority_mask_by_side)
            trajectory = np.asarray(
                (trajectory_source or {}).get(side, authority), dtype=bool).copy()
            if authority.shape != (len(points),) or trajectory.shape != (len(points),):
                raise ValueError(f'{side} foot direction authority must have shape (frames,)')
            if np.any(authority & ~trajectory):
                raise ValueError(f'{side} measured pitch authority is outside its trajectory')
            # Geometry may carry a measured foot-direction trajectory through
            # an unpinned interval. The trajectory mask owns this reference;
            # endpoint pins still alone control contact targets below.
            direction_rows = trajectory
            lengths = np.linalg.norm(directions[:, side_index], axis=1)
            if np.any(direction_rows & (~np.isfinite(lengths) | (lengths <= _EPS))):
                raise ValueError(f'{side} authoritative foot direction is invalid')
            direction = directions[:, side_index] / np.maximum(lengths[:, None], _EPS)
            source_vector[direction_rows] = direction[direction_rows] * np.linalg.norm(
                source_vector[0])
        target_ankle = points[:, ankle_i].copy()
        target_toe = points[:, toe_i].copy()
        both = ankle_pin & toe_pin
        ankle_only = ankle_pin & ~toe_pin
        toe_only = toe_pin & ~ankle_pin
        target_ankle[ankle_pin] = targets[ankle_pin, ankle_i]
        target_toe[toe_pin] = targets[toe_pin, toe_i]
        root_seed_sum[ankle_pin] += targets[ankle_pin, ankle_i] - points[ankle_pin, ankle_i]
        root_seed_count[ankle_pin] += 1.
        root_seed_sum[toe_pin] += targets[toe_pin, toe_i] - points[toe_pin, toe_i]
        root_seed_count[toe_pin] += 1.
        follows_root = ~owned
        target_ankle[follows_root] = points[follows_root, ankle_i]
        target_toe[follows_root] = points[follows_root, toe_i]

        source_length = np.linalg.norm(source_vector, axis=1)
        source_direction = source_vector / np.maximum(source_length[:, None], _EPS)
        fixed_foot_length = float(np.linalg.norm(source_vector[0]))
        source_vector = source_direction * fixed_foot_length
        free_trajectory = follows_root & trajectory
        if np.any(free_trajectory):
            midpoint = .5 * (points[:, ankle_i] + points[:, toe_i])
            target_ankle[free_trajectory] = (
                midpoint[free_trajectory] - .5 * source_vector[free_trajectory])
            target_toe[free_trajectory] = (
                midpoint[free_trajectory] + .5 * source_vector[free_trajectory])
        target_toe[ankle_only] = target_ankle[ankle_only] + source_vector[ankle_only]
        target_ankle[toe_only] = target_toe[toe_only] - source_vector[toe_only]
        target_vector = target_toe - target_ankle
        target_length = np.linalg.norm(target_vector, axis=1)
        source_knee = angles(reference[:, hip_i], reference[:, knee_i], reference[:, ankle_i])
        source_foot = reference[:, toe_i].copy()
        source_foot[owned] = reference[owned, ankle_i] + source_vector[owned]
        source_ankle = angles(reference[:, knee_i], reference[:, ankle_i], source_foot)
        poles = _source_knee_poles(points[:, hip_i], points[:, knee_i], points[:, ankle_i])
        if np.any(np.linalg.norm(poles, axis=1) <= 1e-5):
            return None, {'feasible': False, 'reason': f'{side}_source_knee_pole_unresolved'}
        body_axes = body_orientation_axes(points, names)
        body_basis = frame_basis(body_axes[:, 1], body_axes[:, 0]) if body_axes.shape[1] else np.tile(
            np.eye(3), (len(points), 1, 1))
        source_local = np.einsum('fji,fj->fi', body_basis, source_vector)
        target_local = np.einsum('fji,fj->fi', body_basis, target_vector)
        pose = _foot_pose_report(source_local[owned], target_local[owned])
        allowed = next(float(row[4]) for row in ARTICULATIONS if row[0] == f'{side}_ankle')
        max_heading = float(np.max(np.abs(pose['headingDeltaDegrees']), initial=0.))
        max_pitch = float(np.max(np.abs(pose['pitchDeltaDegrees']), initial=0.))
        p95_heading = float(np.percentile(np.abs(pose['headingDeltaDegrees']), 95))
        p95_pitch = float(np.percentile(np.abs(pose['pitchDeltaDegrees']), 95))
        pair_error = float(np.max(np.abs(target_length[both] - fixed_foot_length), initial=0.))
        preflight[side] = {
            'activeFrames': int(owned.sum()), 'bothEndpointsPinnedFrames': int(both.sum()),
            'fixedRigFootLengthMeters': fixed_foot_length,
            'maxPinnedPairLengthErrorMeters': pair_error,
            'medianSourceHeadingDegrees': float(np.median(pose['sourceHeadingDegrees'])),
            'medianTargetHeadingDegrees': float(np.median(pose['targetHeadingDegrees'])),
            'medianSourcePitchDegrees': float(np.median(pose['sourcePitchDegrees'])),
            'medianTargetPitchDegrees': float(np.median(pose['targetPitchDegrees'])),
            'maxSourceHeadingDeltaDegrees': max_heading,
            'maxSourcePitchDeltaDegrees': max_pitch,
            'p95SourceHeadingDeltaDegrees': p95_heading,
            'p95SourcePitchDeltaDegrees': p95_pitch,
            'maximumHeadingDeltaDegrees': max_heading,
            'maximumPitchDeltaDegrees': max_pitch,
            'maxHeadingDeltaDegrees': max_heading,
            'maxPitchDeltaDegrees': max_pitch,
        }
        # The same immutable pre-support limits used by the independent guard
        # bound contact-owned foot pose. A contradictory target must be fixed at
        # its evidence owner, not accommodated by changing valid articulation.
        if pair_error > 1e-5 or p95_heading > allowed or p95_pitch > allowed:
            return None, {'feasible': False, 'reason': f'{side}_contact_target_changes_source_foot_pose',
                          'preflight': preflight,
                          'sourceTargetEvidence': {key: np.asarray(value).tolist()
                                                   for key, value in pose.items()}}
        specs.append({
            'side': side, 'indices': (hip_i, knee_i, ankle_i, toe_i),
            'hip': points[:, hip_i], 'knee': points[:, knee_i],
            'ankle': points[:, ankle_i], 'toe': points[:, toe_i],
            'targetAnkle': target_ankle, 'targetToe': target_toe,
            'ankleFollowsRoot': follows_root, 'toeFollowsRoot': follows_root,
            'thigh': np.linalg.norm(points[:, knee_i] - points[:, hip_i], axis=1),
            'shin': np.linalg.norm(points[:, ankle_i] - points[:, knee_i], axis=1),
            'pole': _unit(poles), 'sourceAxis': _unit(points[:, ankle_i] - points[:, hip_i]),
            'referenceKneeAngle': source_knee, 'referenceAnkleAngle': source_ankle,
            'kneeTolerance': np.deg2rad(next(float(row[4]) for row in ARTICULATIONS
                                              if row[0] == f'{side}_knee')),
            'ankleTolerance': np.deg2rad(allowed),
        })
    root_seed = root_seed_sum / np.maximum(root_seed_count[:, None], 1.)
    for spec in specs:
        spec['rootSeed'] = root_seed
    return specs, {'feasible': bool(specs), 'feet': preflight}


def _root_track(specs, count, deadline, cyclic, fps):
    bounds = [(-_ROOT_LIMIT_METERS, _ROOT_LIMIT_METERS)] * 3
    translations = np.zeros((count, 3), dtype=float)
    for frame in range(count):
        if monotonic() >= deadline:
            raise TimeoutError('joint plant root feasibility exceeded deadline')
        zero_margins, _ = _frame_state(specs, frame, np.zeros(3))
        if (np.min(zero_margins) >= -1e-8
                and all(np.max(np.abs(spec['targetAnkle'][frame] - spec['ankle'][frame]), initial=0.) < 1e-10
                        and np.max(np.abs(spec['targetToe'][frame] - spec['toe'][frame]), initial=0.) < 1e-10
                        for spec in specs)):
            continue
        def frame_margins(value, f=frame):
            if monotonic() >= deadline:
                raise TimeoutError('joint plant frame feasibility exceeded deadline')
            return _frame_state(specs, f, value)[0]

        constraints = [{'type': 'ineq', 'fun': frame_margins}]
        root_seed = specs[0]['rootSeed'][frame].copy()
        seeds = [np.zeros(3)]
        if not np.allclose(root_seed, seeds[0], rtol=0., atol=1e-12):
            seeds.append(root_seed)
        if frame:
            previous_seed = translations[frame - 1].copy()
        elif cyclic:
            previous_seed = translations[-1].copy()
        else:
            previous_seed = None
        if (previous_seed is not None
                and not any(np.allclose(previous_seed, seed, rtol=0., atol=1e-12)
                            for seed in seeds)):
            seeds.append(previous_seed)
        def cost(value):
            current_margins = frame_margins(value)
            tolerance = np.asarray([
                item for spec in specs for item in
                (spec['kneeTolerance'], spec['ankleTolerance'])])
            delta = np.maximum(tolerance - np.deg2rad(_INTERIOR_MARGIN_DEGREES)
                               - current_margins, 0.)
            return float(delta @ delta + _ROOT_COST_WEIGHT
                         * (value @ value) / (_ROOT_LIMIT_METERS ** 2))
        attempts = [minimize(cost, seed,
                             method='SLSQP',
                             bounds=bounds, constraints=constraints,
                             options={'maxiter': 35, 'ftol': 1e-9, 'disp': False})
                    for seed in seeds]
        feasible = [np.asarray(result.x, dtype=float) for result in attempts
                    if np.min(_frame_state(specs, frame, result.x)[0]) >= -1e-7]
        if not feasible:
            margins = [np.min(_frame_state(specs, frame, result.x)[0]) for result in attempts]
            return None, {'feasible': False, 'frame': frame,
                          'bestMinimumMarginDegrees': float(np.rad2deg(max(margins)))}
        translations[frame] = min(feasible, key=cost)

    if count > 2:
        d2 = diags([np.ones(count - 2), -2. * np.ones(count - 2),
                    np.ones(count - 2)], [0, 1, 2], shape=(count - 2, count), format='lil')
        if cyclic:
            d2 = lil_matrix((count, count), dtype=float)
            for row in range(count):
                d2[row, row] = -2.
                d2[row, (row - 1) % count] = 1.
                d2[row, (row + 1) % count] = 1.
        d2 = d2.tocsr()
        system = eye(count, format='csr') + 8. * (d2.T @ d2)
        smooth = np.column_stack([np.asarray(
            spsolve(system.tocsc(), translations[:, axis])).ravel() for axis in range(3)])
        for _ in range(3):
            projected = np.clip(smooth, -_ROOT_LIMIT_METERS, _ROOT_LIMIT_METERS)
            for frame in range(count):
                if monotonic() >= deadline:
                    raise TimeoutError('joint plant root smoothing exceeded deadline')
                if np.min(_frame_state(specs, frame, projected[frame])[0]) >= -1e-7:
                    continue
                def smooth_frame_margins(value, f=frame):
                    if monotonic() >= deadline:
                        raise TimeoutError('joint plant smoothing feasibility exceeded deadline')
                    return _frame_state(specs, f, value)[0]

                result = minimize(
                    lambda value, f=frame: float(np.sum(((value - smooth[f]) / .02) ** 2)),
                    projected[frame], method='SLSQP', bounds=bounds,
                    constraints=[{'type': 'ineq', 'fun': smooth_frame_margins}],
                    options={'maxiter': 30, 'ftol': 1e-9, 'disp': False})
                if np.min(_frame_state(specs, frame, result.x)[0]) >= -1e-7:
                    projected[frame] = result.x
            translations = projected
            smooth = np.column_stack([np.asarray(
                spsolve(system.tocsc(), translations[:, axis])).ravel() for axis in range(3)])
        margins = np.asarray([_frame_state(specs, frame, projected[frame])[0]
                              for frame in range(count)])
        if not np.isfinite(margins).all() or np.min(margins) < -1e-7:
            return None, {'feasible': False, 'reason': 'smoothed_root_track_not_feasible',
                          'minimumMarginDegrees': float(np.rad2deg(np.nanmin(margins)))}
        translations = projected
    cyclic_differences = (np.diff(np.vstack((translations[-1:], translations)), axis=0)
                          if cyclic else np.diff(translations, axis=0))
    second_difference = ((np.roll(translations, 1, axis=0) - 2. * translations
                          + np.roll(translations, -1, axis=0)) if cyclic else
                         np.diff(translations, n=2, axis=0))
    return translations, {
        'feasible': True,
        'maxMagnitudeMeters': float(np.max(np.linalg.norm(translations, axis=1), initial=0.)),
        'maxAbsCorrectionXYZMeters': [
            float(np.max(np.abs(translations[:, axis]), initial=0.))
            for axis in range(3)
        ],
        'rmsMagnitudeMeters': float(np.sqrt(np.mean(np.sum(translations ** 2, axis=1)))),
        'maxStepMeters': float(np.max(np.linalg.norm(cyclic_differences, axis=1), initial=0.)),
        'maxSecondDifferenceMeters': float(np.max(np.linalg.norm(second_difference, axis=1), initial=0.)),
        'maxCorrectionSpeedMetersPerSecond': float(
            np.max(np.linalg.norm(cyclic_differences, axis=1), initial=0.) * fps),
        'maxCorrectionAccelerationMetersPerSecondSquared': float(
            np.max(np.linalg.norm(second_difference, axis=1), initial=0.) * fps * fps),
        'cyclic': bool(cyclic),
    }


def initialize_joint_plant_coordinates(rig, coordinates, pinned, contact_targets, *,
                                       articulation_reference, fps, cyclic=False, deadline,
                                       desired_world_foot_directions=None,
                                       pitch_authority_mask_by_side=None,
                                       pitch_trajectory_mask_by_side=None):
    """Solve planted poses with bounded root travel and only supported-leg articulation."""
    baseline = np.asarray(coordinates, dtype=float)
    pins = np.asarray(pinned, dtype=bool)
    targets = np.asarray(contact_targets, dtype=float)
    reference = np.asarray(articulation_reference, dtype=float)
    if (baseline.ndim != 2 or pins.shape != (len(baseline), len(rig.names))
            or targets.shape != (len(baseline), len(rig.names), 3)
            or reference.shape != targets.shape):
        return None, {'feasible': False, 'reason': 'incompatible_initializer_inputs'}
    points = rig.decode(baseline)
    specs, preflight = _make_specs(
        rig.names, points, pins, targets, reference,
        desired_world_foot_directions=desired_world_foot_directions,
        pitch_authority_mask_by_side=pitch_authority_mask_by_side,
        pitch_trajectory_mask_by_side=pitch_trajectory_mask_by_side)
    if not specs:
        return None, {'feasible': False, **preflight}
    offsets, root_report = _root_track(specs, len(points), deadline, cyclic, fps)
    if offsets is None:
        return None, {'feasible': False, 'preflight': preflight, 'root': root_report}
    if monotonic() >= deadline:
        raise TimeoutError('joint plant encoding exceeded deadline')
    encoded, initialized, margins = _encode_root_adjusted_pose(rig, baseline, specs, offsets)
    if monotonic() >= deadline:
        raise TimeoutError('joint plant encoding exceeded deadline')
    if encoded is None:
        return None, {'feasible': False, 'preflight': preflight, 'root': root_report,
                      'reason': 'closed_chain_encoding_failed'}
    actual = rig.decode(encoded)
    contact_error = np.linalg.norm((actual - targets)[pins], axis=-1)
    if not np.isfinite(actual).all() or np.max(contact_error, initial=0.) > 1e-5:
        return None, {'feasible': False, 'preflight': preflight, 'root': root_report,
                      'reason': 'exact_contact_postcheck_failed',
                      'maximumContactErrorMeters': float(np.max(contact_error, initial=0.))}
    knee_margins = margins[:, 0::2]
    ankle_margins = margins[:, 1::2]
    for side_index, spec in enumerate(specs):
        preflight['feet'][spec['side']].update({
            'minimumKneeMarginDegrees': float(np.rad2deg(np.min(knee_margins[:, side_index]))),
            'minimumAnkleMarginDegrees': float(np.rad2deg(np.min(ankle_margins[:, side_index]))),
        })
    return encoded, {
        'feasible': True, 'strategy': 'bounded_joint_root_and_closed_chain_legs',
        'preflight': preflight, 'root': root_report,
        'maximumContactErrorMeters': float(np.max(contact_error, initial=0.)),
        'minimumKneeMarginDegrees': float(np.rad2deg(np.min(knee_margins))),
        'minimumAnkleMarginDegrees': float(np.rad2deg(np.min(ankle_margins))),
        'maximumRootTranslationMeters': float(np.max(np.linalg.norm(offsets, axis=1), initial=0.)),
    }
