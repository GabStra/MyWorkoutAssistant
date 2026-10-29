"""Recover source-observed heel-pitch motion with bounded 1D inversion."""

from __future__ import annotations

import math
import time

import numpy as np

from .foot_geometry import SHOE_LENGTH_RATIO, calibrated_foot_rest_pitches
from .rig_playback import decode_rig

def _check_deadline(deadline):
    if deadline is not None and time.monotonic() >= float(deadline):
        raise TimeoutError('source heel pitch stage exceeded its deadline')


def _unit(vector):
    vector = np.asarray(vector, dtype=float)
    length = np.linalg.norm(vector, axis=-1, keepdims=True)
    return vector / np.maximum(length, 1e-12)


def _source_projection_for_points(projection, payload):
    projection = np.asarray(projection, dtype=float)
    if projection.shape != (2, 3) or not np.isfinite(projection).all():
        raise ValueError('source projection must be a finite 2x3 matrix')
    placement = payload.get('scenePlacement') or {}
    if placement.get('version') == 1:
        from scipy.spatial.transform import Rotation
        rotation = Rotation.from_rotvec(np.asarray(placement['rotationVector'], dtype=float)).as_matrix()
        projection = projection @ rotation.T
    return projection


def _invert_native_heel_pitch(row, points, names, projection):
    """Invert the calibrated source heel lift into a signed world pitch delta."""
    side = row['motionSide']
    ankle_index, toe_index = names.index(f'{side}_ankle'), names.index(f'{side}_foot')
    cursor = float(row['leftFrame']) + float(row['alpha'])
    left = min(max(int(math.floor(cursor)), 0), len(points) - 1)
    right = min(left + 1, len(points) - 1)
    alpha = cursor - math.floor(cursor)
    pose = points[left] * (1. - alpha) + points[right] * alpha
    bone = pose[toe_index] - pose[ankle_index]
    length = float(np.linalg.norm(bone))
    horizontal = bone.copy()
    horizontal[1] = 0.
    horizontal_length = float(np.linalg.norm(horizontal))
    if length <= 1e-9 or horizontal_length <= 1e-9:
        return None, {'sourceTimeSec': float(row['sourceTime']), 'sourceSide': row['sourceSide'],
                      'reason': 'candidate_foot_heading_unavailable'}

    heading = horizontal / horizontal_length
    up = np.array([0., 1., 0.])
    lift_direction = _unit(np.asarray(row['liftDirection'], dtype=float))
    a = float(np.dot(projection @ heading, lift_direction))
    b = float(np.dot(projection @ up, lift_direction))
    source_lift = float(np.dot(
        np.asarray(row['sourceHeelToToeVector']) - np.asarray(row['baselineSourceVector']),
        lift_direction,
    ))
    baseline_fit = float(np.dot(np.asarray(row['baselineFitVector']), lift_direction))
    target = -(baseline_fit + source_lift) / (SHOE_LENGTH_RATIO * length)
    radius = math.hypot(a, b)
    if radius <= 1e-12 or target < -radius - 1e-9 or target > radius + 1e-9:
        return None, {
            'sourceTimeSec': float(row['sourceTime']), 'sourceSide': row['sourceSide'],
            'reason': 'observed_lift_outside_fixed_heading_pitch_reach',
            'projectedPitchRadius': radius, 'target': target,
            'sourceLiftImageUnits': source_lift,
        }

    phase = math.atan2(b, a)
    offset = math.acos(float(np.clip(target / radius, -1., 1.)))
    candidates = []
    for root in (phase + offset, phase - offset):
        for turn in range(-2, 3):
            value = root + 2. * math.pi * turn
            if -math.pi / 2. <= value <= 0.:
                candidates.append(value)
    if not candidates:
        return None, {
            'sourceTimeSec': float(row['sourceTime']), 'sourceSide': row['sourceSide'],
            'reason': 'no_heel_up_root_with_forward_foot_heading',
            'projectedPitchRadius': radius, 'target': target,
            'sourceLiftImageUnits': source_lift,
        }

    pitch_delta = max(candidates)
    generated = -SHOE_LENGTH_RATIO * length * (
        a * math.cos(pitch_delta) + b * math.sin(pitch_delta))
    fit_lift = generated - baseline_fit
    return pitch_delta, {
        'sourceTimeSec': float(row['sourceTime']), 'sourceSide': row['sourceSide'],
        'motionSide': side, 'sourceLiftImageUnits': source_lift,
        'pitchDeltaDegrees': float(np.rad2deg(pitch_delta)),
        'closedFormFitLiftImageUnits': fit_lift,
        'liftRatio': fit_lift / max(source_lift, 1e-12),
    }


def _measured_unknown_heel_pitches(constraint, points, names, projection, deadline=None):
    """Invert reliable unknown-state heel/toe vectors without assigning contact.

    Unknown rows are eligible only inside a continuous run bracketed by the
    same observed full-sole/toe-only anchor. The anchor supplies a geometric
    neutral baseline; it does not change the row's unknown contact state.
    """
    image_rows = list(constraint.get('sourceFootHeelImageObservations') or [])
    calibration_rows = [
        row for row in constraint.get('sourceFootHeelCalibrationObservations') or []
        if row.get('state') == 'full_sole'
        and row.get('stationaryAnchorGroupId') is not None
    ]
    geometry_payload = constraint.get('footGeometryPayload')
    if not image_rows or not calibration_rows or not isinstance(geometry_payload, dict):
        return [], [], {'eligibleUnknownObservationCount': 0,
                        'resolvedUnknownGeometryCount': 0,
                        'resolvedUnknownDirectionOnlyCount': 0,
                        'directionOnlyDetails': []}

    from .foot_geometry import sample_material_foot_points

    projection = np.asarray(projection, dtype=float)
    cursors = [float(row['leftFrame']) + float(row['alpha']) for row in calibration_rows]
    material = sample_material_foot_points(geometry_payload, cursors, points=points)
    predicted = np.asarray([
        projection @ (material[row['motionSide']]['heel'][index]
                      - material[row['motionSide']]['toe'][index])
        for index, row in enumerate(calibration_rows)
    ])
    source_vectors = np.asarray([
        row['sourceHeelToToeVector'] for row in calibration_rows
    ], dtype=float)
    image_height = float(((geometry_payload.get('sourcePoseCameraReference') or {})
                          .get('sourcePose') or {}).get('imageHeight') or 1000.)
    groups = {}
    for index, row in enumerate(calibration_rows):
        _check_deadline(deadline)
        key = (row.get('sourceSide'), row.get('motionSide'),
               row.get('stationaryAnchorGroupId'))
        groups.setdefault(key, []).append(index)

    baseline_by_group = {}
    retained_noise_by_group = {}
    for row in image_rows:
        if (row.get('state') != 'full_sole'
                or row.get('stationaryAnchorGroupId') is None):
            continue
        try:
            noise = float(row['sourceNoiseImageUnits'])
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        if np.isfinite(noise) and noise >= 0.:
            key = (row.get('sourceSide'), row.get('motionSide'),
                   row.get('stationaryAnchorGroupId'))
            retained_noise_by_group.setdefault(key, []).append(noise)
    up = np.array([0., 1., 0.])
    for key, indexes in groups.items():
        if len(indexes) < 3:
            continue
        selected_source = source_vectors[indexes]
        selected_fit = predicted[indexes]
        side_lift = projection @ up
        side_lift /= max(float(np.linalg.norm(side_lift)), 1e-12)
        source_lifts = selected_source @ side_lift
        median_lift = float(np.median(source_lifts))
        noise = (float(np.median(retained_noise_by_group[key]))
                 if retained_noise_by_group.get(key) else max(
                     1. / max(image_height, 1.),
                     3. * 1.4826 * float(np.median(np.abs(source_lifts - median_lift))),
                 ))
        baseline_by_group[key] = {
            'source': np.median(selected_source, axis=0),
            'fit': np.median(selected_fit, axis=0),
            'noise': noise,
            'liftDirection': side_lift,
        }

    rows_by_side = {}
    for row in image_rows:
        if row.get('motionSide') in ('left', 'right'):
            rows_by_side.setdefault(row['motionSide'], []).append(row)
    pitches, failures = [], []
    eligible_count = 0
    for motion_side, rows in rows_by_side.items():
        rows.sort(key=lambda row: float(row.get('sourceTime', float('inf'))))
        times = np.asarray([
            float(row['sourceTime']) for row in rows
            if np.isfinite(float(row.get('sourceTime', float('nan'))))
        ], dtype=float)
        positive_steps = np.diff(times)
        positive_steps = positive_steps[positive_steps > 1e-8]
        cadence = float(np.median(positive_steps)) if positive_steps.size else 0.
        max_step = 2.5 * cadence
        index = 0
        while index < len(rows):
            _check_deadline(deadline)
            if str(rows[index].get('state', 'unknown')).lower() != 'unknown':
                index += 1
                continue
            run_start = index
            while (index < len(rows)
                   and str(rows[index].get('state', 'unknown')).lower() == 'unknown'):
                index += 1
            run_end = index
            eligible_count += run_end - run_start
            if run_start == 0 or run_end >= len(rows):
                continue
            previous, following = rows[run_start - 1], rows[run_end]
            group_id = previous.get('stationaryAnchorGroupId')
            if (not group_id or following.get('stationaryAnchorGroupId') != group_id
                    or previous.get('state') not in ('full_sole', 'toe_only')
                    or following.get('state') not in ('full_sole', 'toe_only')):
                continue
            try:
                bracket_times = np.asarray(
                    [float(item['sourceTime']) for item in rows[run_start - 1:run_end + 1]],
                    dtype=float)
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
            if (not np.isfinite(bracket_times).all()
                    or np.any(np.diff(bracket_times) <= 0.)
                    or (max_step > 0. and np.any(np.diff(bracket_times) > max_step))):
                continue
            key = (previous.get('sourceSide'), motion_side, group_id)
            baseline = baseline_by_group.get(key)
            if baseline is None:
                continue
            for row in rows[run_start:run_end]:
                try:
                    confidence = min(float(row['confidenceWeight']), 1.)
                    source_vector = np.asarray(row['sourceHeelToToeVector'], dtype=float)
                except (KeyError, TypeError, ValueError, OverflowError):
                    continue
                if (not np.isfinite(confidence) or confidence < .8
                        or not np.isfinite(source_vector).all()):
                    continue
                enriched = {
                    **row,
                    'motionSide': motion_side,
                    'stationaryAnchorGroupId': group_id,
                    'baselineSourceVector': baseline['source'],
                    'baselineFitVector': baseline['fit'],
                    'liftDirection': baseline['liftDirection'],
                    'sourceNoiseImageUnits': baseline['noise'],
                }
                delta, detail = _invert_native_heel_pitch(
                    enriched, points, names, projection)
                if delta is None:
                    # A tiny negative lift can be explained by the calibrated
                    # stance noise and has no heel-up root. Larger contradictions
                    # remain unresolved rather than being clamped to flat.
                    source_lift = detail.get('sourceLiftImageUnits')
                    if (detail.get('reason') == 'no_heel_up_root_with_forward_foot_heading'
                            and source_lift is not None
                            and -baseline['noise'] <= float(source_lift) < 0.):
                        delta = 0.
                        detail = {**detail, 'resolvedAsNoiseBoundedStance': True,
                                  'sourceNoiseImageUnits': baseline['noise']}
                    else:
                        failures.append({**detail, 'state': 'unknown',
                                         'sourceNoiseImageUnits': baseline['noise']})
                        continue
                else:
                    detail = {**detail, 'sourceNoiseImageUnits': baseline['noise']}
                pitches.append((enriched, float(delta)))

    # Heel-image tracking can have a long gap while the toe ray remains
    # continuously observed. A stationary, same-anchor toe is sufficient to
    # carry *orientation* through an unknown heel sample; it does not resolve
    # contact. Use empirical per-anchor toe-ray jitter and the existing ray
    # cadence bound rather than extending the heel-observation bridge.
    all_ray_rows = list(constraint.get('sourceFootRayObservations') or [])
    ray_rows = [row for row in all_ray_rows
                if row.get('state') in ('full_sole', 'toe_only')
                and row.get('stationaryAnchorGroupId') is not None]
    rays_by_key = {}
    for row in ray_rows:
        key = (row.get('sourceSide'), row.get('motionSide'),
               row.get('stationaryAnchorGroupId'))
        try:
            ray_time = float(row['sourceTime'])
            toe_point = np.asarray(row['toeImagePoint'], dtype=float)
            confidence = float(row.get('confidenceWeight', 0.))
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        if (not np.isfinite(ray_time) or toe_point.shape != (2,)
                or not np.isfinite(toe_point).all() or not np.isfinite(confidence)
                or confidence < .8):
            continue
        rays_by_key.setdefault(key, []).append(row)
    for rows in rays_by_key.values():
        rows.sort(key=lambda row: float(row['sourceTime']))

    camera = ((geometry_payload.get('sourcePoseCameraReference') or {})
              .get('sourcePose') or {})
    try:
        image_scale = np.asarray([float(camera['imageWidth']), float(camera['imageHeight'])])
    except (KeyError, TypeError, ValueError, OverflowError):
        image_scale = np.asarray([image_height, image_height])
    if image_scale.shape != (2,) or not np.isfinite(image_scale).all() or np.any(image_scale <= 0.):
        image_scale = np.asarray([image_height, image_height])

    jitter_by_group = {}
    ray_step_by_side = {}
    for key, rows in rays_by_key.items():
        times = np.asarray([float(row['sourceTime']) for row in rows], dtype=float)
        positive = np.diff(times)
        positive = positive[positive > 1e-8]
        if positive.size:
            ray_step_by_side.setdefault(key[:2], []).extend(positive.tolist())
    for key, rows in rays_by_key.items():
        cadence_values = ray_step_by_side.get(key[:2], [])
        cadence = float(np.median(cadence_values)) if cadence_values else 0.
        distances = []
        for first, second in zip(rows, rows[1:]):
            gap = float(second['sourceTime']) - float(first['sourceTime'])
            if gap <= 0.:
                continue
            points_px = (np.asarray(first['toeImagePoint'], dtype=float) * image_scale,
                         np.asarray(second['toeImagePoint'], dtype=float) * image_scale)
            distances.append((gap, float(np.linalg.norm(points_px[1] - points_px[0]))))
        bounded = [distance for gap, distance in distances
                   if cadence > 0. and gap <= 2.5 * cadence]
        if len(bounded) >= 3:
            jitter_by_group[key] = float(np.percentile(bounded, 95.))

    direction_only_details = []
    resolved_keys = {(row.get('sourceSide'), round(float(row['sourceTime']), 6),
                      row.get('motionSide')) for row, _delta in pitches}
    for row in image_rows:
        _check_deadline(deadline)
        if str(row.get('state', 'unknown')).lower() != 'unknown':
            continue
        try:
            source_time = float(row['sourceTime'])
            source_vector = np.asarray(row['sourceHeelToToeVector'], dtype=float)
            confidence = float(row['confidenceWeight'])
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        identity = (row.get('sourceSide'), round(source_time, 6), row.get('motionSide'))
        if identity in resolved_keys or not np.isfinite(source_time):
            continue
        side = row.get('motionSide')
        source_side = row.get('sourceSide')
        if (side not in ('left', 'right') or not np.isfinite(source_vector).all()
                or not np.isfinite(confidence) or confidence < .8):
            continue
        direct_ray = next((ray for ray in all_ray_rows
                           if ray.get('sourceSide') == source_side
                           and ray.get('motionSide') == side
                           and str(ray.get('state', '')).lower() == 'unknown'
                           and abs(float(ray.get('sourceTime', float('inf'))) - source_time)
                           <= 1e-6), None)
        if direct_ray is None:
            continue
        try:
            direct_confidence = float(direct_ray['confidenceWeight'])
            direct_point = np.asarray(direct_ray['toeImagePoint'], dtype=float) * image_scale
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        if (not np.isfinite(direct_confidence) or direct_confidence < .8
                or direct_point.shape != (2,) or not np.isfinite(direct_point).all()):
            continue
        try:
            source_noise = float(row['sourceNoiseImageUnits'])
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        key_prefix = (source_side, side)
        group_candidates = [key for key in baseline_by_group
                            if key[:2] == key_prefix]
        if not group_candidates:
            continue
        ray_cadence_values = ray_step_by_side.get(key_prefix, [])
        ray_cadence = float(np.median(ray_cadence_values)) if ray_cadence_values else 0.
        max_ray_gap = 2.5 * ray_cadence
        selected = None
        for group_key in group_candidates:
            anchor_id = group_key[2]
            group_rays = rays_by_key.get(group_key, [])
            jitter = jitter_by_group.get(group_key)
            if jitter is None or max_ray_gap <= 0.:
                continue
            neighbors = []
            for ray in group_rays:
                ray_time = float(ray['sourceTime'])
                gap = abs(ray_time - source_time)
                if gap <= max_ray_gap:
                    point_px = np.asarray(ray['toeImagePoint'], dtype=float) * image_scale
                    neighbors.append((gap, ray_time < source_time, point_px))
            if not neighbors:
                continue
            nearest_gap, prior, nearest_point = min(neighbors, key=lambda item: item[0])
            displacement_pixels = (
                float(np.linalg.norm(direct_point - nearest_point))
                if direct_point.shape == (2,) and np.isfinite(direct_point).all()
                else float('inf'))
            if (not np.isfinite(direct_point).all()
                    or nearest_gap > max_ray_gap
                    or displacement_pixels > jitter):
                continue
            selected = (group_key, anchor_id, jitter, nearest_gap, prior,
                        displacement_pixels)
            break
        if selected is None:
            continue
        group_key, anchor_id, jitter, ray_gap, is_prior_ray, displacement_pixels = selected
        baseline = baseline_by_group[group_key]
        source_lift = float(np.dot(
            source_vector - baseline['source'], baseline['liftDirection']))
        effective_noise = max(float(source_noise), float(baseline['noise']))
        if (not np.isfinite(source_lift) or not np.isfinite(effective_noise)
                or abs(source_lift) > effective_noise):
            continue
        try:
            cursor = float(row['leftFrame']) + float(row['alpha'])
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        ankle_index = names.index(f'{side}_ankle')
        toe_index = names.index(f'{side}_foot')
        left = int(np.clip(math.floor(cursor), 0, len(points) - 1))
        right = min(left + 1, len(points) - 1)
        alpha = cursor - math.floor(cursor)
        native_pose = points[left] * (1. - alpha) + points[right] * alpha
        native_bone = native_pose[toe_index] - native_pose[ankle_index]
        native_length = float(np.linalg.norm(native_bone))
        native_horizontal = native_bone.copy()
        native_horizontal[1] = 0.
        native_horizontal_length = float(np.linalg.norm(native_horizontal))
        if native_length <= 1e-9 or native_horizontal_length <= 1e-9:
            continue
        native_heading = native_horizontal / native_horizontal_length
        native_pitch = math.atan2(float(native_bone[1]), native_horizontal_length)
        lift_direction = baseline['liftDirection']
        a = float(np.dot(projection @ native_heading, lift_direction))
        b = float(np.dot(projection @ np.array([0., 1., 0.]), lift_direction))
        predicted_native_lift = (
            -SHOE_LENGTH_RATIO * native_length
            * (a * math.cos(native_pitch) + b * math.sin(native_pitch))
            - float(np.dot(baseline['fit'], lift_direction))
        )
        native_pitch_matches_source_image = (
            abs(predicted_native_lift - source_lift) <= effective_noise)
        enriched = {
            **row,
            'motionSide': side,
            'stationaryAnchorGroupId': anchor_id,
            'baselineSourceVector': baseline['source'],
            'baselineFitVector': baseline['fit'],
            'liftDirection': baseline['liftDirection'],
            'sourceNoiseImageUnits': max(float(source_noise), float(baseline['noise'])),
            'toeImagePoint': direct_ray['toeImagePoint'],
            'toeImageConfidenceWeight': direct_confidence,
            'directionOnlyNeutralWithinNoise': True,
            'toeStationarityEvidence': {
                'sameAnchorGroupId': anchor_id,
                'matchedRayGapSec': ray_gap,
                'matchedRayWasPrior': is_prior_ray,
                'maxRayGapSec': max_ray_gap,
                'toeDisplacementPixels': displacement_pixels,
                'calibratedSameAnchorJitterP95Pixels': jitter,
                'contactResolved': False,
            },
            'nativePitchForwardProjectionLiftImageUnits': predicted_native_lift,
            'nativePitchMatchesSourceImage': native_pitch_matches_source_image,
        }
        neutral_detail = {
            'sourceTimeSec': source_time,
            'sourceSide': source_side,
            'motionSide': side,
            'pitchDeltaDegrees': 0.,
            'sourceLiftImageUnits': source_lift,
            'sourceNoiseImageUnits': enriched['sourceNoiseImageUnits'],
            'nativePitchForwardProjectionResidualImageUnits': (
                predicted_native_lift - source_lift),
            'nativePitchMatchesSourceImage': native_pitch_matches_source_image,
            'resolvedAsNoiseBoundedDirectionOnly': True,
            'contactResolved': False,
            'toeStationarityEvidence': enriched['toeStationarityEvidence'],
        }
        pitches.append((enriched, 0.))
        resolved_keys.add(identity)
        direction_only_details.append(neutral_detail)
    return pitches, failures, {
        'eligibleUnknownObservationCount': int(eligible_count),
        'resolvedUnknownGeometryCount': int(len(pitches)),
        'resolvedUnknownDirectionOnlyCount': sum(
            bool(row.get('directionOnlyNeutralWithinNoise')) for row, _delta in pitches),
        'directionOnlyDetails': direction_only_details,
    }


def _shape_preserving_source_pitch(
    constraint, frame_count, side, fullsole_frame_mask, event_pitches, *,
    geometry_pitches=(), frame_times=None, fps=30., deadline=None,
):
    """Map measured pitch through known support phases without smoothing speed.

    PCHIP interpolates only inside contiguous, timed full-sole/toe-only evidence.
    Unknown samples are interpolated only when their native heel/toe image
    geometry has an independently resolved pitch. They remain geometric
    direction evidence and never become inferred contact or airborne intervals.
    """
    from scipy.interpolate import PchipInterpolator

    fixed = np.asarray(fullsole_frame_mask, dtype=bool)
    if fixed.shape != (frame_count,):
        raise ValueError('full-sole pitch mask must match the rig frame count')

    frame_clock = None
    has_source_clock = False
    if frame_times is not None:
        try:
            candidate_clock = np.asarray(frame_times, dtype=float)
        except (TypeError, ValueError, OverflowError):
            candidate_clock = np.empty(0, dtype=float)
        if (candidate_clock.shape == (frame_count,)
                and np.isfinite(candidate_clock).all()
                and (frame_count < 2 or np.all(np.diff(candidate_clock) > 0.))):
            frame_clock = candidate_clock
            has_source_clock = True
    if frame_clock is None:
        # Direct callers without source timestamps retain exact fit-frame
        # alignment; production payloads use their absolute source clock.
        if not np.isfinite(float(fps)) or float(fps) <= 0.:
            raise ValueError('source pitch interpolation requires a positive frame rate')
        frame_clock = np.arange(frame_count, dtype=float) / float(fps)

    observations = []
    for row in constraint.get('sourceFootHeelImageObservations') or []:
        _check_deadline(deadline)
        if row.get('motionSide') != side:
            continue
        try:
            source_time = float(row['sourceTime'])
            cursor = float(row['leftFrame']) + float(row['alpha'])
            state = str(row.get('state', 'unknown')).lower()
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        if not np.isfinite(source_time) or not np.isfinite(cursor):
            continue
        observations.append((source_time, cursor, state, row))
    observations.sort(key=lambda item: item[0])

    event_by_key = {
        (row.get('sourceSide'), round(float(row['sourceTime']), 6), row.get('motionSide')):
            float(pitch_delta)
        for row, pitch_delta in event_pitches
        if row.get('motionSide') == side
    }
    geometry_by_key = {
        (row.get('sourceSide'), round(float(row['sourceTime']), 6), row.get('motionSide')):
            {'target': float(pitch_delta),
             'anchorGroup': row.get('stationaryAnchorGroupId')}
        for row, pitch_delta in geometry_pitches
        if row.get('motionSide') == side
    }
    mapped = []
    for source_time, cursor, state, row in observations:
        key = (row.get('sourceSide'), round(source_time, 6), row.get('motionSide'))
        geometry = None
        if state == 'full_sole':
            target = 0.
        elif state == 'toe_only':
            target = event_by_key.get(key)
            if target is None:
                # A toe-only row without an independently inverted heel sample
                # is unresolved and breaks the interpolated trajectory.
                target = None
        elif state == 'unknown':
            # This target comes from a reliable native heel/toe image vector,
            # not a contact label. Unknown rows without resolved geometry
            # remain gaps and cannot be bridged by interpolation.
            geometry = geometry_by_key.get(key)
            target = geometry.get('target') if geometry is not None else None
        else:
            target = None
        mapped.append({
            'time': source_time if has_source_clock else cursor / float(fps),
            'sourceTime': source_time,
            'cursor': cursor,
            'state': state,
            'target': target,
            'anchorGroup': (geometry.get('anchorGroup') if state == 'unknown'
                            and geometry is not None
                            else row.get('stationaryAnchorGroupId')),
            'sourceSide': row.get('sourceSide'),
            'measuredGeometry': (state == 'unknown' and key in geometry_by_key),
        })

    pitch_delta = np.zeros(frame_count, dtype=float)
    authority = fixed.copy()
    trajectory = fixed.copy()
    observed_sample_count = 0
    interpolated_segment_count = 0
    unknown_gap_count = sum(item['target'] is None for item in mapped)
    if not mapped:
        return pitch_delta, authority, trajectory, {
            'observationCount': 0, 'interpolatedSegmentCount': 0,
            'unresolvedObservationCount': 0,
        }

    intervals = np.diff([item['time'] for item in mapped])
    intervals = intervals[intervals > 1e-9]
    max_gap = 2.5 * float(np.median(intervals)) if intervals.size else 0.

    valid_indices = [index for index, item in enumerate(mapped) if item['target'] is not None]
    segments, active = [], []
    prior_valid_index = None
    for index in valid_indices:
        item = mapped[index]
        bridge_rows = (mapped[prior_valid_index + 1:index]
                       if prior_valid_index is not None else [])
        bridge_clock = ([mapped[prior_valid_index]['time']]
                        + [row['time'] for row in bridge_rows]
                        + [item['time']]) if prior_valid_index is not None else []
        continuous_source_samples = (
            len(bridge_clock) >= 2
            and all(0. < delta <= max_gap
                    for delta in np.diff(bridge_clock))
        )
        permitted_unknown_bridge = (
            all(row['state'] == 'unknown' and row['target'] is not None
                for row in bridge_rows)
            and continuous_source_samples
        )
        contiguous = (
            prior_valid_index is not None
            and item['anchorGroup'] == mapped[prior_valid_index]['anchorGroup']
            and permitted_unknown_bridge
        )
        if not contiguous and active:
            segments.append(active)
            active = []
        active.append(item)
        prior_valid_index = index
    if active:
        segments.append(active)

    for segment in segments:
        _check_deadline(deadline)
        sample_times = np.asarray([item['time'] for item in segment], dtype=float)
        sample_targets = np.asarray([item['target'] for item in segment], dtype=float)
        if len(sample_times) > 1:
            inside = ((frame_clock >= sample_times[0])
                      & (frame_clock <= sample_times[-1]))
            if np.any(inside):
                pitch_delta[inside] = np.asarray(
                    PchipInterpolator(sample_times, sample_targets, extrapolate=False)(
                        frame_clock[inside]), dtype=float)
                trajectory[inside] = True
            interpolated_segment_count += 1
        else:
            # A lone observation authorizes only its mapped frame, never a
            # neighborhood or the rest of the clip.
            index = int(np.clip(round(segment[0]['cursor']), 0, frame_count - 1))
            frame_interval = (float(np.median(np.diff(frame_clock)))
                              if frame_count > 1 else 1. / float(fps))
            if abs(frame_clock[index] - segment[0]['time']) <= .5 * frame_interval + 1e-9:
                pitch_delta[index] = float(sample_targets[0])
                trajectory[index] = True
        observed_sample_count += len(segment)

    # Contact/pitch authority requires measured adjacent support samples.
    # A short unknown bridge gets a continuous geometric direction above,
    # while this stricter mask remains false through that gap.
    for index, item in enumerate(mapped):
        if item['target'] is None:
            continue
        nearest = int(np.argmin(np.abs(frame_clock - item['time'])))
        # This mask is measured direction authority, not contact truth. A
        # reliable unknown heel/toe image vector can validate direction while
        # the separate pinned/contact masks remain untouched.
        authority[nearest] = True
        if index + 1 >= len(mapped):
            continue
        following = mapped[index + 1]
        if (following['target'] is not None
                and following['anchorGroup'] == item['anchorGroup']
                and following['time'] - item['time'] <= max_gap):
            inside = ((frame_clock >= item['time']) & (frame_clock <= following['time']))
            authority[inside] = True

    pitch_delta[fixed] = 0.
    authority[fixed] = True
    trajectory[fixed] = True
    # Measured contact evidence may be nearest to a fit frame even when its
    # source timestamp lies outside that frame's observed clock coverage. Such
    # a row must not claim contact authority unless the geometric trajectory
    # was actually mapped there.
    authority &= trajectory
    return pitch_delta, authority, trajectory, {
        'observationCount': int(observed_sample_count),
        'interpolatedSegmentCount': int(interpolated_segment_count),
        'unresolvedObservationCount': int(unknown_gap_count),
    }


def propose_source_heel_pitch(rig, coordinates, payload, source_projection_constraint,
                              pinned, fps, deadline=None, contact_targets=None):
    """Derive smooth foot pitch targets from retained native heel observations.

    Returns a desired unit ankle-to-toe direction array shaped ``(frames, 2, 3)``
    in left/right order, plus JSON-safe diagnostics. The caller owns toe anchors,
    root motion, IK feasibility, rig encoding, and final acceptance.
    """
    names = list(rig['jointNames'] if isinstance(rig, dict) else rig.names)
    coordinates = np.asarray(coordinates, dtype=float)
    frame_count = len(coordinates)
    if frame_count < 3 or not np.isfinite(coordinates).all():
        raise ValueError('source heel pitch requires at least three finite rig keyframes')
    if not np.isfinite(float(fps)) or float(fps) <= 0.:
        raise ValueError('source heel pitch requires a positive frame rate')
    points = rig.decode(coordinates) if hasattr(rig, 'decode') else decode_rig(rig, coordinates)
    pinned = np.asarray(pinned, dtype=bool)
    if pinned.shape != points.shape[:2]:
        raise ValueError('pinned mask must have shape (frames, joints)')

    if 'sourceTimeOriginSec' in source_projection_constraint:
        try:
            declared_origin = float(source_projection_constraint['sourceTimeOriginSec'])
        except (TypeError, ValueError, OverflowError):
            declared_origin = float('nan')
        if not np.isfinite(declared_origin):
            base_directions = np.zeros((frame_count, 2, 3), dtype=float)
            name_set = set(names)
            for side_index, side in enumerate(('left', 'right')):
                if not {f'{side}_ankle', f'{side}_foot'} <= name_set:
                    continue
                ankle, toe = names.index(f'{side}_ankle'), names.index(f'{side}_foot')
                base_directions[:, side_index] = _unit(points[:, toe] - points[:, ankle])
            return base_directions, {
                'available': False, 'passed': False,
                'reason': 'invalid_source_time_origin',
                'eventCount': 0, 'inversionFailureCount': 0,
                'observationCountBySide': {'left': 0, 'right': 0},
                'pitchAuthorityMaskBySide': {
                    side: np.zeros(frame_count, dtype=bool).tolist()
                    for side in ('left', 'right')
                },
                'pitchTrajectoryMaskBySide': {
                    side: np.zeros(frame_count, dtype=bool).tolist()
                    for side in ('left', 'right')
                },
            }

    observations = source_projection_constraint.get('sourceFootHeelTrajectoryObservations') or []
    image_observations = source_projection_constraint.get('sourceFootHeelImageObservations') or []
    if not observations or not image_observations:
        base_directions = np.zeros((frame_count, 2, 3), dtype=float)
        for side_index, side in enumerate(('left', 'right')):
            ankle, toe = names.index(f'{side}_ankle'), names.index(f'{side}_foot')
            base_directions[:, side_index] = _unit(points[:, toe] - points[:, ankle])
        return base_directions, {
            'available': False, 'passed': False, 'reason': 'native_heel_observations_unavailable',
            'eventCount': 0, 'inversionFailureCount': 0,
            'observationCountBySide': {'left': 0, 'right': 0},
            'pitchAuthorityMaskBySide': {
                side: np.zeros(frame_count, dtype=bool).tolist()
                for side in ('left', 'right')
            },
            'pitchTrajectoryMaskBySide': {
                side: np.zeros(frame_count, dtype=bool).tolist()
                for side in ('left', 'right')
            },
        }

    _check_deadline(deadline)
    if contact_targets is not None:
        contact_targets = np.asarray(contact_targets, dtype=float)
        if (contact_targets.shape != points.shape
                or not np.isfinite(contact_targets).all()):
            raise ValueError('stationary contact targets must match finite rig points')

    projection = _source_projection_for_points(
        source_projection_constraint.get('projection'), payload)
    from .contact_constraints import motion_space_support_evidence
    support_evidence = motion_space_support_evidence(payload)
    payload_rest_pitch = payload.get('footRestPitchRadians')
    rest_pitch = dict(payload_rest_pitch) if isinstance(payload_rest_pitch, dict) else {}
    calibrated_pitch = calibrated_foot_rest_pitches(
        points, names, support_evidence,
        frame_times=[frame.get('sourceTimeSec') for frame in payload.get('frames', [])])
    rest_pitch_source_by_side = {}
    for side in ('left', 'right'):
        value = rest_pitch.get(side)
        if value is not None and np.isfinite(float(value)):
            rest_pitch_source_by_side[side] = 'payload'
        elif side in calibrated_pitch:
            rest_pitch[side] = calibrated_pitch[side]
            rest_pitch_source_by_side[side] = 'calibrated_source_full_sole'

    # Source heel baselines are rendered when the projection constraint is
    # prepared. If it carries that geometry context, its material rest pitch
    # must be the same one used for this inversion. Older synthetic callers
    # without the context remain supported, but a stale prepared baseline is
    # unresolved rather than silently inverted against a different shoe pose.
    geometry_payload = source_projection_constraint.get('footGeometryPayload')
    geometry_pitch_context = None
    baseline_pitch_context_errors = {}
    if isinstance(geometry_payload, dict):
        raw_context = geometry_payload.get('footRestPitchRadians')
        geometry_pitch_context = raw_context if isinstance(raw_context, dict) else {}
        for side in {row.get('motionSide') for row in observations
                     if row.get('motionSide') in ('left', 'right')}:
            selected = rest_pitch.get(side)
            context_value = geometry_pitch_context.get(side, 0.)
            try:
                selected_value = float(selected)
                context_value = float(context_value)
            except (TypeError, ValueError, OverflowError):
                selected_value = context_value = float('nan')
            if (not np.isfinite(selected_value) or not np.isfinite(context_value)
                    or not np.isclose(selected_value, context_value, rtol=0., atol=1e-8)):
                baseline_pitch_context_errors[side] = {
                    'reason': 'material_baseline_rest_pitch_context_mismatch',
                    'selectedRestPitchRadians': (selected_value if np.isfinite(selected_value) else None),
                    'baselineGeometryRestPitchRadians': (context_value if np.isfinite(context_value) else None),
                }

    event_pitches, inversion_failures, inversion_details = [], [], []
    for row in observations:
        _check_deadline(deadline)
        if row.get('motionSide') not in ('left', 'right'):
            continue
        context_error = baseline_pitch_context_errors.get(row.get('motionSide'))
        if context_error:
            detail = {
                'sourceTimeSec': row.get('sourceTime'),
                'sourceSide': row.get('sourceSide'),
                'motionSide': row.get('motionSide'),
                **context_error,
            }
            inversion_details.append(detail)
            inversion_failures.append(detail)
            continue
        pitch_delta, detail = _invert_native_heel_pitch(row, points, names, projection)
        inversion_details.append(detail)
        if pitch_delta is None:
            inversion_failures.append(detail)
        else:
            event_pitches.append((row, pitch_delta))

    unknown_geometry_pitches, unknown_geometry_failures, unknown_geometry_report = (
        _measured_unknown_heel_pitches(
            source_projection_constraint, points, names, projection, deadline))

    desired = np.zeros((frame_count, 2, 3), dtype=float)
    observation_counts = {}
    side_reports = {}
    pitch_delta_by_side = {}
    pitch_authority_by_side = {}
    pitch_trajectory_by_side = {}
    heading_calibration_by_side = {}
    frame_times = None
    frame_times_raw = [frame.get('sourceTimeSec') for frame in payload.get('frames', [])]
    try:
        candidate_frame_times = np.asarray(frame_times_raw, dtype=float)
    except (TypeError, ValueError, OverflowError):
        candidate_frame_times = np.empty(0, dtype=float)
    try:
        source_time_origin = float(source_projection_constraint.get('sourceTimeOriginSec', 0.))
    except (TypeError, ValueError, OverflowError):
        source_time_origin = float('nan')
    if np.isfinite(source_time_origin) and candidate_frame_times.ndim == 1:
        candidate_frame_times = candidate_frame_times - source_time_origin
    else:
        candidate_frame_times = np.empty(0, dtype=float)
    if (candidate_frame_times.shape == (frame_count,)
            and np.isfinite(candidate_frame_times).all()
            and (frame_count < 2 or np.all(np.diff(candidate_frame_times) > 0.))):
        frame_times = candidate_frame_times
    for side_index, side in enumerate(('left', 'right')):
        _check_deadline(deadline)
        ankle_name, toe_name = f'{side}_ankle', f'{side}_foot'
        if ankle_name not in names or toe_name not in names:
            side_reports[side] = {'available': False, 'reason': 'foot_joints_unavailable'}
            pitch_authority_by_side[side] = np.zeros(frame_count, dtype=bool).tolist()
            pitch_trajectory_by_side[side] = np.zeros(frame_count, dtype=bool).tolist()
            continue
        ankle_index, toe_index = names.index(ankle_name), names.index(toe_name)
        base_bone = points[:, toe_index] - points[:, ankle_index]
        base_directions = _unit(base_bone)
        desired[:, side_index] = base_directions
        lengths = np.linalg.norm(base_bone, axis=1)
        if np.any(lengths <= 1e-9):
            side_reports[side] = {'available': False, 'reason': 'foot_length_unavailable'}
            pitch_authority_by_side[side] = np.zeros(frame_count, dtype=bool).tolist()
            pitch_trajectory_by_side[side] = np.zeros(frame_count, dtype=bool).tolist()
            continue
        rest = rest_pitch.get(side)
        if rest is None or not np.isfinite(float(rest)):
            side_reports[side] = {'available': False, 'reason': 'rest_pitch_unavailable'}
            pitch_authority_by_side[side] = np.zeros(frame_count, dtype=bool).tolist()
            pitch_trajectory_by_side[side] = np.zeros(frame_count, dtype=bool).tolist()
            continue

        fullsole = pinned[:, ankle_index] & pinned[:, toe_index]
        side_geometry_pitches = []
        for geometry_row, target_delta in unknown_geometry_pitches:
            if geometry_row.get('motionSide') != side:
                continue
            if (geometry_row.get('directionOnlyNeutralWithinNoise')
                    and geometry_row.get('nativePitchMatchesSourceImage')):
                # Use native orientation only when its forward-projected heel
                # lift agrees with the retained image evidence.
                cursor = float(geometry_row['leftFrame']) + float(geometry_row['alpha'])
                left = int(np.clip(math.floor(cursor), 0, frame_count - 1))
                right = min(left + 1, frame_count - 1)
                alpha = cursor - math.floor(cursor)
                native_bone = ((points[right, toe_index] - points[right, ankle_index]) * alpha
                               + (points[left, toe_index] - points[left, ankle_index]) * (1. - alpha))
                native_horizontal = math.hypot(float(native_bone[0]), float(native_bone[2]))
                if native_horizontal <= 1e-9:
                    continue
                target_delta = math.atan2(float(native_bone[1]), native_horizontal) - float(rest)
            side_geometry_pitches.append((geometry_row, target_delta))
        pitch_delta, pitch_authority, pitch_trajectory, mapping_report = _shape_preserving_source_pitch(
            source_projection_constraint, frame_count, side, fullsole,
            event_pitches, geometry_pitches=side_geometry_pitches,
            frame_times=frame_times, fps=fps, deadline=deadline)
        count = mapping_report['observationCount']
        observation_counts[side] = count
        pitch_delta_by_side[side] = pitch_delta.tolist()
        pitch_authority_by_side[side] = pitch_authority.tolist()
        pitch_trajectory_by_side[side] = pitch_trajectory.tolist()
        horizontal = base_bone.copy()
        horizontal[:, 1] = 0.
        horizontal_lengths = np.linalg.norm(horizontal, axis=1)
        heading = horizontal / np.maximum(horizontal_lengths[:, None], 1e-12)
        source_heading_track = heading.copy()
        from scipy.interpolate import PchipInterpolator

        # Full-sole paired targets are authoritative for heading at each
        # measured stance sample. Interpolate their yaw offsets over the same
        # anchor's geometric trajectory so toe-only/unknown rows retain their
        # observed heading changes without snapping between source and target
        # yaw at contact-state boundaries.
        geometry_anchor_by_key = {
            (row.get('sourceSide'), round(float(row['sourceTime']), 6),
             row.get('motionSide')): row.get('stationaryAnchorGroupId')
            for row, _delta in unknown_geometry_pitches
            if row.get('motionSide') == side
        }
        image_rows = []
        for row in image_observations:
            if row.get('motionSide') != side or row.get('state') not in (
                    'full_sole', 'toe_only', 'unknown'):
                continue
            anchor_group = row.get('stationaryAnchorGroupId')
            if anchor_group is None:
                try:
                    anchor_group = geometry_anchor_by_key.get((
                        row.get('sourceSide'), round(float(row['sourceTime']), 6),
                        row.get('motionSide')))
                except (KeyError, TypeError, ValueError, OverflowError):
                    anchor_group = None
            if anchor_group is not None:
                image_rows.append({**row, 'stationaryAnchorGroupId': anchor_group})
        group_rows = {}
        for row in image_rows:
            group_rows.setdefault(row['stationaryAnchorGroupId'], []).append(row)
        timeline = (np.asarray(frame_times, dtype=float)
                    if frame_times is not None else np.arange(frame_count) / float(fps))
        heading_calibration = []
        for rows in group_rows.values():
            _check_deadline(deadline)
            stance_times, stance_offsets = [], []
            group_times = []
            for row in rows:
                try:
                    row_time = (float(row['sourceTime']) if frame_times is not None
                                else (float(row['leftFrame']) + float(row['alpha'])) / float(fps))
                    if np.isfinite(row_time):
                        group_times.append(row_time)
                except (KeyError, TypeError, ValueError, OverflowError):
                    continue
                if row.get('state') != 'full_sole' or contact_targets is None:
                    continue
                try:
                    cursor = float(row['leftFrame']) + float(row['alpha'])
                except (KeyError, TypeError, ValueError, OverflowError):
                    continue
                if not np.isfinite(cursor):
                    continue
                left = int(np.clip(math.floor(cursor), 0, frame_count - 1))
                right = min(left + 1, frame_count - 1)
                alpha = cursor - math.floor(cursor)
                raw_bone = (base_bone[left] * (1. - alpha)
                            + base_bone[right] * alpha)
                target_bone = (
                    (contact_targets[right, toe_index] - contact_targets[right, ankle_index]) * alpha
                    + (contact_targets[left, toe_index] - contact_targets[left, ankle_index]) * (1. - alpha))
                raw_bone[1] = 0.
                target_bone[1] = 0.
                if np.linalg.norm(raw_bone) <= 1e-9 or np.linalg.norm(target_bone) <= 1e-9:
                    continue
                raw_yaw = math.atan2(float(raw_bone[0]), float(raw_bone[2]))
                target_yaw = math.atan2(float(target_bone[0]), float(target_bone[2]))
                offset = math.atan2(math.sin(target_yaw - raw_yaw),
                                    math.cos(target_yaw - raw_yaw))
                stance_times.append(row_time)
                stance_offsets.append(offset)
            if not stance_times or not group_times:
                continue
            order = np.argsort(stance_times)
            stance_times = np.asarray(stance_times, dtype=float)[order]
            stance_offsets = np.unwrap(np.asarray(stance_offsets, dtype=float)[order])
            # Collapse duplicate timestamp samples without inventing a new
            # heading; circular averaging handles the +/-pi boundary.
            unique_times, unique_offsets = [], []
            for row_time in np.unique(stance_times):
                values = stance_offsets[stance_times == row_time]
                unique_times.append(float(row_time))
                unique_offsets.append(math.atan2(float(np.mean(np.sin(values))),
                                                 float(np.mean(np.cos(values)))))
            unique_times = np.asarray(unique_times, dtype=float)
            unique_offsets = np.unwrap(np.asarray(unique_offsets, dtype=float))
            if unique_times.size > 1:
                offset_track = PchipInterpolator(unique_times, unique_offsets,
                                                 extrapolate=False)
                in_group = ((timeline >= min(group_times) - 1e-8)
                            & (timeline <= max(group_times) + 1e-8)
                            & (timeline >= unique_times[0] - 1e-8)
                            & (timeline <= unique_times[-1] + 1e-8)
                            & np.asarray(pitch_trajectory, dtype=bool))
            else:
                offset_track = None
                in_group = ((timeline >= min(group_times) - 1e-8)
                            & (timeline <= max(group_times) + 1e-8)
                            & np.asarray(pitch_trajectory, dtype=bool))
            if np.any(in_group):
                offsets = (np.full(np.count_nonzero(in_group), unique_offsets[0])
                           if offset_track is None
                           else np.asarray(offset_track(timeline[in_group]), dtype=float))
                source_yaw = np.arctan2(source_heading_track[in_group, 0],
                                        source_heading_track[in_group, 2])
                calibrated_yaw = source_yaw + offsets
                heading[in_group, 0] = np.sin(calibrated_yaw)
                heading[in_group, 2] = np.cos(calibrated_yaw)
                heading[in_group] = _unit(heading[in_group])
            raw_stance_heading = source_heading_track[
                int(np.argmin(np.abs(timeline - unique_times[0])))]
            target_stance_heading = heading[
                int(np.argmin(np.abs(timeline - unique_times[0])))]
            heading_calibration.append({
                'stationaryAnchorGroupId': rows[0].get('stationaryAnchorGroupId'),
                'sourceStanceHeadingYawDegrees': float(np.rad2deg(math.atan2(
                    raw_stance_heading[0], raw_stance_heading[2]))),
                'targetStanceHeadingYawDegrees': float(np.rad2deg(math.atan2(
                    target_stance_heading[0], target_stance_heading[2]))),
                'appliedYawOffsetDegrees': float(np.rad2deg(unique_offsets[0])),
                'measuredYawOffsetCount': int(len(unique_times)),
                'trajectoryFrameCount': int(np.count_nonzero(in_group)),
            })
        pitch = float(rest) + pitch_delta
        pitch_directions = _unit(
            heading * np.cos(pitch)[:, None]
            + np.array([0., 1., 0.])[None, :] * np.sin(pitch)[:, None])
        desired[pitch_trajectory, side_index] = pitch_directions[pitch_trajectory]
        side_reports[side] = {
            'available': count > 0,
            'restPitchRadians': float(rest),
            'restPitchSource': rest_pitch_source_by_side.get(side, 'unavailable'),
            'observationCount': int(count),
            **mapping_report,
            'fullSoleDirichletFrameCount': int(np.count_nonzero(fullsole)),
            'pitchDeltaMinimumDegrees': float(np.rad2deg(pitch_delta.min())),
            'pitchDeltaMaximumDegrees': float(np.rad2deg(pitch_delta.max())),
            'maximumPitchDeltaDegrees': float(np.max(np.abs(np.rad2deg(pitch_delta)))),
        }
        heading_calibration_by_side[side] = heading_calibration

    observed_sides = {row.get('motionSide') for row in observations
                      if row.get('motionSide') in ('left', 'right')}
    return desired, {
        'available': bool(event_pitches),
        'passed': bool(event_pitches) and not inversion_failures
                  and all(side_reports.get(side, {}).get('available') for side in observed_sides),
        'method': 'source_timed_shape_preserving_closed_form_heel_pitch',
        'eventCount': len(event_pitches),
        'inversionFailureCount': len(inversion_failures),
        'inversionFailures': inversion_failures,
        'unknownGeometryFailureCount': len(unknown_geometry_failures),
        'unknownGeometryFailures': unknown_geometry_failures,
        'unknownGeometry': unknown_geometry_report,
        'baselinePitchContextErrorsBySide': baseline_pitch_context_errors,
        **({'reason': 'material_baseline_rest_pitch_context_mismatch'}
           if baseline_pitch_context_errors else {}),
        'inversionDetails': inversion_details,
        'observationCountBySide': observation_counts,
        'pitchDeltaRadiansBySide': pitch_delta_by_side,
        'pitchAuthorityMaskBySide': pitch_authority_by_side,
        'pitchTrajectoryMaskBySide': pitch_trajectory_by_side,
        'stationaryHeadingCalibrationBySide': heading_calibration_by_side,
        'sides': side_reports,
        'projection': projection.tolist(),
        'fps': float(fps),
    }
