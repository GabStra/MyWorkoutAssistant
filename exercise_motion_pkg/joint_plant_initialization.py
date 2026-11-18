"""Bounded common-root and closed-chain initialization for observed foot plants."""
from __future__ import annotations

from copy import deepcopy
from time import monotonic

import numpy as np
from scipy.interpolate import PchipInterpolator
from scipy.optimize import minimize
from scipy.sparse import diags, eye, lil_matrix
from scipy.sparse.linalg import spsolve
from scipy.spatial.transform import Rotation

from .contact_heel_repair import (
    _EPS, _INTERIOR_MARGIN_DEGREES, _ROOT_LIMIT_METERS,
    _encode_foot_world_orientations, _encode_root_adjusted_pose,
    _frame_state as _closed_chain_frame_state, _unit,
)
from .foot_kinematics import _source_knee_poles
from .physical_validation import ARTICULATIONS, angles, source_articulation_fit_bounds
from .support_geometry import _native_side_axes_for_coordinates
from .sequence_stabilization import frame_basis
from .temporal_quality import body_orientation_axes

_ROOT_COST_WEIGHT = 1e-3
_NATIVE_FULLSOLE_TOLERANCE_METERS = 1e-5
_ROOT_FEASIBILITY_TOLERANCE_RADIANS = 1e-7


def _frame_state(specs, frame, translation):
    margins, knees = _closed_chain_frame_state(specs, frame, translation)
    context = specs[0].get('sourceHingeContext') if specs else None
    if context is None:
        return margins, knees
    if knees is None:
        return np.r_[margins, np.full(len(specs), np.pi)], knees
    from .controlled_motion import hinge_coordinates, transported_hinge_dots
    names, points, source_parent, source_bend, reliable = context
    candidate = points[frame:frame+1].copy() + translation
    for spec, knee in zip(specs, knees):
        _, knee_i, ankle_i, toe_i = spec['indices']
        candidate[0, knee_i] = knee
        candidate[0, ankle_i] = spec['targetAnkle'][frame] + translation*spec['ankleFollowsRoot'][frame]
        candidate[0, toe_i] = spec['targetToe'][frame] + translation*spec['toeFollowsRoot'][frame]
    project_emitted = specs[0].get('projectEmittedPoints')
    if project_emitted is not None:
        candidate = project_emitted(frame, translation, candidate)
        if candidate is None:
            return np.r_[margins, np.full(len(specs), -np.pi)], knees
        for index, spec in enumerate(specs):
            hip, knee, ankle, toe = spec['indices']
            knee_angle = angles(candidate[:, hip], candidate[:, knee], candidate[:, ankle])[0]
            ankle_angle = angles(candidate[:, knee], candidate[:, ankle], candidate[:, toe])[0]
            margins[2 * index] = min(margins[2 * index],
                knee_angle - spec['kneeLower'][frame], spec['kneeUpper'][frame] - knee_angle)
            margins[2 * index + 1] = min(margins[2 * index + 1],
                spec['ankleTolerance'] - np.deg2rad(_INTERIOR_MARGIN_DEGREES)
                - abs(ankle_angle - spec['referenceAnkleAngle'][frame]))
    parent, bend, sine = hinge_coordinates(candidate, names)
    dots = transported_hinge_dots(
        source_parent[frame:frame+1], source_bend[frame:frame+1], parent, bend)
    hinge_specs = [row for row in ARTICULATIONS if row[0].endswith(('_knee', '_elbow'))]
    hinge_margins = np.full(len(specs), np.pi)
    for index, spec in enumerate(specs):
        column = next(i for i, row in enumerate(hinge_specs) if row[0] == spec['side']+'_knee')
        if reliable[frame, column] and sine[0, column] > np.sin(np.deg2rad(15.)):
            angle = np.arccos(np.clip(dots[0, column], -1., 1.))
            # Keep solver feasibility slack inside the unchanged strict postcheck.
            hinge_margins[index] = (np.deg2rad(hinge_specs[column][-1]) - angle
                                   - 2. * _ROOT_FEASIBILITY_TOLERANCE_RADIANS)
    return np.r_[margins, hinge_margins], knees


def _root_bend_deviation(specs, frame, translation, knees):
    """Source-reference bend preference for common-root seed selection.

    Sum of squared hip-ankle-relative knee-bend deviations from the inferred
    source-reference bend, normalised by thigh length. Selecting the offset
    that minimises it keeps the closed-chain seed on the source's bend branch
    instead of crossing the outer reach fold, where the clip/clamp in the
    shared frame state silently flattens a bent source knee (or over-bends it
    as the cyclic track resizes the span on the other seam end). This is a
    selection preference, not a feasibility floor: a legitimately straight or
    locked leg (reference bend ~0) and support-driven flexion stay possible.
    """
    if knees is None:
        return 0.
    total = 0.
    for spec, knee in zip(specs, knees):
        source_height = spec.get('sourceKneeHeight')
        if source_height is None:
            continue
        hip = spec['hip'][frame] + translation
        ankle = spec['targetAnkle'][frame] + translation * spec['ankleFollowsRoot'][frame]
        line = ankle - hip
        distance = float(np.linalg.norm(line))
        if distance < _EPS:
            continue
        axis = line / distance
        relative = knee - hip
        bend_height = float(np.linalg.norm(relative - np.dot(relative, axis) * axis))
        scale = max(float(spec['thigh'][frame]), _EPS)
        total += ((bend_height - float(source_height[frame])) / scale) ** 2
    return total


def _native_fullsole_reference_normals(evidence, side, mapped, source_count):
    """Per-row calibrated sole invariant for a validated native full-sole track.

    Returns ``(world_normal, forward_component, owned)`` when a validated
    stationary ``full_sole`` episode covers at least one source row, else
    ``None``. ``world_normal`` is the episode support-plane normal and
    ``forward_component`` is the sole normal expressed along the material
    ``forward`` (ankle->foot bone) axis. A rigid sole keeps
    ``bone_forward . world_normal == forward_component`` at every episode frame.
    Rows without a qualified, calibrated episode are not owned and must keep the
    legacy raw contact-foot vector.
    """
    tracks = (evidence or {}).get('_nativeFootMaterialTracks')
    if not isinstance(tracks, dict) or tracks.get('version') != 2:
        return None
    track = tracks.get(side)
    if not isinstance(track, dict):
        return None
    try:
        from .contact_interpolation import _validated_native_side_track
        active, _, _, _ = _validated_native_side_track(
            track, len(track['active']), side)
    except (KeyError, TypeError, ValueError):
        return None
    track_count = len(active)
    track_normal = np.zeros((track_count, 3), dtype=float)
    track_forward = np.zeros(track_count, dtype=float)
    track_owned = np.zeros(track_count, dtype=bool)
    for episode in track['episodes']:
        if (not isinstance(episode, dict)
                or str(episode.get('regionRole')) != 'full_sole'
                or str(episode.get('mode')) != 'stationary'):
            continue
        try:
            start = int(episode['startFrame'])
            end = int(episode['endFrame'])
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        if not 0 <= start <= end < track_count:
            continue
        sole_local = episode.get('soleNormalLocalMeters')
        normal = episode.get('surfaceNormal')
        if sole_local is None or normal is None:
            continue
        try:
            sole_local = np.asarray(sole_local, dtype=float)
            normal = np.asarray(normal, dtype=float)
        except (TypeError, ValueError):
            continue
        sole_length = float(np.linalg.norm(sole_local))
        normal_length = float(np.linalg.norm(normal))
        if (sole_local.shape != (3,) or not np.isfinite(sole_local).all()
                or normal.shape != (3,) or not np.isfinite(normal).all()
                or sole_length <= _EPS or abs(sole_length - 1.) > 1e-6
                or normal_length <= _EPS):
            continue
        rows = np.arange(start, end + 1)[active[start:end + 1]]
        if not len(rows):
            continue
        track_normal[rows] = normal / normal_length
        track_forward[rows] = float(sole_local[0] / sole_length)
        track_owned[rows] = True
    if not np.any(track_owned):
        return None
    mapped = np.asarray(mapped, dtype=int)
    valid = (mapped >= 0) & (mapped < track_count)
    rows = np.flatnonzero(valid)
    if not len(rows):
        return None
    owned_rows = rows[track_owned[mapped[rows]]]
    if not len(owned_rows):
        return None
    world_normal = np.zeros((source_count, 3), dtype=float)
    forward_component = np.zeros(source_count, dtype=float)
    owned = np.zeros(source_count, dtype=bool)
    track_rows = mapped[owned_rows]
    world_normal[owned_rows] = track_normal[track_rows]
    forward_component[owned_rows] = track_forward[track_rows]
    owned[owned_rows] = True
    return world_normal, forward_component, owned


def contact_conditioned_articulation_reference(reference, pinned, targets, names,
                                               evidence, frame_times):
    """Replace reconstructed foot pitch only on observed, mapped full-sole pins.

    The source knee and ankle remain immutable. On a trusted full-sole sample,
    only the foot vector is taken from the physical contact target. A validated,
    calibrated native full-sole episode additionally qualifies the bone forward
    direction with its rigid sole-normal invariant, preserving the source
    tangential heading and bone length. Unknown, released, partial-contact,
    uncalibrated, and out-of-source-clock rows keep the raw source articulation.
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
    native_reference_applied = False
    patch = (evidence or {}).get('footPatchEvidence') or {}
    feet = patch.get('feet') or {}
    if patch.get('available') is not True:
        return conditioned, masks, observed_masks, {
            'available': False, 'reason': 'foot_patch_unavailable'}
    from .contact_constraints import (
        fit_frame_foot_patch_states_by_side,
        mapped_foot_patch_state_indices,
    )
    mapped = np.asarray(
        mapped_foot_patch_state_indices(evidence, frame_times, len(source)), dtype=int)
    indices = mapped
    fit_states = fit_frame_foot_patch_states_by_side(evidence, len(source))
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
        aligned = fit_states.get(side)
        if aligned is not None:
            full_sole = np.asarray([
                str(state).casefold() == 'full_sole' for state in aligned
            ], dtype=bool)
            valid |= np.asarray([
                str(state).casefold() not in {'', 'unknown', 'unobserved', 'none'}
                for state in aligned
            ], dtype=bool)
        else:
            full_sole[valid] = np.asarray([
                str(states[index]).casefold() == 'full_sole' for index in indices[valid]
            ], dtype=bool)
        ankle_i, toe_i = names.index(ankle_name), names.index(toe_name)
        # The observed foot patch owns the physical full-sole state. Only the
        # foot pin is an exact point anchor here; the ankle follows from the
        # conditioned foot vector and must not be promoted to an XYZ pin.
        active = full_sole & pins[:, toe_i]
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
        vectors = target_vector
        native_owned = np.zeros(int(active.sum()), dtype=bool)
        qualified = np.zeros(int(active.sum()), dtype=bool)
        fallback = {}
        invariant_residual = 0.
        native_frame = None
        native = _native_fullsole_reference_normals(
            evidence, side, indices, len(source))
        if native is not None:
            world_normal, forward_component, owned_all = native
            native_owned = owned_all[active]
            target_length = np.linalg.norm(target_vector, axis=1)
            length_ok = target_length > _EPS
            raw_hat = np.zeros_like(target_vector)
            np.divide(target_vector, target_length[:, None], out=raw_hat,
                      where=length_ok[:, None])
            normal = world_normal[active]
            forward_component = np.clip(forward_component[active], -1., 1.)
            tangential = raw_hat - np.sum(
                raw_hat * normal, axis=1, keepdims=True) * normal
            tangential_length = np.linalg.norm(tangential, axis=1)
            heading_ok = tangential_length > 1e-8
            qualified = native_owned & length_ok & heading_ok
            if np.any(qualified):
                tangent = np.zeros_like(tangential)
                np.divide(tangential, tangential_length[:, None], out=tangent,
                          where=heading_ok[:, None])
                scale = np.sqrt(np.maximum(0., 1. - forward_component ** 2))
                bone = (forward_component[:, None] * normal
                        + scale[:, None] * tangent)
                vectors = target_vector.copy()
                vectors[qualified] = bone[qualified] * target_length[qualified, None]
                invariant_residual = float(np.max(np.abs(
                    np.sum(bone[qualified] * normal[qualified], axis=1)
                    - forward_component[qualified]), initial=0.))
                native_reference_applied = True
                native_frame = {
                    'worldNormal': normal[qualified][0].tolist(),
                    'forwardComponent': float(forward_component[qualified][0]),
                }
            fallback = {
                'boneLength': int(np.count_nonzero(native_owned & ~length_ok)),
                'tangentialHeading': int(np.count_nonzero(
                    native_owned & length_ok & ~heading_ok)),
            }
        conditioned[active, toe_i] = source_ankle + vectors
        report[side] = {
            'conditionedFrameCount': int(active.sum()),
            'mappedFrameCount': int(valid.sum()),
            'mappedFullSoleFrameCount': int(full_sole.sum()),
            'unmappedFrameCount': int(np.count_nonzero(indices < 0)),
            'nativeFullsoleOwnedFrameCount': int(native_owned.sum()),
            'nativeFullsoleUnownedFrameCount': int(
                active.sum() - native_owned.sum()),
            'nativeFullsoleReferenceFrameCount': int(qualified.sum()),
            'nativeFullsoleFallbackFrameCount': int(
                native_owned.sum() - qualified.sum()),
            'nativeFullsoleFallbackReasons': fallback,
            'nativeFullsoleMaximumNormalInvariantResidual': invariant_residual,
            'nativeFullsoleFrame': native_frame,
            'nativeFullsoleReference': (
                'calibrated_native_material_frame' if np.any(qualified)
                else 'raw_contact_target_fallback'),
        }
    return conditioned, masks, observed_masks, {
        'available': bool(masks),
        'reference': ('source_shin_with_calibrated_native_full_sole_reference_frame'
                      if native_reference_applied
                      else 'source_shin_with_observed_full_sole_foot_vector'),
        'nativeFullsoleFrameBasis': (
            'inferred_rigid_material_frame_from_calibrated_sole_normal_and_observed_contact'
            if native_reference_applied else 'not_applied'),
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
        pitch_trajectory_mask_by_side, *, source_reference, frame_times):
    """Transport calibrated foot-angle corrections over the source clock.

    Directions are measured only on qualified trajectories. Their angular
    correction relative to the immutable pre-contact source is carried through
    free frames, so entering or leaving a measured segment does not switch
    between calibrated and raw angle baselines.
    """
    source = np.asarray(reference, dtype=float)
    original = np.asarray(source_reference, dtype=float)
    pins = np.asarray(pinned, dtype=bool)
    directions = np.asarray(desired_world_foot_directions, dtype=float)
    if (source.ndim != 3 or source.shape[1:] != (len(names), 3)
            or original.shape != source.shape
            or pins.shape != source.shape[:2]
            or directions.shape != (len(source), 2, 3)):
        raise ValueError('incompatible source foot direction reference inputs')
    trajectories = {
        side: np.asarray(
            (pitch_trajectory_mask_by_side or {}).get(side, np.zeros(len(source))),
            dtype=bool)
        for side in ('left', 'right')
    }
    for side, trajectory in trajectories.items():
        if trajectory.shape != (len(source),):
            raise ValueError(f'{side} pitch trajectory mask must have shape (frames,)')
    if not any(np.any(trajectory) for trajectory in trajectories.values()):
        return source.copy(), {'left': 0, 'right': 0}, {
            side: {'trajectoryFrameCount': 0, 'transportedFrameCount': 0}
            for side in ('left', 'right')
        }
    clock = np.asarray(frame_times, dtype=float)
    if (clock.shape != (len(source),) or not np.isfinite(clock).all()
            or np.any(np.diff(clock) < 0.)):
        raise ValueError('source foot direction clock must be finite and nondecreasing')
    conditioned = source.copy()
    counts = {}
    details = {}
    from scipy.interpolate import PchipInterpolator

    for side_index, side in enumerate(('left', 'right')):
        ankle_name, toe_name = f'{side}_ankle', f'{side}_foot'
        if ankle_name not in names or toe_name not in names:
            counts[side] = 0
            continue
        ankle_i, toe_i = names.index(ankle_name), names.index(toe_name)
        trajectory = trajectories[side]
        rows = trajectory
        lengths = np.linalg.norm(directions[:, side_index], axis=1)
        if np.any(rows & (~np.isfinite(lengths) | (lengths <= _EPS))):
            raise ValueError(f'{side} source foot direction is invalid on its trajectory')
        source_bones = original[:, toe_i] - original[:, ankle_i]
        source_lengths = np.linalg.norm(source_bones, axis=1)
        source_length = float(np.median(source_lengths))
        if np.any(rows) and source_length <= _EPS:
            raise ValueError(f'{side} source foot length is unavailable')
        if not np.any(rows):
            counts[side] = 0
            details[side] = {'trajectoryFrameCount': 0, 'transportedFrameCount': 0}
            continue

        source_unit = source_bones / np.maximum(source_lengths[:, None], _EPS)
        target_unit = directions[:, side_index] / np.maximum(lengths[:, None], _EPS)
        source_yaw = np.arctan2(source_unit[:, 0], source_unit[:, 2])
        source_pitch = np.arctan2(source_unit[:, 1], np.linalg.norm(source_unit[:, [0, 2]], axis=1))
        target_yaw = np.arctan2(target_unit[:, 0], target_unit[:, 2])
        target_pitch = np.arctan2(target_unit[:, 1], np.linalg.norm(target_unit[:, [0, 2]], axis=1))
        owned = np.flatnonzero(rows)
        yaw_correction = np.unwrap(_angle_delta(target_yaw[owned], source_yaw[owned]))
        pitch_correction = target_pitch[owned] - source_pitch[owned]
        knot_times, inverse = np.unique(clock[owned], return_inverse=True)
        # These corrections compare reconstructed bones to observed directions;
        # same-exposure reconstruction rows may differ. Use representative
        # transport knots without discarding the exact measured row corrections.
        knot_yaw = np.array([np.median(yaw_correction[inverse == index])
                             for index in range(len(knot_times))])
        knot_pitch = np.array([np.median(pitch_correction[inverse == index])
                               for index in range(len(knot_times))])
        if len(knot_times) == 1:
            yaw_track = np.full(len(source), knot_yaw[0], dtype=float)
            pitch_track = np.full(len(source), knot_pitch[0], dtype=float)
        else:
            clipped_clock = np.clip(clock, knot_times[0], knot_times[-1])
            yaw_track = np.asarray(PchipInterpolator(
                knot_times, knot_yaw, extrapolate=False)(clipped_clock), dtype=float)
            pitch_track = np.asarray(PchipInterpolator(
                knot_times, knot_pitch, extrapolate=False)(clipped_clock), dtype=float)
        yaw_track[owned] = yaw_correction
        pitch_track[owned] = pitch_correction

        transported_yaw = source_yaw + yaw_track
        transported_pitch = source_pitch + pitch_track
        transported_direction = np.stack((
            np.sin(transported_yaw) * np.cos(transported_pitch),
            np.sin(transported_pitch),
            np.cos(transported_yaw) * np.cos(transported_pitch),
        ), axis=1)
        conditioned[:, toe_i] = (
            conditioned[:, ankle_i] + transported_direction * source_length)
        counts[side] = int(rows.sum())
        details[side] = {
            'trajectoryFrameCount': int(rows.sum()),
            'transportedFrameCount': int((~rows).sum()),
            'yawCorrectionRangeDegrees': np.rad2deg([
                float(np.min(yaw_track)), float(np.max(yaw_track))]).tolist(),
            'pitchCorrectionRangeDegrees': np.rad2deg([
                float(np.min(pitch_track)), float(np.max(pitch_track))]).tolist(),
            'maximumCorrectionStepDegrees': float(np.rad2deg(max(
                np.max(np.abs(np.diff(yaw_track))) if len(yaw_track) > 1 else 0.,
                np.max(np.abs(np.diff(pitch_track))) if len(pitch_track) > 1 else 0.))),
        }
    return conditioned, counts, details


def _carry_contact_placement(source_ankle, source_toe, target_ankle, target_toe,
                             owned, *, ankle_owned=None, cyclic=False):
    """Carry placement between contacts without filtering the source motion."""
    rows = np.flatnonzero(owned)
    if not len(rows):
        return target_ankle, target_toe
    ankle_owned = owned if ankle_owned is None else np.asarray(ankle_owned, dtype=bool)
    source_anchor = np.where(ankle_owned[:, None], source_ankle, source_toe)
    target_anchor = np.where(ankle_owned[:, None], target_ankle, target_toe)
    corrections = target_anchor[rows] - source_anchor[rows]
    clock = np.arange(len(owned), dtype=float)
    if cyclic:
        rows = np.concatenate((rows - len(owned), rows, rows + len(owned)))
        corrections = np.tile(corrections, (3, 1))
    if len(rows) == 1:
        correction = np.broadcast_to(corrections[0], source_ankle.shape)
    else:
        correction = PchipInterpolator(rows, corrections, axis=0)(
            np.clip(clock, rows[0], rows[-1]))
    free = ~owned
    target_ankle[free] = source_ankle[free] + correction[free]
    target_toe[free] = source_toe[free] + correction[free]
    return target_ankle, target_toe


def _native_fullsole_target(episode, material, normal):
    """Stationary full-sole world target for the current material sample."""
    target = episode.get('targetWorld')
    if target is not None:
        target = np.asarray(target, dtype=float)
        if target.shape != (3,) or not np.isfinite(target).all():
            return None
        return np.broadcast_to(target, material.shape).copy()
    offset = episode.get('planeOffsetMeters')
    try:
        offset = float(offset)
    except (TypeError, ValueError, OverflowError):
        return None
    if not np.isfinite(offset):
        return None
    return material - (material @ normal - offset)[:, None] * normal


def _native_fullsole_material_rotation(source_normal, source_heading,
                                       target_normal, target_heading):
    """Closest proper rotation mapping the sole plane while keeping heading."""
    source_normal = _unit(source_normal)
    target_normal = _unit(target_normal)
    if np.linalg.norm(source_normal) <= _EPS or np.linalg.norm(target_normal) <= _EPS:
        return None
    source_heading = source_heading - source_normal * np.dot(source_heading, source_normal)
    target_heading = target_heading - target_normal * np.dot(target_heading, target_normal)
    if np.linalg.norm(source_heading) <= 1e-8 or np.linalg.norm(target_heading) <= 1e-8:
        return Rotation.align_vectors(
            target_normal[None, :], source_normal[None, :])[0].as_matrix()
    source_heading = _unit(source_heading)
    target_heading = _unit(target_heading)
    return Rotation.align_vectors(
        np.stack((target_normal, target_heading)),
        np.stack((source_normal, source_heading)))[0].as_matrix()


def _native_fullsole_mirror_pair(coverage, native_foot_mirror_required):
    """Return the overlapping bilateral full-sole rows eligible for shared orientation."""
    if (native_foot_mirror_required is not True
            or not isinstance(coverage, dict)
            or set(coverage) != {'left', 'right'}
            or any(len(coverage.get(side) or ()) != 1 for side in ('left', 'right'))):
        return None
    left, right = coverage['left'][0], coverage['right'][0]
    for entry in (left, right):
        episode = entry.get('episode') or {}
        if (episode.get('mode') != 'stationary'
                or episode.get('regionRole') != 'full_sole'):
            return None
    try:
        left_normal = _unit(np.asarray(left['episode']['surfaceNormal'], dtype=float))
        right_normal = _unit(np.asarray(right['episode']['surfaceNormal'], dtype=float))
        left_frames = np.asarray(left['frames'], dtype=int)
        right_frames = np.asarray(right['frames'], dtype=int)
    except (KeyError, TypeError, ValueError):
        return None
    if (left_frames.ndim != 1 or right_frames.ndim != 1
            or left_frames.size < 2 or right_frames.size < 2
            or np.linalg.norm(left_normal) <= _EPS
            or np.linalg.norm(right_normal) <= _EPS
            or not np.allclose(left_normal, right_normal, rtol=0., atol=1e-6)):
        return None
    try:
        left_anchor = np.asarray(left['episode']['targetWorld'], dtype=float)
        right_anchor = np.asarray(right['episode']['targetWorld'], dtype=float)
    except (KeyError, TypeError, ValueError):
        return None
    if (left_anchor.shape != (3,) or right_anchor.shape != (3,)
            or not np.isfinite(left_anchor).all() or not np.isfinite(right_anchor).all()
            or abs(float(left_anchor[1] - right_anchor[1]))
            > _NATIVE_FULLSOLE_TOLERANCE_METERS):
        return None
    mirror_normal = right_anchor - left_anchor
    mirror_normal[1] = 0.
    mirror_length = float(np.linalg.norm(mirror_normal))
    if not np.isfinite(mirror_length) or mirror_length <= _EPS:
        return None
    mirror_normal /= mirror_length
    common = np.intersect1d(left_frames, right_frames)
    if len(common) < 2:
        return None
    left_lookup = {int(frame): i for i, frame in enumerate(left_frames)}
    right_lookup = {int(frame): i for i, frame in enumerate(right_frames)}
    return {
        'left': left, 'right': right, 'frames': common,
        'mirrorNormal': mirror_normal,
        'leftIndexes': np.asarray([left_lookup[int(frame)] for frame in common], dtype=int),
        'rightIndexes': np.asarray([right_lookup[int(frame)] for frame in common], dtype=int),
    }


def _native_fullsole_track_mirror_pair(native_foot_tracks, frame_count,
                                       native_foot_mirror_required):
    """Find the qualified bilateral full-sole anchors before root-heading seeding."""
    if (native_foot_mirror_required is not True
            or not isinstance(native_foot_tracks, dict)
            or native_foot_tracks.get('version') != 2):
        return None
    frames = np.arange(frame_count, dtype=int)
    coverage = {}
    for side in ('left', 'right'):
        track = native_foot_tracks.get(side)
        # The v2 schema version belongs to the enclosing track bundle; side
        # tracks contain only their frame arrays and episodes.
        if not isinstance(track, dict):
            return None
        active = np.asarray(track.get('active', ()), dtype=bool)
        if active.shape != (frame_count,):
            return None
        entries = []
        for episode in track.get('episodes') or ():
            if (not isinstance(episode, dict)
                    or episode.get('mode') != 'stationary'
                    or episode.get('regionRole') != 'full_sole'):
                continue
            try:
                start = int(episode['startFrame'])
                end = int(episode['endFrame'])
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
            rows = frames[active & (frames >= start) & (frames <= end)]
            if len(rows) >= 2:
                entries.append({'episode': episode, 'frames': rows})
        coverage[side] = entries
    return _native_fullsole_mirror_pair(coverage, native_foot_mirror_required)


def _native_fullsole_solver_constraints(
        rig, points, coordinates, pinned, contact_targets, *,
        native_foot_tracks, native_foot_geometry, side_axis_by_side, foot_scale,
        native_foot_mirror_required=False, source_projection_constraint=None,
        fps=30.):
    """Add transient full-sole ankle/foot targets without changing evidence.

    A qualified stationary native full-sole episode owns the rendered sole
    support. Its actual six sole-bottom mesh samples define a rigid material
    transform that maps the sampled sole plane and material point to the
    observed world support. Only frames where neither ankle nor foot already
    carries an observed pin receive transient solver targets; the caller's
    pinned mask and contact targets stay untouched.
    """
    empty = {
        'pins': pinned, 'targets': contact_targets, 'orientations': {},
        'coverage': {}, 'report': {'available': False, 'sides': {}},
    }
    if (not isinstance(native_foot_tracks, dict)
            or native_foot_tracks.get('version') != 2):
        return empty
    from .native_foot_geometry import validated_native_foot_geometry
    geometry = validated_native_foot_geometry(native_foot_geometry)
    if geometry is None:
        return empty
    from .support_geometry import (
        _NATIVE_SHOE_SOLE_RING_VERTICES, _native_side_axes_for_coordinates,
    )
    try:
        current_axes = _native_side_axes_for_coordinates(
            rig, coordinates, {'_nativeFootMaterialTracks': native_foot_tracks})
    except (KeyError, TypeError, ValueError):
        return empty
    if not current_axes:
        return empty
    from .body_surface_geometry import evaluate_contact_patch
    from .foot_geometry import foot_scale_from_pose, shoe_vertices
    from .material_region_support import shoe_triangles

    scale = foot_scale
    if scale is None:
        scale = foot_scale_from_pose(points[0], rig.names)
    try:
        scale = float(scale)
    except (TypeError, ValueError, OverflowError):
        return empty
    if not np.isfinite(scale) or scale <= 0.:
        return empty
    triangles = shoe_triangles()
    count = len(points)
    frames = np.arange(count)
    derived_pins = pinned.copy()
    derived_targets = contact_targets.copy()
    orientations, coverage, report_sides = {}, {}, {}
    for side in ('left', 'right'):
        track = native_foot_tracks.get(side)
        side_geometry = (geometry.get('sides') or {}).get(side)
        basis = current_axes.get(side)
        if (not isinstance(track, dict) or side_geometry is None
                or basis is None or len(basis) != count):
            continue
        active = np.asarray(track.get('active', ()), dtype=bool)
        if active.shape != (count,) or not np.any(active):
            continue
        episodes = track.get('episodes') or ()
        if not isinstance(episodes, (list, tuple)) or not episodes:
            continue
        ankle_i, toe_i = (rig.names.index(f'{side}_ankle'),
                          rig.names.index(f'{side}_foot'))
        try:
            shoes = shoe_vertices(
                points[:, ankle_i], points[:, toe_i], np.asarray(basis, dtype=float),
                None, scale, native_geometry=side_geometry)
        except (TypeError, ValueError):
            continue
        sole = shoes[:, _NATIVE_SHOE_SOLE_RING_VERTICES]
        centered = sole - sole.mean(axis=1, keepdims=True)
        _, singular, vectors = np.linalg.svd(centered, full_matrices=False)
        if singular.shape[1] < 3:
            continue
        normals = vectors[:, -1, :]
        forward = points[:, toe_i] - points[:, ankle_i]
        lengths = np.linalg.norm(forward, axis=1)
        if np.any(lengths <= _EPS):
            continue
        forward /= lengths[:, None]
        lateral = np.asarray(basis, dtype=float)
        lateral -= forward * np.sum(lateral * forward, axis=1, keepdims=True)
        lateral_lengths = np.linalg.norm(lateral, axis=1)
        if np.any(lateral_lengths <= _EPS):
            continue
        lateral /= lateral_lengths[:, None]
        up = np.cross(lateral, forward)
        normals *= np.where(np.sum(normals * up, axis=1) >= 0., 1., -1.)[:, None]
        world_rotations = rig.global_rotations(coordinates)
        anchor_ids = track.get('anchorIds')
        if anchor_ids is not None:
            anchor_ids = np.asarray(anchor_ids, dtype=object)
            if anchor_ids.shape != (count,):
                continue
        side_derived = np.zeros(count, dtype=bool)
        side_skipped = 0
        normalized_residuals = []
        for episode in episodes:
            if (not isinstance(episode, dict)
                    or str(episode.get('regionRole')) != 'full_sole'
                    or str(episode.get('mode')) != 'stationary'):
                continue
            try:
                start = int(episode['startFrame'])
                end = int(episode['endFrame'])
                target_normal = np.asarray(episode['surfaceNormal'], dtype=float)
                triangle_index = int(episode['triangleIndex'])
                barycentric = np.asarray(episode['barycentric'], dtype=float)
                primitive_id = str(episode['primitiveId'])
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
            if (target_normal.shape != (3,) or not np.isfinite(target_normal).all()
                    or np.linalg.norm(target_normal) <= _EPS
                    or not 0 <= triangle_index < len(triangles)
                    or barycentric.shape != (3,) or not np.isfinite(barycentric).all()
                    or np.any(barycentric < 0.)
                    or not np.isclose(barycentric.sum(), 1., atol=1e-6)):
                continue
            target_normal = _unit(target_normal)
            mask = active & (frames >= start) & (frames <= end)
            anchor = episode.get('anchorId')
            if anchor_ids is not None and anchor is not None:
                mask &= anchor_ids == anchor
            rows = np.flatnonzero(mask)
            if not len(rows):
                continue
            eligible = rows[~derived_pins[rows, ankle_i] & ~derived_pins[rows, toe_i]]
            side_skipped += int(len(rows) - len(eligible))
            if not len(eligible):
                continue
            try:
                material = evaluate_contact_patch(
                    {primitive_id: {'vertices': shoes, 'triangles': triangles}},
                    {'primitiveId': primitive_id,
                     'points': [{'triangleIndex': triangle_index,
                                 'barycentric': barycentric.tolist()}]})[:, 0]
            except (KeyError, ValueError):
                continue
            target = _native_fullsole_target(episode, material, target_normal)
            if target is None:
                continue
            # A stationary full-sole episode owns one rigid material frame for
            # its whole interval. Select a measured source frame by quaternion
            # medoid so isolated tracker noise cannot choose an extreme pose.
            # Per-frame heading preservation only fixes one material point and
            # the plane; it lets the rest of a stationary sole yaw around that
            # point and moves the ankle/forefoot locators.
            source_rotations = np.empty((len(rows), 3, 3), dtype=float)
            for index, frame in enumerate(rows):
                rotation = _native_fullsole_material_rotation(
                    normals[frame], forward[frame], target_normal,
                    forward[frame])
                if rotation is None:
                    source_rotations = None
                    break
                source_rotations[index] = rotation
            if source_rotations is None:
                continue
            source_world = np.einsum(
                'fij,fjk->fik', source_rotations, world_rotations[toe_i][rows])
            quaternions = Rotation.from_matrix(source_world).as_quat()
            pairwise_angles = 2. * np.arccos(np.clip(
                np.abs(quaternions @ quaternions.T), 0., 1.))
            reference_position = int(np.argmin(pairwise_angles.sum(axis=1)))
            reference_frame = int(rows[reference_position])
            material_target = _native_fullsole_target(
                episode, material[reference_frame:reference_frame + 1], target_normal)
            if material_target is None:
                continue
            fixed_target = material_target[0]
            fixed_rotation = source_rotations[reference_position]
            ankle_target = fixed_target + fixed_rotation @ (
                points[reference_frame, ankle_i] - material[reference_frame])
            toe_target = fixed_target + fixed_rotation @ (
                points[reference_frame, toe_i] - material[reference_frame])
            if (not np.isfinite(ankle_target).all() or not np.isfinite(toe_target).all()
                    or abs(np.linalg.norm(toe_target - ankle_target)
                           - lengths[reference_frame]) > 1e-5):
                continue
            derived_pins[eligible, ankle_i] = True
            derived_pins[eligible, toe_i] = True
            derived_targets[eligible, ankle_i] = ankle_target
            derived_targets[eligible, toe_i] = toe_target
            side_derived[eligible] = True
            desired_world = source_world[reference_position]
            frame_deltas = np.einsum(
                'ij,fjk->fik', desired_world,
                np.swapaxes(world_rotations[toe_i][eligible], 1, 2))
            corrected_normals = np.einsum(
                'fij,fj->fi', frame_deltas, normals[eligible])
            normalized_residuals.append(float(np.max(
                np.abs(corrected_normals - target_normal), initial=0.)))
            # The shared axis transport binds one source-measured local
            # material axis for this stationary full-sole episode, so one
            # world rotation is sufficient for the episode. Save that local
            # axis so the post-root encoder can apply only axial twist, leaving
            # the closed-chain foot endpoint untouched.
            desired = np.broadcast_to(desired_world, (len(eligible), 3, 3)).copy()
            local_material_axes = np.einsum(
                'fji,fj->fi', world_rotations[toe_i][eligible], basis[eligible])
            if side in orientations:
                orientations[side] = {
                    'frames': np.concatenate((orientations[side]['frames'], eligible)),
                    'worldRotations': np.concatenate(
                        (orientations[side]['worldRotations'], desired), axis=0),
                    'localMaterialAxes': np.concatenate(
                        (orientations[side]['localMaterialAxes'], local_material_axes), axis=0),
                }
            else:
                orientations[side] = {
                    'frames': eligible, 'worldRotations': desired,
                    'localMaterialAxes': local_material_axes,
                }
            coverage.setdefault(side, []).append({
                'episode': {**episode, 'targetWorld': fixed_target.tolist()},
                'frames': eligible,
                'stationarityFrames': rows,
                'targets': np.broadcast_to(fixed_target, (len(eligible), 3)).copy(),
                'material': material[eligible],
                'referenceFrame': reference_frame,
            })
        if np.any(side_derived):
            report_sides[side] = {
                'derivedFrameCount': int(side_derived.sum()),
                'explicitPinSkippedFrameCount': side_skipped,
                'maximumNormalResidual': max(normalized_residuals, default=0.),
            }
    mirror_pair = _native_fullsole_mirror_pair(
        coverage, native_foot_mirror_required)
    camera_yaw_report = None
    if coverage and source_projection_constraint is not None:
        # The camera-ray selector must score the pose after the base material
        # point and sole plane have been imposed. This is a bounded in-memory
        # counterfactual; no camera estimate is promoted to observed 3D data.
        base_points = points.copy()
        for side, entries in coverage.items():
            ankle_i, toe_i = (rig.names.index(f'{side}_ankle'),
                              rig.names.index(f'{side}_foot'))
            for entry in entries:
                frames = np.asarray(entry['frames'], dtype=int)
                base_points[frames, ankle_i] = derived_targets[frames, ankle_i]
                base_points[frames, toe_i] = derived_targets[frames, toe_i]
        # The camera selector sees only frames that actually received the
        # base material/plane projection. Keep the source tracks immutable and
        # retain episode/anchor identity while masking uncovered or skipped
        # rows, including the unowned opposite side.
        selector_tracks = dict(native_foot_tracks)
        for side in ('left', 'right'):
            track = native_foot_tracks.get(side)
            if not isinstance(track, dict):
                continue
            eligible = np.zeros(count, dtype=bool)
            episodes = []
            for entry in coverage.get(side, ()):
                frames = np.asarray(entry['frames'], dtype=int)
                eligible[frames] = True
                episodes.append(entry['episode'])
            selector_tracks[side] = {
                **track, 'active': eligible, 'episodes': episodes,
            }
        try:
            from .controlled_motion import _native_fullsole_camera_yaw_by_side
            base_material_axes = None
            if getattr(rig, 'material_frames', None) is not None:
                base_material_axes = {side:np.asarray(axis).copy() for side,axis in current_axes.items()}
                for side, orientation in orientations.items():
                    base_material_axes[side][orientation['frames']] = np.einsum(
                        'fij,fj->fi',orientation['worldRotations'],orientation['localMaterialAxes'])
            yaw_by_side, camera_yaw_report = _native_fullsole_camera_yaw_by_side(
                base_points, rig.names, selector_tracks,
                source_projection_constraint, fps=fps,
                material_side_axes=base_material_axes, native_geometry=geometry)
        except (KeyError, TypeError, ValueError, RuntimeError) as error:
            return {**empty, 'report': {
                'available': False,
                'reason': f'native_fullsole_camera_yaw_unavailable:{error}',
            }}
        if not isinstance(yaw_by_side, dict):
            return {**empty, 'report': {
                'available': False, 'reason': 'native_fullsole_camera_yaw_invalid',
            }}
        coupled_yaw_by_side = {}
        if mirror_pair is not None:
            independent_left = float(yaw_by_side.get('left', 0.))
            independent_right = float(yaw_by_side.get('right', 0.))
            coupled_left = .5 * (independent_left - independent_right)
            coupled_yaw_by_side = {'left': coupled_left, 'right': -coupled_left}
        for side, raw_yaw in yaw_by_side.items():
            if side not in coverage:
                continue
            try:
                yaw = (float(coupled_yaw_by_side[side]) if side in coupled_yaw_by_side
                       else float(raw_yaw))
            except (TypeError, ValueError, OverflowError):
                return {**empty, 'report': {
                    'available': False, 'reason': f'{side}_native_camera_yaw_invalid',
                }}
            if not np.isfinite(yaw):
                return {**empty, 'report': {
                    'available': False, 'reason': f'{side}_native_camera_yaw_invalid',
                }}
            ankle_i, toe_i = (rig.names.index(f'{side}_ankle'),
                              rig.names.index(f'{side}_foot'))
            values = orientations.get(side)
            if values is None:
                return {**empty, 'report': {
                    'available': False, 'reason': f'{side}_native_camera_yaw_orientation_missing',
                }}
            orientation_frames = np.asarray(values['frames'], dtype=int)
            orientation_by_frame = {
                int(frame): rotation for frame, rotation in zip(
                    orientation_frames, np.asarray(values['worldRotations'], dtype=float))
            }
            local_axis_by_frame = {
                int(frame): axis for frame, axis in zip(
                    orientation_frames, np.asarray(values['localMaterialAxes'], dtype=float))
            }
            for entry in coverage[side]:
                frames = np.asarray(entry['frames'], dtype=int)
                target = np.asarray(entry['targets'], dtype=float)
                if target.shape != (len(frames), 3):
                    return {**empty, 'report': {
                        'available': False,
                        'reason': f'{side}_native_camera_yaw_anchor_invalid',
                    }}
                paired_frames = (set(np.asarray(mirror_pair['frames'], dtype=int).tolist())
                                 if mirror_pair is not None else set())
                selected_independent = float(raw_yaw)
                for frame_index, frame in enumerate(frames):
                    rotation = orientation_by_frame.get(int(frame))
                    if rotation is None:
                        return {**empty, 'report': {
                            'available': False,
                            'reason': f'{side}_native_camera_yaw_orientation_missing',
                        }}
                    frame_yaw = (float(coupled_yaw_by_side[side])
                                 if int(frame) in paired_frames and side in coupled_yaw_by_side
                                 else selected_independent)
                    yaw_rotation = Rotation.from_rotvec(
                        _unit(np.asarray(entry['episode']['surfaceNormal'], dtype=float))
                        * frame_yaw).as_matrix()
                    derived_targets[frame, ankle_i] = target[frame_index] + yaw_rotation @ (
                        derived_targets[frame, ankle_i] - target[frame_index])
                    derived_targets[frame, toe_i] = target[frame_index] + yaw_rotation @ (
                        derived_targets[frame, toe_i] - target[frame_index])
                    orientation_by_frame[int(frame)] = yaw_rotation @ rotation
            orientations[side] = {
                'frames': np.asarray(sorted(orientation_by_frame), dtype=int),
                'worldRotations': np.asarray([
                    orientation_by_frame[frame]
                    for frame in sorted(orientation_by_frame)
                ], dtype=float),
                'localMaterialAxes': np.asarray([
                    local_axis_by_frame[frame]
                    for frame in sorted(orientation_by_frame)
                ], dtype=float),
            }
            report_sides[side]['appliedCameraYawRadians'] = yaw
            if mirror_pair is not None and side in coupled_yaw_by_side:
                camera_yaw_report['bySide'][side]['independentSelectedYawRadians'] = (
                    selected_independent)
                camera_yaw_report['bySide'][side]['yawRadians'] = yaw
                camera_yaw_report['bySide'][side]['yawDegrees'] = float(np.degrees(yaw))
    mirrored_report = None
    # A verified mirrored-leg contract may infer the unsupported foot's
    # orientation from the one qualified full-sole side. These are transient
    # solver targets, not observations: the caller's pin mask and source
    # evidence remain unchanged, and any actual opposite-side support wins.
    if native_foot_mirror_required is True and len(coverage) == 1:
        owner = next(iter(coverage))
        inferred = 'right' if owner == 'left' else 'left'
        owner_track = native_foot_tracks.get(owner) or {}
        inferred_track = native_foot_tracks.get(inferred) or {}
        inferred_active = np.asarray(inferred_track.get('active', ()), dtype=bool)
        if (inferred_active.shape == (count,)
                and f'{owner}_hip' in rig.names and f'{inferred}_hip' in rig.names):
            owner_ankle, owner_toe = (rig.names.index(f'{owner}_ankle'),
                                      rig.names.index(f'{owner}_foot'))
            inferred_ankle, inferred_toe = (rig.names.index(f'{inferred}_ankle'),
                                            rig.names.index(f'{inferred}_foot'))
            left_hip, right_hip = (rig.names.index('left_hip'),
                                   rig.names.index('right_hip'))
            current_world = rig.global_rotations(coordinates)
            owner_desired = {}
            owner_orientation = orientations.get(owner)
            if owner_orientation is not None:
                owner_desired = {
                    int(frame): rotation for frame, rotation in zip(
                        np.asarray(owner_orientation['frames'], dtype=int),
                        np.asarray(owner_orientation['worldRotations'], dtype=float))
                }
            inferred_foot_index = rig.names.index(f'{inferred}_foot')
            rows, inferred_forward, inferred_world, inferred_local_axes = [], [], [], []
            for entry in coverage[owner]:
                for frame in np.asarray(entry['frames'], dtype=int):
                    if (inferred_active[frame] or pinned[frame, inferred_ankle]
                            or not pinned[frame, inferred_toe]):
                        continue
                    owner_rotation = owner_desired.get(int(frame))
                    if owner_rotation is None:
                        continue
                    hip_axis = points[frame, right_hip] - points[frame, left_hip]
                    # Canonical stance reflection is a vertical sagittal plane,
                    # matching the level-plane normal used by the support
                    # residual and _native_fullsole_mirror_pair. Hip height
                    # asymmetry must not tilt the mirror and leak a vertical
                    # error into the inferred opposite foot.
                    hip_axis[1] = 0.
                    hip_length = float(np.linalg.norm(hip_axis))
                    owner_bone = (derived_targets[frame, owner_toe]
                                  - derived_targets[frame, owner_ankle])
                    owner_length = float(np.linalg.norm(owner_bone))
                    inferred_length = float(np.linalg.norm(
                        points[frame, inferred_toe] - points[frame, inferred_ankle]))
                    if min(hip_length, owner_length, inferred_length) <= _EPS:
                        return {**empty, 'report': {
                            'available': False,
                            'reason': 'mirrored_native_foot_geometry_unresolved',
                        }}
                    normal = hip_axis / hip_length
                    forward = owner_bone / owner_length
                    reflected = forward - 2. * float(np.dot(forward, normal)) * normal
                    reflected_length = float(np.linalg.norm(reflected))
                    if reflected_length <= _EPS:
                        return {**empty, 'report': {
                            'available': False,
                            'reason': 'mirrored_native_foot_direction_unresolved',
                        }}
                    reflected /= reflected_length
                    owner_delta = owner_rotation @ current_world[owner_toe][frame].T
                    owner_lateral = owner_delta @ current_axes[owner][frame]
                    reflected_lateral = -(owner_lateral - 2. * float(
                        np.dot(owner_lateral, normal)) * normal)
                    source_forward = points[frame, inferred_toe] - points[frame, inferred_ankle]
                    source_forward /= inferred_length
                    source_lateral = current_axes[inferred][frame].copy()
                    source_lateral -= source_forward * float(np.dot(source_lateral, source_forward))
                    source_lateral_length = float(np.linalg.norm(source_lateral))
                    target_lateral = reflected_lateral - reflected * float(
                        np.dot(reflected_lateral, reflected))
                    target_lateral_length = float(np.linalg.norm(target_lateral))
                    if min(source_lateral_length, target_lateral_length) <= _EPS:
                        return {**empty, 'report': {
                            'available': False,
                            'reason': 'mirrored_native_foot_axes_unresolved',
                        }}
                    source_lateral /= source_lateral_length
                    target_lateral /= target_lateral_length
                    delta = Rotation.align_vectors(
                        np.stack((reflected, target_lateral)),
                        np.stack((source_forward, source_lateral)))[0].as_matrix()
                    rows.append(int(frame))
                    inferred_forward.append(reflected)
                    inferred_world.append(delta @ current_world[
                        inferred_foot_index][frame])
                    # Express the source material side axis in the inferred
                    # foot's local frame so the shared twist encoder can roll
                    # the mirrored foot onto the reflected lateral target. The
                    # single-coverage branch must carry this axis; otherwise the
                    # encoder skips the inferred foot and the source roll leaks
                    # into the mirror residual.
                    inferred_local_axes.append(np.einsum(
                        'ji,j->i', current_world[inferred_foot_index][frame],
                        current_axes[inferred][frame]))
            if rows:
                rows = np.asarray(rows, dtype=int)
                inferred_forward = np.asarray(inferred_forward, dtype=float)
                inferred_local_axes = np.asarray(inferred_local_axes, dtype=float)
                toe_target = contact_targets[rows, inferred_toe].copy()
                ankle_target = toe_target - inferred_forward * np.linalg.norm(
                    points[rows, inferred_toe] - points[rows, inferred_ankle],
                    axis=1)[:, None]
                derived_pins[rows, inferred_ankle] = True
                derived_pins[rows, inferred_toe] = True
                derived_targets[rows, inferred_ankle] = ankle_target
                derived_targets[rows, inferred_toe] = toe_target
                inferred_foot = inferred_foot_index
                inferred_rotations = np.asarray(inferred_world, dtype=float)
                if inferred in orientations:
                    old_frames = np.asarray(orientations[inferred]['frames'], dtype=int)
                    orientations[inferred] = {
                        'frames': np.concatenate((old_frames, rows)),
                        'worldRotations': np.concatenate((
                            np.asarray(orientations[inferred]['worldRotations'], dtype=float),
                            inferred_rotations), axis=0),
                        'localMaterialAxes': np.concatenate((
                            np.asarray(orientations[inferred]['localMaterialAxes'],
                                       dtype=float),
                            inferred_local_axes), axis=0),
                    }
                else:
                    orientations[inferred] = {
                        'frames': rows,
                        'worldRotations': inferred_rotations,
                        'localMaterialAxes': inferred_local_axes,
                    }
                mirrored_report = {
                    'ownerSide': owner,
                    'inferredSide': inferred,
                    'frameCount': int(len(rows)),
                    'sourceObservationsAdded': 0,
                    'explicitPinSkippedFrameCount': len({
                        int(frame)
                        for entry in coverage[owner]
                        for frame in np.asarray(entry['frames'], dtype=int)
                        if pinned[int(frame), inferred_ankle]
                    }),
                }
    if mirror_pair is not None:
        # Both feet have observed stationary full-sole episodes. Build the
        # second target in the first side's calibrated material frame, while
        # retaining the second side's own measured material anchor and plane.
        # This couples bilateral geometry without replacing either contact.
        left_world = orientations.get('left')
        right_world = orientations.get('right')
        if left_world is not None and right_world is not None:
            current_world = rig.global_rotations(coordinates)

            def orientation_cost(side, values):
                frames = np.asarray(values['frames'], dtype=int)
                rotations = np.asarray(values['worldRotations'], dtype=float)
                foot_index = rig.names.index(f'{side}_foot')
                deltas = np.einsum(
                    'fij,fjk->fik', rotations,
                    np.swapaxes(current_world[foot_index][frames], 1, 2))
                return float(np.sum(Rotation.from_matrix(deltas).magnitude()))

            owner = min(('left', 'right'), key=lambda side: (
                orientation_cost(side, orientations[side]), side))
            inferred = 'right' if owner == 'left' else 'left'
            owner_entry = mirror_pair[owner]
            inferred_entry = mirror_pair[inferred]
            owner_toe = rig.names.index(f'{owner}_foot')
            owner_ankle = rig.names.index(f'{owner}_ankle')
            inferred_toe = rig.names.index(f'{inferred}_foot')
            inferred_ankle = rig.names.index(f'{inferred}_ankle')
            owner_orientation = orientations[owner]
            owner_rotations = {
                int(frame): rotation for frame, rotation in zip(
                    np.asarray(owner_orientation['frames'], dtype=int),
                    np.asarray(owner_orientation['worldRotations'], dtype=float))}
            inferred_frames = np.asarray(inferred_entry['frames'], dtype=int)
            inferred_indexes = {
                int(frame): index for index, frame in enumerate(inferred_frames)}
            inferred_side_geometry = (geometry.get('sides') or {}).get(inferred)
            if inferred_side_geometry is None:
                return {**empty, 'report': {
                    'available': False,
                    'reason': 'mirrored_native_fullsole_pair_geometry_unavailable',
                }}
            inferred_shoes = shoe_vertices(
                points[:, rig.names.index(f'{inferred}_ankle')],
                points[:, rig.names.index(f'{inferred}_foot')],
                np.asarray(current_axes[inferred], dtype=float), None, scale,
                native_geometry=inferred_side_geometry)
            inferred_sole = inferred_shoes[:, _NATIVE_SHOE_SOLE_RING_VERTICES]
            inferred_centered = inferred_sole - inferred_sole.mean(axis=1, keepdims=True)
            _, _, inferred_plane_axes = np.linalg.svd(
                inferred_centered, full_matrices=False)
            inferred_normals = inferred_plane_axes[:, -1, :]
            inferred_forward_rows = points[:, inferred_toe] - points[:, inferred_ankle]
            inferred_forward_rows /= np.maximum(
                np.linalg.norm(inferred_forward_rows, axis=1, keepdims=True), _EPS)
            inferred_lateral_rows = np.asarray(current_axes[inferred], dtype=float)
            inferred_lateral_rows -= inferred_forward_rows * np.sum(
                inferred_lateral_rows * inferred_forward_rows, axis=1, keepdims=True)
            inferred_lateral_rows /= np.maximum(
                np.linalg.norm(inferred_lateral_rows, axis=1, keepdims=True), _EPS)
            inferred_up_rows = np.cross(inferred_lateral_rows, inferred_forward_rows)
            inferred_normals *= np.where(
                np.sum(inferred_normals * inferred_up_rows, axis=1) >= 0., 1., -1.)[:, None]
            inferred_material_axes = {}
            for frame_index, frame in enumerate(inferred_frames):
                inferred_material_axes[int(frame)] = np.asarray(
                    orientations[inferred]['localMaterialAxes'][frame_index], dtype=float)
            inferred_orientation_by_frame = {
                int(row): value for row, value in zip(
                    np.asarray(orientations[inferred]['frames'], dtype=int),
                    np.asarray(orientations[inferred]['worldRotations'], dtype=float))}
            for frame in np.asarray(mirror_pair['frames'], dtype=int):
                owner_rotation = owner_rotations.get(int(frame))
                if owner_rotation is None:
                    continue
                owner_bone = (derived_targets[frame, owner_toe]
                              - derived_targets[frame, owner_ankle])
                owner_length = float(np.linalg.norm(owner_bone))
                inferred_bone = points[frame, inferred_toe] - points[frame, inferred_ankle]
                inferred_length = float(np.linalg.norm(inferred_bone))
                if min(owner_length, inferred_length) <= _EPS:
                    return {**empty, 'report': {
                        'available': False,
                        'reason': 'mirrored_native_fullsole_pair_geometry_unresolved',
                    }}
                mirror_normal = np.asarray(mirror_pair['mirrorNormal'], dtype=float)
                owner_forward = owner_bone / owner_length
                reflected_forward = owner_forward - 2. * float(
                    np.dot(owner_forward, mirror_normal)) * mirror_normal
                reflected_forward_length = float(np.linalg.norm(reflected_forward))
                if reflected_forward_length <= _EPS:
                    return {**empty, 'report': {
                        'available': False,
                        'reason': 'mirrored_native_fullsole_pair_direction_unresolved',
                    }}
                reflected_forward /= reflected_forward_length
                source_forward = inferred_bone / inferred_length
                target_normal = _unit(np.asarray(
                    inferred_entry['episode']['surfaceNormal'], dtype=float))
                delta = _native_fullsole_material_rotation(
                    inferred_normals[frame], source_forward,
                    target_normal, reflected_forward)
                if delta is None:
                    return {**empty, 'report': {
                        'available': False,
                        'reason': 'mirrored_native_fullsole_pair_frame_unresolved',
                    }}
                inferred_index = inferred_indexes[int(frame)]
                target_material = np.asarray(
                    inferred_entry['targets'][inferred_index], dtype=float)
                source_material = np.asarray(
                    inferred_entry['material'][inferred_index], dtype=float)
                derived_targets[frame, inferred_ankle] = target_material + delta @ (
                    points[frame, inferred_ankle] - source_material)
                derived_targets[frame, inferred_toe] = target_material + delta @ (
                    points[frame, inferred_toe] - source_material)
                derived_pins[frame, inferred_ankle] = True
                derived_pins[frame, inferred_toe] = True
                inferred_material_axes[int(frame)] = np.einsum(
                    'ji,j->i', current_world[inferred_toe][frame],
                    current_axes[inferred][frame])
                inferred_world = delta @ current_world[inferred_toe][frame]
                inferred_orientation_by_frame[int(frame)] = inferred_world
            paired_rows = np.asarray(mirror_pair['frames'], dtype=int)
            ordered_frames = np.asarray(sorted(inferred_orientation_by_frame), dtype=int)
            orientations[inferred] = {
                'frames': ordered_frames,
                'worldRotations': np.asarray([
                    inferred_orientation_by_frame[int(frame)] for frame in ordered_frames]),
                'localMaterialAxes': np.asarray([
                    inferred_material_axes[int(frame)] for frame in ordered_frames]),
            }
            mirrored_report = {
                'ownerSide': owner,
                'inferredSide': inferred,
                'reference': 'overlapping_observed_bilateral_fullsole_material_frames',
                'frameCount': int(len(paired_rows)),
                'targetAnchorsPreserved': True,
                'sourceObservationsAdded': 0,
            }
            if camera_yaw_report is not None:
                camera_yaw_report['mirroredPairCoupling'] = {
                    'ownerSide': owner,
                    'inferredSide': inferred,
                    'frameCount': int(len(paired_rows)),
                    'appliedYawRadiansBySide': {
                        side: report_sides[side].get('appliedCameraYawRadians')
                        for side in ('left', 'right')},
                }
    if not report_sides:
        return empty
    report = {
        'available': True,
        'reference': 'qualified_native_fullsole_material_episode',
        'sides': report_sides,
    }
    if mirrored_report is not None:
        report['canonicalMirroredInference'] = mirrored_report
        if mirrored_report.get('reference') == (
                'overlapping_observed_bilateral_fullsole_material_frames'):
            report['mirroredPairCoupling'] = mirrored_report
    if camera_yaw_report is not None:
        report['sourceCameraYaw'] = camera_yaw_report
        if mirror_pair is not None and source_projection_constraint is not None:
            try:
                from .controlled_motion import _source_foot_ray_fit_evidence
                coupled_points = points.copy()
                for side in ('left', 'right'):
                    ankle_i, toe_i = (rig.names.index(f'{side}_ankle'),
                                      rig.names.index(f'{side}_foot'))
                    for entry in coverage[side]:
                        frames = np.asarray(entry['frames'], dtype=int)
                        coupled_points[frames, ankle_i] = derived_targets[frames, ankle_i]
                        coupled_points[frames, toe_i] = derived_targets[frames, toe_i]
                camera_yaw_report['sourceRayFitAfterMirroredPair'] = (
                    _source_foot_ray_fit_evidence(
                        coupled_points, source_projection_constraint))
            except (KeyError, TypeError, ValueError):
                camera_yaw_report['sourceRayFitAfterMirroredPair'] = {
                    'available': False, 'reason': 'coupled_source_ray_fit_unavailable'}
    return {
        'pins': derived_pins, 'targets': derived_targets,
        'orientations': orientations, 'coverage': coverage,
        'report': report,
    }


def _native_material_point_solver_constraints(
        rig, points, coordinates, pinned, contact_targets, *,
        native_foot_tracks, excluded_pins=None):
    """Seed ankle/toe targets for fully anchored native material points.

    A stationary native material episode (forefoot/heel) owns the rendered
    material point, not the whole sole plane and not the foot's heading. The
    playback sampler reconstructs that point from the episode's cached local
    offset expressed in the stored track direction and side axis; reproduce
    exactly that geometry so the continuous root track starts from the same
    placement playback will sample. Reusing the stored direction preserves the
    frame-varying toe/ankle pitch and heading instead of imposing a fabricated
    flat-sole frame.

    These ankle/toe pins are an *initializer seed only*. They are not the fit
    authority: promoting them into the main fit freezes an unobserved yaw that
    cannot coexist with the observed camera-ray heading. The fit instead keeps
    the calibrated actual-shoe material-point residual
    (``geometry_constraint_errors``), which leaves the legal foot rotation about
    that point free; ``initialize_joint_plant_coordinates`` excludes these seed
    pins from the ``native_fullsole_constraint_capture`` handoff.

    Only fully anchored ``stationary`` episodes with ``targetWorld`` contribute
    full 3D seed pins. ``verticalOnly`` rows, released/unknown authority and
    rows already owned by an explicit pin stay on their existing paths, and the
    caller's observed pin mask/evidence are never modified.
    """
    empty_targets = np.asarray(contact_targets, dtype=float).copy()
    empty = {
        'pins': np.asarray(pinned, dtype=bool).copy(),
        'targets': empty_targets,
        'coverage': {},
        'report': {'available': False, 'sides': {}},
    }
    if (not isinstance(native_foot_tracks, dict)
            or native_foot_tracks.get('version') != 2):
        return empty
    from .contact_interpolation import _validated_native_side_track
    count = len(points)
    occupied = np.asarray(pinned, dtype=bool).copy()
    if excluded_pins is not None:
        excluded = np.asarray(excluded_pins, dtype=bool)
        if excluded.shape == occupied.shape:
            occupied |= excluded
    derived_pins = np.asarray(pinned, dtype=bool).copy()
    derived_targets = empty_targets.copy()
    coverage, report_sides = {}, {}
    for side in ('left', 'right'):
        track = native_foot_tracks.get(side)
        if not isinstance(track, dict):
            continue
        ankle_name, toe_name = f'{side}_ankle', f'{side}_foot'
        if ankle_name not in rig.names or toe_name not in rig.names:
            continue
        try:
            active, directions, side_axes, anchor_ids = _validated_native_side_track(
                track, count, side)
        except (KeyError, TypeError, ValueError, IndexError):
            continue
        ankle_i, toe_i = rig.names.index(ankle_name), rig.names.index(toe_name)
        bone_length = float(np.linalg.norm(rig.offsets[toe_i]))
        if not np.isfinite(bone_length) or bone_length <= _EPS:
            continue
        anchor_ids = np.asarray(anchor_ids, dtype=object)
        frames = np.arange(count)
        side_derived = []
        side_entries = []
        skipped = 0
        kinds = {}
        for episode in track.get('episodes') or ():
            if not isinstance(episode, dict):
                continue
            mode = str(episode.get('mode'))
            # ``verticalOnly`` has no world anchor: keep the existing
            # height-only plane path and horizontal freedom.
            if mode != 'stationary':
                continue
            role = str(episode.get('regionRole'))
            if role == 'full_sole':
                # The qualified calibrated full-sole owner already derives its
                # rigid material frame in _native_fullsole_solver_constraints.
                continue
            try:
                start = int(episode['startFrame'])
                end = int(episode['endFrame'])
                local = np.asarray(episode['materialOffsetLocalMeters'], dtype=float)
                reference = float(episode['referenceLengthMeters'])
                target_world = np.asarray(episode['targetWorld'], dtype=float)
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
            if (local.shape != (3,) or not np.isfinite(local).all()
                    or not np.isfinite(reference) or reference <= _EPS
                    or target_world.shape != (3,) or not np.isfinite(target_world).all()):
                continue
            mask = active & (frames >= start) & (frames <= end)
            anchor = episode.get('anchorId')
            if anchor is not None:
                mask &= anchor_ids == anchor
            rows = np.flatnonzero(mask)
            if not len(rows):
                continue
            eligible = rows[~occupied[rows, ankle_i] & ~occupied[rows, toe_i]]
            skipped += int(len(rows) - len(eligible))
            if not len(eligible):
                continue
            forward = directions[eligible]
            lateral = side_axes[eligible]
            up = np.cross(lateral, forward)
            offset = ((forward * local[0] + lateral * local[1] + up * local[2])
                      * (bone_length / reference))
            material = points[eligible, ankle_i] + offset
            ankle_target = points[eligible, ankle_i] + (target_world - material)
            toe_target = ankle_target + forward * bone_length
            if (not np.isfinite(ankle_target).all()
                    or not np.isfinite(toe_target).all()):
                continue
            derived_pins[eligible, ankle_i] = True
            derived_pins[eligible, toe_i] = True
            derived_targets[eligible, ankle_i] = ankle_target
            derived_targets[eligible, toe_i] = toe_target
            occupied[eligible, ankle_i] = True
            occupied[eligible, toe_i] = True
            side_derived.append(eligible)
            side_entries.append({'episode': episode, 'frames': eligible})
            kinds[f'{role}:stationary'] = kinds.get(f'{role}:stationary', 0) + 1
        if side_derived:
            coverage.setdefault(side, []).extend(side_entries)
            report_sides[side] = {
                'derivedSeedFrameCount': int(
                    sum(len(rows) for rows in side_derived)),
                'regionModes': kinds,
                'observedPinSkippedFrameCount': int(skipped),
                'reference': 'stored_playback_material_point_seed',
            }
    if not coverage:
        return empty
    return {
        'pins': derived_pins, 'targets': derived_targets,
        'coverage': coverage,
        'report': {
            'available': True,
            'reference': 'qualified_native_stationary_material_point_seed',
            'derivedSource': 'stored_playback_direction_and_side_axis',
            'pinsDerived': int(np.count_nonzero(derived_pins & ~np.asarray(
                pinned, dtype=bool))),
            'seedOnly': True,
            'fitAuthority': 'calibrated_material_point_residual',
            'orientationsAdded': False,
            'observedContactMaskChanged': False,
            'sides': report_sides,
        },
    }


def _native_plane_projection_targets(names, points, projection_tracks, coordinate_clock):
    """Transient plane-consistent targets for rows the emitted projection owns.

    ``project_supported_native_foot_coordinates(current_knee_pivot=True)``
    re-orbits the shank around the current knee so a native material point on a
    support-plane (``verticalOnly``) episode lands on the observed plane. That
    emitted placement authority must not be discovered only after the root
    track solved a different geometry: rows still owned by the projection get
    the same material-to-plane correction applied to their transient IK targets
    (XZ stays free, pins stay untouched), so the continuous root track and the
    hinge-direction feasibility model measure the geometry that is actually
    emitted. Fully anchored ``stationary`` episodes with ``targetWorld`` remain
    owned by ``_native_material_point_solver_constraints``/observed pins, and
    calibrated full-sole plane rows keep their dedicated rigid-solver path.
    Returns ``{side: [{'rows', 'axes', 'episode'}, ...]}`` mirroring the
    projector's episode gating, or ``{}`` when nothing is owned.
    """
    if (not isinstance(projection_tracks, dict)
            or projection_tracks.get('version') != 2):
        return {}
    from .supported_contact_rig import _episode_mask
    count = len(points)
    frames = np.arange(count)
    side_axes = _native_side_axes_for_coordinates(
        coordinate_clock['rig'], coordinate_clock['coordinates'],
        {'_nativeFootMaterialTracks': projection_tracks}) or {}
    result = {}
    for side in ('left', 'right'):
        track = projection_tracks.get(side)
        if not isinstance(track, dict) or side not in side_axes:
            continue
        ankle_name, toe_name = f'{side}_ankle', f'{side}_foot'
        if ankle_name not in names or toe_name not in names:
            continue
        active = np.asarray(track.get('active', ()), dtype=bool)
        if active.shape != (count,):
            raise ValueError(f'{side} native material track does not match the rig frame count')
        episodes = track.get('episodes') or ()
        if not isinstance(episodes, (list, tuple)):
            raise ValueError(f'{side} native material episodes are malformed')
        axes = np.asarray(side_axes[side], dtype=float)
        entries = []
        for episode in episodes:
            if not isinstance(episode, dict):
                raise ValueError(f'{side} native material episode is malformed')
            if ('targetWorld' in episode
                    or (str(episode.get('regionRole')) == 'full_sole'
                        and str(episode.get('mode')) == 'stationary'
                        and episode.get('soleNormalLocalMeters') is not None)):
                # XYZ-anchor rows are owned by the material-point solver path;
                # rigid full-sole rows re-solve the knee and are not a
                # shin-orbit plane correction.
                continue
            mask = _episode_mask(track, episode, active, active, frames, count)
            rows = np.flatnonzero(mask)
            if not len(rows):
                continue
            entries.append({'rows': rows, 'axes': axes[rows].copy(),
                            'episode': episode})
        if entries:
            result[side] = entries
    return result


def _native_tracks_without_solved_fullsole(native_foot_tracks, coverage):
    """Remove already encoded native material rows from a projector track copy."""
    if not coverage:
        return native_foot_tracks
    tracks = dict(native_foot_tracks)
    for side, entries in coverage.items():
        track = native_foot_tracks.get(side)
        if not isinstance(track, dict):
            continue
        count = len(track.get('active', ()))
        solved = np.zeros(count, dtype=bool)
        for entry in entries:
            solved[np.asarray(entry['frames'], dtype=int)] = True
        episodes = track.get('episodes') or ()
        if not isinstance(episodes, (list, tuple)):
            continue
        rebuilt = []
        anchor_ids = track.get('anchorIds')
        anchor_ids = (None if anchor_ids is None else np.asarray(anchor_ids, dtype=object))
        for episode in episodes:
            if not isinstance(episode, dict):
                rebuilt.append(episode)
                continue
            try:
                start, end = int(episode['startFrame']), int(episode['endFrame'])
            except (KeyError, TypeError, ValueError, OverflowError):
                rebuilt.append(episode)
                continue
            rows = np.arange(max(start, 0), min(end, count - 1) + 1)
            anchor = episode.get('anchorId')
            if anchor_ids is not None and anchor is not None:
                rows = rows[anchor_ids[rows] == anchor]
            rows = rows[~solved[rows]]
            if not len(rows):
                continue
            breaks = np.flatnonzero(np.diff(rows) != 1)
            starts = np.r_[rows[0], rows[breaks + 1]]
            ends = np.r_[rows[breaks], rows[-1]]
            for run_start, run_end in zip(starts, ends):
                if run_start == start and run_end == end:
                    rebuilt.append(episode)
                else:
                    rebuilt.append({**episode, 'startFrame': int(run_start),
                                    'endFrame': int(run_end)})
        tracks[side] = {**track, 'episodes': rebuilt}
    return tracks


def _native_fullsole_encoded_check(
        rig, encoded, coverage, native_foot_tracks, native_foot_geometry, foot_scale):
    """Validate encoded material anchors and rendered sole-plane samples."""
    from .body_surface_geometry import evaluate_contact_patch
    from .foot_geometry import shoe_vertices
    from .material_region_support import shoe_triangles
    from .native_foot_geometry import validated_native_foot_geometry
    from .support_geometry import (
        _NATIVE_SHOE_SOLE_RING_VERTICES, _native_side_axes_for_coordinates,
    )
    geometry = validated_native_foot_geometry(native_foot_geometry)
    if geometry is None:
        return {'passed': False, 'reason': 'native_foot_geometry_unavailable'}
    points = rig.decode(encoded)
    try:
        axes = _native_side_axes_for_coordinates(
            rig, encoded, {'_nativeFootMaterialTracks': native_foot_tracks})
    except (KeyError, TypeError, ValueError) as error:
        return {'passed': False, 'reason': f'native_side_axes_unavailable:{error}'}
    if not axes:
        return {'passed': False, 'reason': 'native_side_axes_unavailable'}
    triangles = shoe_triangles()
    maximum_anchor = 0.
    maximum_sole = 0.
    maximum_stationarity = 0.
    by_side = {}
    for side, entries in coverage.items():
        track = native_foot_tracks.get(side)
        side_geometry = (geometry.get('sides') or {}).get(side)
        basis = axes.get(side)
        if not isinstance(track, dict) or side_geometry is None or basis is None:
            return {'passed': False, 'reason': f'{side}_native_geometry_unavailable'}
        ankle_i, toe_i = (rig.names.index(f'{side}_ankle'),
                          rig.names.index(f'{side}_foot'))
        try:
            shoes = shoe_vertices(
                points[:, ankle_i], points[:, toe_i], np.asarray(basis, dtype=float),
                None, float(foot_scale), native_geometry=side_geometry)
        except (TypeError, ValueError) as error:
            return {'passed': False, 'reason': f'{side}_shoe_geometry_unavailable:{error}'}
        side_anchor, side_sole, side_stationarity = 0., 0., 0.
        for entry in entries:
            episode = entry['episode']
            frames = np.asarray(entry['frames'], dtype=int)
            stationarity_frames = np.asarray(
                entry.get('stationarityFrames', frames), dtype=int)
            try:
                target_normal = _unit(np.asarray(episode['surfaceNormal'], dtype=float))
                primitive_id = str(episode['primitiveId'])
                material = evaluate_contact_patch(
                    {primitive_id: {'vertices': shoes, 'triangles': triangles}},
                    {'primitiveId': primitive_id,
                     'points': [{'triangleIndex': int(episode['triangleIndex']),
                                 'barycentric': list(episode['barycentric'])}]})[:, 0]
            except (KeyError, TypeError, ValueError) as error:
                return {'passed': False,
                        'reason': f'{side}_native_patch_unavailable:{error}'}
            target = _native_fullsole_target(episode, material, target_normal)
            if target is None:
                return {'passed': False, 'reason': f'{side}_native_target_unavailable'}
            anchor = float(np.max(
                np.linalg.norm(material[frames] - target[frames], axis=1), initial=0.))
            offset = episode.get('planeOffsetMeters')
            if offset is None:
                offset = float(np.asarray(episode['targetWorld'], dtype=float) @ target_normal)
            plane = float(np.max(np.abs(
                shoes[frames][:, _NATIVE_SHOE_SOLE_RING_VERTICES] @ target_normal
                - float(offset)), initial=0.))
            if str(episode.get('mode')) == 'stationary':
                sole_points = shoes[stationarity_frames][:, _NATIVE_SHOE_SOLE_RING_VERTICES]
                stationarity = float(np.max(np.linalg.norm(
                    sole_points - sole_points[:1], axis=-1), initial=0.))
                side_stationarity = max(side_stationarity, stationarity)
            side_anchor = max(side_anchor, anchor)
            side_sole = max(side_sole, plane)
        maximum_anchor = max(maximum_anchor, side_anchor)
        maximum_sole = max(maximum_sole, side_sole)
        maximum_stationarity = max(maximum_stationarity, side_stationarity)
        by_side[side] = {
            'maximumAnchorErrorMeters': side_anchor,
            'maximumSolePlaneErrorMeters': side_sole,
            'maximumSoleMaterialStationarityMeters': side_stationarity,
        }
    return {
        'passed': bool(
            maximum_anchor <= _NATIVE_FULLSOLE_TOLERANCE_METERS
            and maximum_sole <= _NATIVE_FULLSOLE_TOLERANCE_METERS
            and maximum_stationarity <= _NATIVE_FULLSOLE_TOLERANCE_METERS),
        'maximumAnchorErrorMeters': maximum_anchor,
        'maximumSolePlaneErrorMeters': maximum_sole,
        'maximumSoleMaterialStationarityMeters': maximum_stationarity,
        'toleranceMeters': _NATIVE_FULLSOLE_TOLERANCE_METERS,
        'bySide': by_side,
    }


def _encode_native_fullsole_material_twists(rig, coordinates, orientations):
    """Align native material lateral axes without moving solved foot points."""
    encoded = np.asarray(coordinates, dtype=float).copy()
    if not isinstance(orientations, dict):
        return encoded
    world = rig.global_rotations(encoded)
    for side, values in orientations.items():
        try:
            frames = np.asarray(values['frames'], dtype=int)
            desired_world = np.asarray(values['worldRotations'], dtype=float)
            local_axes = np.asarray(values['localMaterialAxes'], dtype=float)
        except (KeyError, TypeError, ValueError):
            continue
        if (frames.ndim != 1 or desired_world.shape != (len(frames), 3, 3)
                or local_axes.shape != (len(frames), 3)
                or not np.isfinite(desired_world).all()
                or not np.isfinite(local_axes).all()
                or np.any(frames < 0) or np.any(frames >= len(encoded))):
            return None
        foot = rig.names.index(f'{side}_foot')
        ankle = rig.names.index(f'{side}_ankle')
        if foot not in rig.slots or ankle not in rig.parents:
            return None
        offset = np.asarray(rig.offsets[foot], dtype=float)
        offset_length = float(np.linalg.norm(offset))
        if offset_length <= _EPS:
            return None
        current_world = world[foot][frames]
        forward = np.einsum('fij,j->fi', current_world, offset / offset_length)
        current_axis = np.einsum('fij,fj->fi', current_world, local_axes)
        target_axis = np.einsum('fij,fj->fi', desired_world, local_axes)
        current_lateral = current_axis - forward * np.sum(
            current_axis * forward, axis=1, keepdims=True)
        target_lateral = target_axis - forward * np.sum(
            target_axis * forward, axis=1, keepdims=True)
        current_length = np.linalg.norm(current_lateral, axis=1)
        target_length = np.linalg.norm(target_lateral, axis=1)
        if np.any(current_length <= _EPS) or np.any(target_length <= _EPS):
            return None
        current_lateral /= current_length[:, None]
        target_lateral /= target_length[:, None]
        sine = np.sum(forward * np.cross(current_lateral, target_lateral), axis=1)
        cosine = np.clip(np.sum(current_lateral * target_lateral, axis=1), -1., 1.)
        angles = np.arctan2(sine, cosine)
        corrected_world = (Rotation.from_rotvec(forward * angles[:, None])
                           * Rotation.from_matrix(current_world)).as_matrix()
        parent_world = world[ankle][frames]
        local = np.einsum('fji,fjk->fik', parent_world, corrected_world)
        slot = rig.slots[foot]
        encoded[frames, slot:slot + 3] = Rotation.from_matrix(local).as_rotvec()
    return encoded


def _make_specs(names, points, pinned, targets, reference, *,
                desired_world_foot_directions=None, pitch_authority_mask_by_side=None,
                pitch_trajectory_mask_by_side=None, cyclic=False, floor_y=None,
                rest_pitch_radians=None, foot_scale=None, side_axis_by_side=None, fps=30.,
                direction_authority=None, native_projection_targets=None):
    index = {name: i for i, name in enumerate(names)}
    specs, preflight = [], {}
    directions = (None if desired_world_foot_directions is None else
                  np.asarray(desired_world_foot_directions, dtype=float))
    if directions is not None and directions.shape != (len(points), 2, 3):
        raise ValueError('desired foot directions must have shape (frames, 2, 3)')
    side_axes = (None if side_axis_by_side is None else
                 np.asarray(side_axis_by_side, dtype=float))
    if rest_pitch_radians is None:
        rest_pitch_radians = {}
    if floor_y is not None:
        if (side_axes is None or side_axes.shape != (len(points), 2, 3)
                or not isinstance(rest_pitch_radians, dict)
                or any(side not in ('left', 'right') for side in rest_pitch_radians)
                or any(not np.isfinite(float(value))
                       for value in rest_pitch_radians.values())
                or foot_scale is None or not np.isfinite(float(floor_y))
                or not np.isfinite(float(foot_scale)) or float(foot_scale) <= 0.
                or not np.isfinite(fps) or fps <= 0.):
            raise ValueError('material floor correction requires finite floor, optional pitch, scale, and side axes')
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
        knee_spec = next(row for row in ARTICULATIONS if row[0] == f'{side}_knee')
        source_knee_angles = angles(reference[:, hip_i], reference[:, knee_i], reference[:, ankle_i])
        knee_low, knee_high = source_articulation_fit_bounds(
            source_knee_angles[:, None], [(knee_spec[0], (hip_i, knee_i, ankle_i), knee_spec[4])])
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
        target_toe[ankle_only] = target_ankle[ankle_only] + source_vector[ankle_only]
        target_ankle[toe_only] = target_toe[toe_only] - source_vector[toe_only]
        # Root correction moves the hip, not a released foot's world trajectory.
        # Interpolate placement only; source-clock pitch and heading stay intact.
        source_ankle = points[:, ankle_i].copy()
        # The caller already transported measured direction corrections over
        # the source clock. Keep that angular authority separate from placement.
        source_toe = source_ankle + source_vector
        target_ankle, target_toe = _carry_contact_placement(
            source_ankle, source_toe, target_ankle, target_toe,
            owned, ankle_owned=ankle_pin, cyclic=cyclic)
        floor_corrections = np.zeros(len(points), dtype=float)
        if floor_y is not None:
            from .foot_geometry import free_foot_floor_translation
            free = ~owned
            for frame in np.flatnonzero(free):
                floor_corrections[frame] = free_foot_floor_translation(
                    target_ankle[frame], target_toe[frame], floor_y=floor_y,
                    rest_pitch_radians=rest_pitch_radians.get(side),
                    foot_scale=foot_scale, side_axis=side_axes[frame, side_index])
            target_ankle[free, 1] += floor_corrections[free]
            target_toe[free, 1] += floor_corrections[free]
        # Rows still owned by the emitted native-foot projection (support-plane
        # episodes without an XYZ anchor) share their placement authority with
        # the root solve: correct the transient IK targets by the same
        # material-to-plane shift the projector applies.  Only unowned rows are
        # touched (pins stay pins, XZ stays free), the foot vector is translated
        # rigidly so pose/length preflight stays identical, and the emitted
        # projection then measures the same geometry the continuous root track
        # solved instead of discovering a post-solve ankle move at postcheck.
        if (native_projection_targets or {}).get(side):
            from .supported_contact_rig import _episode_targets, _material_points
            for entry in native_projection_targets[side]:
                entry_rows = np.asarray(entry['rows'], dtype=int)
                unowned = ~owned[entry_rows]
                rows = entry_rows[unowned]
                if not len(rows):
                    continue
                material = _material_points(target_ankle[rows], target_toe[rows],
                                            np.asarray(entry['axes'], dtype=float)[unowned],
                                            entry['episode'])
                delta = _episode_targets(entry['episode'], material) - material
                target_ankle[rows] += delta
                target_toe[rows] += delta
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
        qualified = owned.copy()
        if direction_authority is not None:
            qualified &= np.all(np.asarray(direction_authority)[:, [ankle_i, toe_i]], axis=1)
        pose = _foot_pose_report(source_local[qualified], target_local[qualified])
        allowed = next(float(row[4]) for row in ARTICULATIONS if row[0] == f'{side}_ankle')
        max_heading = float(np.max(np.abs(pose['headingDeltaDegrees']), initial=0.))
        max_pitch = float(np.max(np.abs(pose['pitchDeltaDegrees']), initial=0.))
        p95_heading = (float(np.percentile(np.abs(pose['headingDeltaDegrees']), 95))
                       if np.any(qualified) else 0.)
        p95_pitch = (float(np.percentile(np.abs(pose['pitchDeltaDegrees']), 95))
                     if np.any(qualified) else 0.)
        pair_error = float(np.max(np.abs(target_length[both] - fixed_foot_length), initial=0.))
        preflight[side] = {
            'activeFrames': int(owned.sum()), 'bothEndpointsPinnedFrames': int(both.sum()),
            'sourceDirectionFrameCount': int(qualified.sum()),
            'fixedRigFootLengthMeters': fixed_foot_length,
            'maxPinnedPairLengthErrorMeters': pair_error,
            'medianSourceHeadingDegrees': (float(np.median(pose['sourceHeadingDegrees'])) if np.any(qualified) else None),
            'medianTargetHeadingDegrees': (float(np.median(pose['targetHeadingDegrees'])) if np.any(qualified) else None),
            'medianSourcePitchDegrees': (float(np.median(pose['sourcePitchDegrees'])) if np.any(qualified) else None),
            'medianTargetPitchDegrees': (float(np.median(pose['targetPitchDegrees'])) if np.any(qualified) else None),
            'maxSourceHeadingDeltaDegrees': max_heading,
            'maxSourcePitchDeltaDegrees': max_pitch,
            'p95SourceHeadingDeltaDegrees': p95_heading,
            'p95SourcePitchDeltaDegrees': p95_pitch,
            'maximumHeadingDeltaDegrees': max_heading,
            'maximumPitchDeltaDegrees': max_pitch,
            'maxHeadingDeltaDegrees': max_heading,
            'maxPitchDeltaDegrees': max_pitch,
            'materialFloorCorrection': {
                'frameCount': int(np.count_nonzero(floor_corrections)),
                'maximumTranslationMeters': float(np.max(floor_corrections, initial=0.)),
                'timeSpanSeconds': ([float(np.flatnonzero(floor_corrections)[0] / fps),
                                     float(np.flatnonzero(floor_corrections)[-1] / fps)]
                                    if np.any(floor_corrections) else None),
            },
        }
        # The same immutable pre-support limits used by the independent guard
        # bound contact-owned foot pose. A contradictory target must be fixed at
        # its evidence owner, not accommodated by changing valid articulation.
        if pair_error > 1e-5 or p95_heading > allowed or p95_pitch > allowed:
            return None, {'feasible': False, 'reason': f'{side}_contact_target_changes_source_foot_pose',
                          'preflight': preflight,
                          'sourceTargetEvidence': {key: np.asarray(value).tolist()
                                                   for key, value in pose.items()}}
        source_axis = _unit(points[:, ankle_i] - points[:, hip_i])
        source_knee_rel = points[:, knee_i] - points[:, hip_i]
        source_knee_height = np.linalg.norm(
            source_knee_rel
            - np.sum(source_knee_rel * source_axis, axis=1, keepdims=True) * source_axis,
            axis=1)
        specs.append({
            'side': side, 'indices': (hip_i, knee_i, ankle_i, toe_i),
            'hip': points[:, hip_i], 'knee': points[:, knee_i],
            'ankle': points[:, ankle_i], 'toe': points[:, toe_i],
            'targetAnkle': target_ankle, 'targetToe': target_toe,
            'activeContact': owned.copy(),
            # Released pose targets carry source motion and clearance, not support.
            'activePoseTarget': np.ones(len(points), dtype=bool),
            'ankleFollowsRoot': np.zeros(len(points), dtype=bool),
            'toeFollowsRoot': np.zeros(len(points), dtype=bool),
            'thigh': np.linalg.norm(points[:, knee_i] - points[:, hip_i], axis=1),
            'shin': np.linalg.norm(points[:, ankle_i] - points[:, knee_i], axis=1),
            'pole': _unit(poles), 'sourceAxis': source_axis,
            # Source-reference knee bend inferred from the source points
            # (perpendicular offset from the hip-ankle line). Common-root
            # selection prefers keeping this bend instead of silently flattening
            # it at the outer reach singularity.
            'sourceKneeHeight': source_knee_height,
            'referenceKneeAngle': source_knee, 'referenceAnkleAngle': source_ankle,
            'kneeLower': knee_low[:, 0], 'kneeUpper': knee_high[:, 0],
            # Feasibility and its interior preference must use the same interval.
            # The old broad phase target is unattainable inside a narrower source envelope.
            'kneeMarginTarget': ((knee_high[:, 0] - knee_low[:, 0]) * .5
                                 + np.deg2rad(_INTERIOR_MARGIN_DEGREES)),
            'kneeTolerance': np.deg2rad(next(float(row[4]) for row in ARTICULATIONS
                                              if row[0] == f'{side}_knee')),
            'ankleTolerance': np.deg2rad(allowed),
        })
    root_seed = root_seed_sum / np.maximum(root_seed_count[:, None], 1.)
    from .controlled_motion import hinge_coordinates, source_hinge_reliability
    from .physical_validation import hinge_direction_mask
    source_parent, source_bend, source_sine = hinge_coordinates(reference, names)
    reliable = source_hinge_reliability(source_parent, source_bend, source_sine, fps)
    if direction_authority is not None:
        reliable &= hinge_direction_mask(np.asarray(direction_authority, dtype=bool), names)
    hinge_context = (names, points, source_parent, source_bend, reliable)
    for spec in specs:
        spec['rootSeed'] = root_seed
        spec['sourceHingeContext'] = hinge_context
    return specs, {'feasible': bool(specs), 'feet': preflight}


def _root_track(specs, count, deadline, cyclic, fps, *, _cache_frame_state=True,
                seed_offsets=None):
    """Solve the common-root offset track, preferring a physically feasible seed.

    ``seed_offsets`` re-encodes an already-computed per-frame feasible track
    instead of solving it again. That path exists so the initializer can retain
    its feasible seed when cyclic smoothing would break the induced joint
    boundary; every frame is still re-validated against the same constraints.
    """
    bounds = [(-_ROOT_LIMIT_METERS, _ROOT_LIMIT_METERS)] * 3
    translations = np.zeros((count, 3), dtype=float)
    provided_seed = seed_offsets is not None

    if _cache_frame_state:
        from functools import lru_cache

        @lru_cache(maxsize=8192)
        def cached_frame_state(frame, x, y, z):
            margins, knees = _frame_state(
                specs, frame, np.asarray((x, y, z), dtype=float))
            margins.setflags(write=False)
            if knees is not None:
                knees.setflags(write=False)
            return margins, knees

    def frame_state(frame, value):
        if monotonic() >= deadline:
            raise TimeoutError('joint plant root frame-state evaluation exceeded deadline')
        value = np.asarray(value, dtype=float)
        if not _cache_frame_state or not np.isfinite(value).all():
            return _frame_state(specs, frame, value)
        # Float keys retain the exact optimizer input; no quantization can
        # merge distinct feasibility points.
        return cached_frame_state(
            int(frame), float(value[0]), float(value[1]), float(value[2]))

    def feasible(frame, value, tolerance=-_ROOT_FEASIBILITY_TOLERANCE_RADIANS):
        margins, knees = frame_state(frame, value)
        active = any(spec.get('activePoseTarget', spec.get('activeContact')) is not None
                     and spec.get('activePoseTarget', spec.get('activeContact'))[frame]
                     for spec in specs)
        return ((not active or knees is not None)
                and np.min(margins) >= tolerance)

    if provided_seed:
        candidate = np.asarray(seed_offsets, dtype=float)
        if candidate.shape != (count, 3) or not np.isfinite(candidate).all():
            return None, {'feasible': False, 'reason': 'provided_root_seed_invalid'}
        translations[:] = candidate
        for frame in range(count):
            if monotonic() >= deadline:
                raise TimeoutError('joint plant root seed validation exceeded deadline')
            if feasible(frame, translations[frame]):
                continue
            margins = frame_state(frame, translations[frame])[0]
            return None, {'feasible': False, 'reason': 'provided_root_seed_not_feasible',
                          'frame': frame,
                          'minimumMarginDegrees': float(np.rad2deg(np.min(margins)))}
    else:
        for frame in range(count):
            if monotonic() >= deadline:
                raise TimeoutError('joint plant root feasibility exceeded deadline')
            if (feasible(frame, np.zeros(3), tolerance=-1e-8)
                    and all(np.max(np.abs(spec['targetAnkle'][frame] - spec['ankle'][frame]), initial=0.) < 1e-10
                            and np.max(np.abs(spec['targetToe'][frame] - spec['toe'][frame]), initial=0.) < 1e-10
                            for spec in specs)):
                continue
            def frame_margins(value, f=frame):
                if monotonic() >= deadline:
                    raise TimeoutError('joint plant frame feasibility exceeded deadline')
                return frame_state(f, value)[0]

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
                all_margins, knees = frame_state(frame, value)
                current_margins = all_margins[:2*len(specs)]
                tolerance = np.asarray([
                    item for spec in specs for item in
                    ((spec['kneeMarginTarget'][frame] if 'kneeMarginTarget' in spec
                      else spec['kneeTolerance']), spec['ankleTolerance'])])
                delta = np.maximum(tolerance - np.deg2rad(_INTERIOR_MARGIN_DEGREES)
                                   - current_margins, 0.)
                bend = _root_bend_deviation(specs, frame, value, knees)
                return (float(delta @ delta)
                        + _ROOT_COST_WEIGHT * (value @ value) / (_ROOT_LIMIT_METERS ** 2)
                        + bend)
            attempts = [minimize(cost, seed,
                                 method='SLSQP',
                                 bounds=bounds, constraints=constraints,
                                 options={'maxiter': 35, 'ftol': 1e-9, 'disp': False})
                        for seed in seeds]
            feasible_offsets = [np.asarray(result.x, dtype=float) for result in attempts
                                if feasible(frame, result.x)]
            if not feasible_offsets:
                margins = [np.min(frame_state(frame, result.x)[0]) for result in attempts]
                return None, {'feasible': False, 'frame': frame,
                              'bestMinimumMarginDegrees': float(np.rad2deg(max(margins)))}
            translations[frame] = min(feasible_offsets, key=cost)

    seed_translations = translations.copy()
    seed_margins = np.asarray([
        frame_state(frame, seed_translations[frame])[0]
        for frame in range(count)
    ])
    minimum_seed_margin = float(np.rad2deg(np.min(seed_margins)))
    rejected_projection_margins = []

    if count > 2 and not provided_seed:
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
            feasible_translations = translations.copy()
            projected = np.clip(smooth, -_ROOT_LIMIT_METERS, _ROOT_LIMIT_METERS)
            for frame in range(count):
                if monotonic() >= deadline:
                    raise TimeoutError('joint plant root smoothing exceeded deadline')
                if feasible(frame, projected[frame]):
                    continue
                def smooth_frame_margins(value, f=frame):
                    if monotonic() >= deadline:
                        raise TimeoutError('joint plant smoothing feasibility exceeded deadline')
                    return frame_state(f, value)[0]

                def smooth_objective(value, f=frame):
                    # Same soft source-reference bend preference as the
                    # per-frame seed cost, so cyclic smoothing does not restore
                    # the near-reach fold when a bend-preserving feasible
                    # projection exists.
                    _, smooth_knees = frame_state(f, value)
                    return (float(np.sum(((value - smooth[f]) / .02) ** 2))
                            + _root_bend_deviation(specs, f, value, smooth_knees))

                result = minimize(
                    smooth_objective,
                    projected[frame], method='SLSQP', bounds=bounds,
                    constraints=[{'type': 'ineq', 'fun': smooth_frame_margins}],
                    options={'maxiter': 30, 'ftol': 1e-9, 'disp': False})
                if feasible(frame, result.x):
                    projected[frame] = result.x
                else:
                    # Smoothing is only a preference for the initializer seed.
                    # Never replace a known-feasible root offset with a failed
                    # projection; the coupled fit still owns final validation.
                    rejected_projection_margins.append(float(np.rad2deg(
                        np.min(frame_state(frame, projected[frame])[0]))))
                    projected[frame] = feasible_translations[frame]
            translations = projected
            smooth = np.column_stack([np.asarray(
                spsolve(system.tocsc(), translations[:, axis])).ravel() for axis in range(3)])
        margin_rows = [frame_state(frame, projected[frame])
                       for frame in range(count)]
        margins = np.asarray([row[0] for row in margin_rows])
        if (not np.isfinite(margins).all() or np.min(margins) < -_ROOT_FEASIBILITY_TOLERANCE_RADIANS
                or any(not feasible(frame, projected[frame])
                       for frame in range(count))):
            return None, {'feasible': False, 'reason': 'smoothed_root_track_not_feasible',
                          'minimumMarginDegrees': float(np.rad2deg(np.nanmin(margins))),
                          'perFrameFeasibleSeedMinimumMarginDegrees': minimum_seed_margin,
                          'rejectedSmoothingProjectionCount': len(rejected_projection_margins),
                          'minimumRejectedSmoothingProjectionMarginDegrees': (
                              min(rejected_projection_margins, default=None)),
                          }
        translations = projected
    cyclic_differences = (np.diff(np.vstack((translations[-1:], translations)), axis=0)
                          if cyclic else np.diff(translations, axis=0))
    second_difference = ((np.roll(translations, 1, axis=0) - 2. * translations
                          + np.roll(translations, -1, axis=0)) if cyclic else
                         np.diff(translations, n=2, axis=0))
    smoothing_changed = bool(not provided_seed
                             and not np.array_equal(translations, seed_translations))
    report = {
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
        'perFrameFeasibleSeedMinimumMarginDegrees': minimum_seed_margin,
        'rejectedSmoothingProjectionCount': len(rejected_projection_margins),
        'minimumRejectedSmoothingProjectionMarginDegrees': (
            min(rejected_projection_margins, default=None)),
        'cyclic': bool(cyclic),
        'smoothingChangedOffsets': smoothing_changed,
    }
    if smoothing_changed:
        # Retained only when smoothing actually moved the feasible track: this
        # is the seed the initializer may re-encode once if the smoothed
        # induced joint trajectory breaks the cycle boundary.
        report['perFrameFeasibleSeedOffsetsMeters'] = seed_translations.tolist()
    if provided_seed:
        report['providedSeedOffsets'] = True
    return translations, report


def _canonical_stance_heading_seed(rig, coordinates, contact_targets, execution):
    """Encode canonical stance heading as a rigid root rotation and translation."""
    from .controlled_motion import canonical_stance_heading_target

    seed = np.asarray(coordinates, dtype=float)
    points = rig.decode(seed)
    target, report = canonical_stance_heading_target(
        points, rig.names, execution, contact_targets)
    if not report.get('required') or not report.get('applied'):
        return None, report
    pelvis = rig.names.index('pelvis')
    if rig.root != pelvis or rig.root not in rig.slots:
        return None, {**report, 'applied': False,
                      'reason': 'canonical_stance_rig_root_unavailable'}
    try:
        from .sequence_stabilization import frame_basis
        source_lateral = (points[:, rig.names.index('right_hip')]
                          - points[:, rig.names.index('left_hip')])
        target_lateral = (target[:, rig.names.index('right_hip')]
                          - target[:, rig.names.index('left_hip')])
        source_lateral[:, 1] = 0.
        target_lateral[:, 1] = 0.
        up = np.broadcast_to([0., 1., 0.], source_lateral.shape)
        source_basis = frame_basis(up, source_lateral)
        target_basis = frame_basis(up, target_lateral)
        rotation = np.einsum('fij,fkj->fik', target_basis, source_basis)
        source_root = points[:, pelvis]
        target_root = target[:, pelvis]
        translation = target_root - np.einsum('fij,fj->fi', rotation, source_root)
        rigid_target = (np.einsum('fij,fnj->fni', rotation, points)
                        + translation[:, None, :])
        rigid_error = float(np.max(np.abs(rigid_target - target), initial=0.))
        if not np.isfinite(rigid_error) or rigid_error > 1e-8:
            return None, {**report, 'applied': False,
                          'reason': 'canonical_stance_heading_not_rigid',
                          'maximumRigidTargetErrorMeters': rigid_error}
        root_world = rig.global_rotations(seed)[rig.root]
        corrected_world = np.einsum('fij,fjk->fik', rotation, root_world)
        encoded = seed.copy()
        encoded[:, :3] = target_root
        slot = rig.slots[rig.root]
        encoded[:, slot:slot + 3] = Rotation.from_matrix(
            corrected_world).as_rotvec()
        decoded = rig.decode(encoded)
        encode_error = float(np.max(np.abs(decoded - target), initial=0.))
    except (KeyError, TypeError, ValueError, IndexError):
        return None, {**report, 'applied': False,
                      'reason': 'canonical_stance_heading_seed_encoding_unavailable'}
    if not np.isfinite(encode_error) or encode_error > 1e-8:
        return None, {**report, 'applied': False,
                      'reason': 'canonical_stance_heading_seed_encoding_mismatch',
                      'maximumSeedEncodingErrorMeters': encode_error}
    return encoded, {
        **report,
        'seedEncodingApplied': True,
        'maximumSeedEncodingErrorMeters': encode_error,
        'seedEncoding': 'common_rigid_root_heading_and_translation',
    }


def initialize_joint_plant_coordinates(rig, coordinates, pinned, contact_targets, *,
                                       articulation_reference, fps, cyclic=False, deadline,
                                       desired_world_foot_directions=None,
                                       pitch_authority_mask_by_side=None,
                                       pitch_trajectory_mask_by_side=None, floor_y=None,
                                       rest_pitch_radians=None, foot_scale=None,
                                       side_axis_by_side=None,
                                       native_foot_geometry=None,
                                       native_foot_tracks=None,
                                       native_foot_mirror_required=False,
                                       source_projection_constraint=None,
                                       canonical_execution=None,
                                       native_fullsole_constraint_capture=None,
                                       diagnostic_stage_capture=None,
                                       failure_capture=None,
                                       root_track_offsets=None):
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

    def capture_failure(stage, coordinates, details=None):
        if callable(failure_capture):
            failure_capture(str(stage), np.asarray(coordinates, dtype=float).copy(),
                            deepcopy(details) if details is not None else {})

    canonical_heading_report = None
    if canonical_execution is not None:
        heading_targets = targets
        anchor_pair = _native_fullsole_track_mirror_pair(
            native_foot_tracks, len(points), native_foot_mirror_required)
        if anchor_pair is not None:
            from .native_foot_geometry import validated_native_foot_geometry
            validated_geometry = validated_native_foot_geometry(native_foot_geometry)
            if (validated_geometry is not None
                    and all(side in (validated_geometry.get('sides') or {})
                            for side in ('left', 'right'))):
                heading_targets = targets.copy()
                for side in ('left', 'right'):
                    target_world = np.asarray(
                        anchor_pair[side]['episode']['targetWorld'], dtype=float)
                    heading_targets[:, rig.names.index(f'{side}_foot')] = target_world
        seeded, canonical_heading_report = _canonical_stance_heading_seed(
            rig, baseline, heading_targets, canonical_execution)
        if heading_targets is not targets and canonical_heading_report.get('required'):
            canonical_heading_report['headingReference'] = (
                'qualified_native_bilateral_fullsole_anchor_pair')
        if canonical_heading_report.get('required'):
            if seeded is None or not canonical_heading_report.get('applied'):
                capture_failure('canonical_stance_heading_seed', baseline,
                                canonical_heading_report)
                return None, {
                    'feasible': False,
                    'reason': canonical_heading_report.get(
                        'reason', 'canonical_stance_heading_seed_unavailable'),
                    'canonicalStanceHeadingSeed': canonical_heading_report,
                }
            baseline = seeded
            points = rig.decode(baseline)

    fullsole = _native_fullsole_solver_constraints(
        rig, points, baseline, pins, targets,
        native_foot_tracks=native_foot_tracks,
        native_foot_geometry=native_foot_geometry,
        side_axis_by_side=side_axis_by_side, foot_scale=foot_scale,
        native_foot_mirror_required=native_foot_mirror_required,
        source_projection_constraint=source_projection_constraint, fps=fps)
    if canonical_heading_report is not None:
        fullsole['report']['canonicalStanceHeadingSeed'] = deepcopy(
            canonical_heading_report)
    def attach_material_constraints(candidate):
        """Merge fully anchored native point targets and solved coverage."""
        material = _native_material_point_solver_constraints(
            rig, points, baseline, pins, targets,
            native_foot_tracks=native_foot_tracks,
            excluded_pins=candidate['pins'])
        derived = np.zeros_like(np.asarray(pins, dtype=bool))
        if material['coverage']:
            derived = np.asarray(material['pins'], dtype=bool) & ~np.asarray(
                candidate['pins'], dtype=bool)
            if np.any(derived):
                candidate['targets'][derived] = material['targets'][derived]
                candidate['pins'] = np.asarray(candidate['pins'], dtype=bool) | derived
            solved_coverage = {}
            for source in (candidate['coverage'], material['coverage']):
                for side, entries in source.items():
                    solved_coverage.setdefault(side, []).extend(entries)
            candidate['solvedCoverage'] = solved_coverage
            candidate['report']['material'] = material['report']
        else:
            candidate['solvedCoverage'] = candidate['coverage']
        candidate['materialDerivedPins'] = derived

    attach_material_constraints(fullsole)
    if fullsole['report'].get('reason'):
        capture_failure('native_fullsole_constraint_preflight', baseline,
                        fullsole['report'])
        return None, {'feasible': False, 'nativeFullsole': fullsole['report'],
                      'reason': fullsole['report']['reason']}

    def projection_track_copy(candidate):
        """Exact projector track copy for one solved candidate's coverage."""
        if not isinstance(native_foot_tracks, dict):
            return None
        return _native_tracks_without_solved_fullsole(
            native_foot_tracks, candidate['solvedCoverage'])

    def capture_native_stage(stage, stage_coordinates):
        """Expose opt-in, production-evaluated full-sole metrics at encode stages."""
        if not callable(diagnostic_stage_capture) or not fullsole['coverage']:
            return None
        check_scale = foot_scale
        if check_scale is None:
            from .foot_geometry import foot_scale_from_pose
            check_scale = foot_scale_from_pose(points[0], rig.names)
        postcheck = _native_fullsole_encoded_check(
            rig, stage_coordinates, fullsole['coverage'], native_foot_tracks,
            native_foot_geometry, check_scale)
        diagnostic_stage_capture(
            str(stage), np.asarray(stage_coordinates, dtype=float).copy(), postcheck)
        return postcheck

    capture_native_stage('before_root_adjusted_pose_encode', baseline)

    def make_specs(candidate):
        # Transient support-plane targets must follow the same filtered tracks
        # the emitted projector will consume for this candidate, so solved
        # coverage changes (including the camera-yaw rebuild) cannot reopen the
        # model-versus-emit ownership split.
        native_projection_targets = _native_plane_projection_targets(
            rig.names, points, projection_track_copy(candidate),
            {'rig': rig, 'coordinates': baseline})
        result, report = _make_specs(
            rig.names, points, candidate['pins'], candidate['targets'], reference,
            desired_world_foot_directions=desired_world_foot_directions,
            pitch_authority_mask_by_side=pitch_authority_mask_by_side,
            pitch_trajectory_mask_by_side=pitch_trajectory_mask_by_side, cyclic=cyclic,
            floor_y=floor_y, rest_pitch_radians=rest_pitch_radians,
            foot_scale=foot_scale, side_axis_by_side=side_axis_by_side, fps=fps,
            direction_authority=getattr(rig, "source_direction_authority", None),
            native_projection_targets=native_projection_targets)
        if result and native_projection_targets:
            from .contact_heel_repair import _encode_targets
            from .contact_interpolation import project_supported_material_contact
            from .support_geometry import _native_side_axes_for_coordinates as material_side_axes
            from .supported_contact_rig import _episode_targets, _material_points
            tracks = projection_track_copy(candidate)
            baseline_axes = material_side_axes(
                rig, baseline, {'_nativeFootMaterialTracks': tracks})
            baseline_world = rig.global_rotations(baseline)
            local_axes = {side: np.einsum('fji,fj->fi',
                baseline_world[rig.names.index(f'{side}_foot')], axes)
                for side, axes in baseline_axes.items()}
            moving = [index for spec in result for index in spec['indices'][1:]]
            by_frame = [[] for _ in points]
            for side, entries in native_projection_targets.items():
                for entry in entries:
                    for frame in entry['rows']:
                        by_frame[frame].append((side, entry['episode']))

            def project_emitted(frame, translation, target_points):
                if not by_frame[frame]:
                    return target_points
                q = baseline[frame:frame + 1].copy()
                q[:, :3] += translation
                q = _encode_targets(rig, q, target_points, moving)
                if q is None:
                    return None
                world = rig.global_rotations(q)
                axes = {side: world[rig.names.index(f'{side}_foot')] @ values[frame]
                        for side, values in local_axes.items()}
                source = rig.decode(q)
                emitted = source.copy()
                for side, episode in by_frame[frame]:
                    knee, ankle, toe = (rig.names.index(f'{side}_{part}')
                                        for part in ('knee', 'ankle', 'foot'))
                    material = _material_points(source[:, ankle], source[:, toe], axes[side], episode)
                    try:
                        new_ankle, new_toe, _, _ = project_supported_material_contact(
                            source[:, knee], source[:, ankle], source[:, toe], material,
                            _episode_targets(episode, material), axes[side], side)
                    except ValueError:
                        return None
                    emitted[:, ankle], emitted[:, toe] = new_ankle, new_toe
                return emitted

            for spec in result:
                spec['projectEmittedPoints'] = project_emitted
        return result, report

    specs, preflight = make_specs(fullsole)
    if not specs and source_projection_constraint is not None:
        failed_side = next((side for side in ('left', 'right')
                            if preflight.get('reason') ==
                            f'{side}_contact_target_changes_source_foot_pose'), None)
        camera_report = fullsole['report'].get('sourceCameraYaw') or {}
        camera_side = (camera_report.get('bySide') or {}).get(failed_side) or {}
        proposed_yaw = (fullsole['report'].get('sides') or {}).get(
            failed_side, {}).get('appliedCameraYawRadians')
        if (failed_side is not None and camera_side.get('available') is True
                and proposed_yaw is not None):
            # The camera-ray optimum is only a proposal. Re-run the existing
            # downstream articulation preflight without that inferred yaw; the
            # source-preserving material rotation remains subject to all normal
            # full-sole, root, and joint limits.
            source_preserving = _native_fullsole_solver_constraints(
                rig, points, baseline, pins, targets,
                native_foot_tracks=native_foot_tracks,
                native_foot_geometry=native_foot_geometry,
                side_axis_by_side=side_axis_by_side, foot_scale=foot_scale,
                native_foot_mirror_required=native_foot_mirror_required,
                source_projection_constraint=None, fps=fps)
            # A rejected camera yaw rebuilds the full-sole constraints, so
            # re-merge the native point targets against the rebuilt pins before
            # the source-preserving preflight consumes them.
            attach_material_constraints(source_preserving)
            source_specs, source_preflight = make_specs(source_preserving)
            if source_specs:
                source_preserving['report']['sourceCameraYawRejected'] = {
                    'side': failed_side,
                    'reason': 'source_articulation_pose_bound',
                    'proposedYawRadians': float(proposed_yaw),
                    'proposedCameraReport': camera_report,
                    'proposedPreflight': preflight.get('preflight', {}).get(failed_side),
                }
                fullsole = source_preserving
                specs, preflight = source_specs, source_preflight
    if not specs:
        capture_failure('source_articulation_preflight', baseline, preflight)
        return None, {'feasible': False, **preflight}
    if (callable(native_fullsole_constraint_capture)
            and fullsole.get('solvedCoverage')):
        # Material-point seed pins place the initializer's closed chain on the
        # stored playback anchor. They must not become fit pins: the fit keeps
        # the calibrated actual-shoe material-point residual so legal foot
        # rotation about that point stays free for the observed camera rays.
        material_seed_pins = np.asarray(
            fullsole.get('materialDerivedPins'), dtype=bool)
        handoff_pins = (np.asarray(fullsole['pins'], dtype=bool)
                        & ~np.asarray(pins, dtype=bool) & ~material_seed_pins)
        orientation_targets = {}
        for side, orientation in fullsole['orientations'].items():
            frames = np.asarray(orientation['frames'], dtype=int)
            world_rotations = np.asarray(orientation['worldRotations'], dtype=float)
            local_axes = np.asarray(orientation['localMaterialAxes'], dtype=float)
            orientation_targets[side] = {
                'frames': frames.copy(),
                'sideAxes': np.einsum('fij,fj->fi', world_rotations, local_axes),
                'worldRotations': world_rotations.copy(),
                'localMaterialAxes': local_axes.copy(),
            }
        native_fullsole_constraint_capture({
            'pinned': handoff_pins.copy(),
            'targets': np.asarray(fullsole['targets'], dtype=float).copy(),
            'orientationTargets': orientation_targets,
            'materialSeedPinnedFrameCount': int(np.count_nonzero(
                material_seed_pins)),
        })
    offsets, root_report = _root_track(
        specs, len(points), deadline, cyclic, fps,
        seed_offsets=root_track_offsets)
    if offsets is None:
        capture_failure('root_track', baseline, {'preflight': preflight, 'root': root_report})
        return None, {'feasible': False, 'preflight': preflight, 'root': root_report}
    if monotonic() >= deadline:
        raise TimeoutError('joint plant encoding exceeded deadline')
    encoded, initialized, margins = _encode_root_adjusted_pose(rig, baseline, specs, offsets)
    if monotonic() >= deadline:
        raise TimeoutError('joint plant encoding exceeded deadline')
    if encoded is None:
        capture_failure('root_adjusted_pose_encode', baseline,
                        {'preflight': preflight, 'root': root_report})
        return None, {'feasible': False, 'preflight': preflight, 'root': root_report,
                      'reason': 'closed_chain_encoding_failed'}
    capture_native_stage('after_root_adjusted_pose_encode', encoded)
    if native_foot_tracks is not None:
        from .supported_contact_rig import project_supported_native_foot_coordinates
        encoded = project_supported_native_foot_coordinates(
            rig, encoded, projection_track_copy(fullsole),
            {}, current_knee_pivot=True)
    capture_native_stage('after_native_track_projection', encoded)
    if fullsole['orientations']:
        encoded = _encode_native_fullsole_material_twists(
            rig, encoded, fullsole['orientations'])
        if encoded is None:
            capture_failure('native_fullsole_material_twist_encode', baseline,
                            {'preflight': preflight, 'root': root_report,
                             'nativeFullsole': fullsole['report']})
            return None, {'feasible': False, 'preflight': preflight, 'root': root_report,
                          'nativeFullsole': fullsole['report'],
                          'reason': 'native_fullsole_material_twist_encoding_failed'}
    captured_postcheck = capture_native_stage(
        'after_native_fullsole_material_twist_encode', encoded)
    actual = rig.decode(encoded)
    material_check = None
    if np.any(fullsole['materialDerivedPins']):
        derived_material_error = float(np.max(np.linalg.norm(
            (actual - fullsole['targets'])[fullsole['materialDerivedPins']],
            axis=-1), initial=0.))
        material_check = {
            'passed': bool(
                derived_material_error <= _NATIVE_FULLSOLE_TOLERANCE_METERS),
            'maximumEndpointErrorMeters': derived_material_error,
            'derivedFrameCount': int(np.count_nonzero(
                fullsole['materialDerivedPins'])),
            'toleranceMeters': _NATIVE_FULLSOLE_TOLERANCE_METERS,
        }
        if not material_check['passed']:
            capture_failure('native_material_derived_endpoint_postcheck', encoded,
                            {'preflight': preflight, 'root': root_report,
                             'nativeMaterial': material_check})
            return None, {'feasible': False, 'preflight': preflight,
                          'root': root_report,
                          'nativeFullsole': {
                              **fullsole['report'], 'materialPostcheck': material_check},
                          'reason': 'native_material_derived_endpoint_postcheck_failed'}
    fullsole_check = None
    if fullsole['coverage']:
        check_scale = foot_scale
        if check_scale is None:
            from .foot_geometry import foot_scale_from_pose
            check_scale = foot_scale_from_pose(points[0], rig.names)
        fullsole_check = (captured_postcheck if captured_postcheck is not None else
                          _native_fullsole_encoded_check(
                              rig, encoded, fullsole['coverage'], native_foot_tracks,
                              native_foot_geometry, check_scale))
        if not fullsole_check['passed']:
            capture_failure('native_fullsole_postcheck', encoded,
                            {'preflight': preflight, 'root': root_report,
                             'nativeFullsole': fullsole_check})
            return None, {'feasible': False, 'preflight': preflight, 'root': root_report,
                          'nativeFullsole': {
                              **fullsole['report'], 'postcheck': fullsole_check},
                          'reason': 'native_fullsole_postcheck_failed'}
    from .physical_validation import hinge_direction_events
    hinge_events = hinge_direction_events(
        actual, rig.names, reference, fps=fps,
        direction_authority=getattr(rig, 'source_direction_authority', None))
    if hinge_events:
        capture_failure('source_hinge_plane_postcheck', encoded,
                        {'hingeEvents': hinge_events, 'preflight': preflight,
                         'root': root_report})
        return None, {'feasible': False, 'reason': 'source_hinge_plane_postcheck_failed',
                      'hingeEvents': hinge_events, 'preflight': preflight, 'root': root_report}
    contact_error = np.linalg.norm((actual - targets)[pins], axis=-1)
    if not np.isfinite(actual).all() or np.max(contact_error, initial=0.) > 1e-5:
        capture_failure('exact_contact_postcheck', encoded,
                        {'preflight': preflight, 'root': root_report,
                         'maximumContactErrorMeters': float(np.max(contact_error, initial=0.))})
        return None, {'feasible': False, 'preflight': preflight, 'root': root_report,
                      'reason': 'exact_contact_postcheck_failed',
                      'maximumContactErrorMeters': float(np.max(contact_error, initial=0.))}
    if floor_y is not None:
        if monotonic() >= deadline:
            raise TimeoutError('joint plant material-floor validation exceeded deadline')
        from .controlled_motion import _sampling_payload
        from .foot_geometry import _sample_material_foot_geometry, shoe_vertices
        from .rig_playback import PLAYBACK_FLOOR_LIMIT_METERS, sample_rig
        floor_side_axes = np.asarray(side_axis_by_side, dtype=float).copy()
        if floor_side_axes.shape != (len(actual), 2, 3):
            return None, {'feasible': False, 'preflight': preflight, 'root': root_report,
                          'reason': 'native_floor_side_axes_unavailable'}
        if native_foot_tracks is not None:
            from .support_geometry import _native_side_axes_for_coordinates
            try:
                current_axes = _native_side_axes_for_coordinates(
                    rig, encoded, {'_nativeFootMaterialTracks': native_foot_tracks})
            except (KeyError, TypeError, ValueError) as error:
                return None, {'feasible': False, 'preflight': preflight, 'root': root_report,
                              'reason': f'native_floor_side_axes_unavailable:{error}'}
            for side_index, side in enumerate(('left', 'right')):
                if side in current_axes:
                    floor_side_axes[:, side_index] = current_axes[side]
        frame_rows = []
        for frame_points, axes in zip(actual, floor_side_axes):
            frame_rows.append({
                'joints': dict(zip(rig.names, frame_points.tolist())),
                'boneSides': {
                    f'{side}_ankle->{side}_foot': axes[side_index].tolist()
                    for side_index, side in enumerate(('left', 'right'))
                },
            })
        sample_count = len(actual) * 4 if cyclic else max(1, (len(actual) - 1) * 4 + 1)
        cursors = np.arange(sample_count, dtype=float) / 4.
        sampling_payload = _sampling_payload(rig, encoded)
        sampled = sample_rig(sampling_payload, cursors, wrap=cyclic)
        geometry_payload = {
            'frames': frame_rows, 'jointNames': list(rig.names),
            'footRestPitchRadians': rest_pitch_radians,
            'renderFloorY': float(floor_y), 'loop': {'enabled': bool(cyclic)},
        }
        if native_foot_geometry is not None:
            geometry_payload['nativeFootGeometry'] = native_foot_geometry
        geometry = _sample_material_foot_geometry(geometry_payload, cursors, sampled)
        floor_violations = {}
        from .foot_geometry import foot_scale_from_pose
        material_scale = float(foot_scale) if foot_scale is not None else foot_scale_from_pose(actual[0], rig.names)
        for side in ('left', 'right'):
            if side not in geometry:
                continue
            ankle_i, toe_i = rig.names.index(f'{side}_ankle'), rig.names.index(f'{side}_foot')
            surface = shoe_vertices(
                sampled[:, ankle_i], sampled[:, toe_i], geometry[side]['lateral'],
                (float(rest_pitch_radians[side]) if side in (rest_pitch_radians or {}) else None),
                material_scale, orientation=geometry[side].get('orientation'),
                native_geometry=geometry[side].get('nativeGeometry'))
            penetration = max(0., float(floor_y) - float(np.min(surface[:, :, 1])))
            floor_violations[side] = penetration
        maximum_floor_penetration = max(floor_violations.values(), default=0.)
        floor_report = {
            'required': True,
            'evaluatedSides': list(floor_violations),
            'sampleCount': int(len(cursors)),
            'maximumSurfacePenetrationMeters': maximum_floor_penetration,
            'limitMeters': PLAYBACK_FLOOR_LIMIT_METERS,
            'bySideMeters': floor_violations,
            'passed': bool(floor_violations) and maximum_floor_penetration <= PLAYBACK_FLOOR_LIMIT_METERS,
            'needsPlaybackFloorRefinement': (
                maximum_floor_penetration > PLAYBACK_FLOOR_LIMIT_METERS),
        }
    else:
        floor_report = {'required': False, 'passed': True,
                        'sampleCount': 0, 'bySideMeters': {},
                        'needsPlaybackFloorRefinement': False}

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
        'nativeFullsole': {
            **fullsole['report'], 'postcheck': fullsole_check,
            'materialPostcheck': material_check},
        'materialFloor': floor_report,
        'initializerFeasible': True,
        'renderReady': bool(floor_report['passed']),
        'maximumContactErrorMeters': float(np.max(contact_error, initial=0.)),
        'minimumKneeMarginDegrees': float(np.rad2deg(np.min(knee_margins))),
        'minimumAnkleMarginDegrees': float(np.rad2deg(np.min(ankle_margins))),
        'maximumRootTranslationMeters': float(np.max(np.linalg.norm(offsets, axis=1), initial=0.)),
    }
