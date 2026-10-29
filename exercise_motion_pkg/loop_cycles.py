"""Choose observed repetition boundaries before attempting cyclic fitting.

Selection never synthesizes a bridge, fades a restart, or removes root travel.
The returned intervals are proposals: the fitted playback must still pass all
anatomical, contact, motion-preservation and seam checks.
"""
from copy import deepcopy

import numpy as np
from scipy.ndimage import gaussian_filter1d

from .contact_constraints import (contact_frame_bounds, motion_support_contacts,
                                 motion_space_support_evidence, vertical_only_contact_mask)
from .physical_validation import body_scale
from .sequence_stabilization import contact_mask, pose_digest
from .temporal_quality import refresh_motion_bounds
from .repetition_phase import complete_repetition


def _boundary_motion_metrics(points, *, fps, scale):
    from .loop_seam import seam_quality_metrics, MAX_RANKED_SOURCE_WRAP_RATIO
    seam = seam_quality_metrics(points, fps=fps, scale=scale)
    wrap_ratio = max(
        seam['seamStepExcessMeters'] / seam['seamStepExcessLimitMeters'],
        seam['seamVelocityMismatchMetersPerSecond'] / seam['seamVelocityMismatchLimitMetersPerSecond'],
    )
    incoming, outgoing = points[-1] - points[-2], points[1] - points[0]
    mismatch = float(np.max(np.linalg.norm(outgoing - incoming, axis=-1))) * fps
    # A wrap step cannot match both observed tangents within the seam limit
    # when their separation exceeds twice that limit (triangle inequality).
    limit = 2 * seam['seamVelocityMismatchLimitMetersPerSecond']
    reasons = []
    if wrap_ratio > MAX_RANKED_SOURCE_WRAP_RATIO:
        reasons.append('source_support_wrap_unrepairable')
    if mismatch > limit:
        reasons.append('source_boundary_tangents_incompatible')
    return {'passed': not reasons, 'rejectionReasons': reasons,
            'failureOwner': 'source' if reasons else None,
            'sourceSupportWrapOverLimitRatio': float(wrap_ratio),
            'maximumEndpointVelocityDifferenceMetersPerSecond': mismatch,
            'endpointVelocityDifferenceLimitMetersPerSecond': float(limit)}


def cycle_boundary_motion_metrics(payload, selection=None):
    """Check actual included endpoint edges, independently of phase completeness."""
    names, frames = payload.get('jointNames', []), payload.get('frames', [])
    start = int((selection or {}).get('startFrame', 0))
    stop = int((selection or {}).get('stopFrameExclusive', len(frames)))
    fps = float(payload.get('fps', 0))
    if (not names or not (0 <= start < stop <= len(frames)) or stop - start < 3
            or not np.isfinite(fps) or fps <= 0):
        return {'passed': False, 'rejectionReasons': ['boundary_motion_unresolved']}
    points = np.asarray([[f['joints'][n] for n in names] for f in frames], dtype=float)
    if not np.isfinite(points).all():
        return {'passed': False, 'rejectionReasons': ['boundary_motion_unresolved']}
    indices = [i for i, name in enumerate(names)
               if name == 'pelvis' or name.endswith(('hip', 'knee', 'ankle', 'foot'))]
    if not indices:
        return {'passed': False, 'rejectionReasons': ['boundary_motion_unresolved']}
    return _boundary_motion_metrics(points[start:stop, indices], fps=fps,
                                    scale=body_scale(points, names))


def rank_loop_cycles(payload, *, max_candidates=5, endpoint_correction_ratio=0., diagnostics=None,
                     phase_values=None, allow_repairable_support_wrap=False):
    """Rank matching poses with compatible velocity, support and full excursion.

    End frames are exclusive: the matching endpoint is the first sample of the
    next repetition, not a duplicated pause at the end of this one.

    Opposite endpoint velocity is expected at extreme-to-extreme returns.
    Incomplete windows with opposite phase or whole-body velocity are rejected
    as eccentric/concentric crossings. Complete returns may carry a soft
    whole-body opposite-velocity score penalty, but must have compatible
    support/root boundary tangents. Source wraps above
    MAX_RANKED_SOURCE_WRAP_RATIO on support joints are not proposed.
    """
    frames, names = payload['frames'], payload['jointNames']
    count, fps = len(frames), float(payload['fps'])
    if count < 7 or fps <= 0:
        return []
    points = np.asarray([[f['joints'][n] for n in names] for f in frames])
    if not np.isfinite(points).all():
        return []
    contacts = contact_mask(payload, names, count)
    if contacts is None:
        return []
    contacts |= vertical_only_contact_mask(
        motion_space_support_evidence(payload), names, count,
    )
    # Use the same whole-interval support authority as the fitter. Fragmented
    # landmark visibility must not turn a confirmed stationary stance into
    # incompatible endpoint contacts and exclude the actual return cycle.
    from .support_geometry import evidence_is_complete, support_evidence
    support = support_evidence(payload)
    if (support.get('required') and support.get('status') == 'confirmed'
            and evidence_is_complete(support, names)):
        for name in support['stationaryJoints']:
            contacts[:, names.index(name)] = True
    scale = body_scale(points, names)
    root = names.index('pelvis')
    features = np.concatenate([points[:, root:root+1], points-points[:, root:root+1]], axis=1)
    if phase_values is not None:
        signal = np.asarray(phase_values, dtype=float)
        if signal.shape != (count,) or not np.isfinite(signal).all():
            return []
        # The declared moving/reference relationship owns repetition excursion.
        # Incidental head/foot drift across multiple repetitions is not a range
        # that each single repetition must reproduce. Whole-body endpoint and
        # velocity feasibility below still use every joint.
        features = signal[:, None, None]
    full_range = np.linalg.norm(np.ptp(features, axis=0), axis=-1)
    moving = full_range > .1*scale
    if not moving.any():
        return []  # A held pose is not evidence of a complete repetition.
    velocity = np.gradient(gaussian_filter1d(points, max(.5, fps*.04), axis=0), axis=0)*fps
    # The principal trajectory is invariant to world rotation. Use the same
    # phase topology as final validation, before spending a fit attempt.
    flattened = features.reshape(count, -1)
    centered = flattened - flattened.mean(axis=0)
    principal = np.linalg.svd(centered, full_matrices=False)[2][0]
    phase_track = gaussian_filter1d(centered @ principal, max(.5, fps*.04))
    phase_velocity = np.gradient(phase_track) * fps
    phase_span = float(np.ptp(phase_track))
    phase_speed_floor = max(.05 * phase_span * fps / max(count - 1, 1), 1e-6)
    minimum_frames = max(6, round(fps*.5))
    counts = {'intervalPairs': 0, 'contactCompatible': 0, 'endpointFeasible': 0,
              'directionCompatible': 0, 'completePhase': 0, 'rangePreserved': 0,
              'wrapFeasible': 0, 'boundaryMotionCompatible': 0}
    if diagnostics is not None:
        diagnostics.update(counts=counts, endpointGapLimitMeters=max(.08, 2*endpoint_correction_ratio)*scale)
    from .loop_seam import (
        seam_errors, MAX_STEP_EXCESS_BODY_RATIO, MAX_VELOCITY_MISMATCH_BODY_RATIO,
        MAX_RANKED_SOURCE_WRAP_RATIO)
    support_idx = [i for i, name in enumerate(names)
                   if name == 'pelvis' or name.endswith(('hip', 'knee', 'ankle', 'foot'))]
    complete_proposals = []
    for start in range(count-minimum_frames):
        # The final observed sample can be the return point of a complete
        # cycle. ``stop == count`` is an exclusive bound over every frame; use
        # the last observed frame as its endpoint evidence because no next-
        # cycle sample exists in the clip.
        for stop in range(start+minimum_frames, count + 1):
            counts['intervalPairs'] += 1
            endpoint_index = stop if stop < count else count - 1
            if not np.array_equal(contacts[start], contacts[endpoint_index]):
                continue
            counts['contactCompatible'] += 1
            jump = float(np.max(np.linalg.norm(points[start]-points[endpoint_index], axis=-1)))
            # Bounded fit feasibility, not permission to accept a final seam.
            if jump > max(.08, 2*endpoint_correction_ratio)*scale:
                continue
            counts['endpointFeasible'] += 1
            phase_window = phase_track[start:stop]
            if stop < count:
                phase_for_complete = np.concatenate([phase_window, phase_track[stop:stop + 1]])
            else:
                phase_for_complete = np.concatenate([phase_window, phase_track[start:start + 1]])
            complete, _ = complete_repetition(phase_for_complete.tolist())
            # Extreme-to-extreme returns reverse phase velocity at the apex by
            # construction. Hard-reject opposite motion only for incomplete
            # windows (eccentric/concentric pose crossings and half-reps).
            phase_left = float(phase_velocity[start])
            phase_right = float(phase_velocity[endpoint_index])
            phase_opposite = (abs(phase_left) > phase_speed_floor
                              and abs(phase_right) > phase_speed_floor
                              and phase_left * phase_right < 0)
            left, right = velocity[start].ravel(), velocity[endpoint_index].ravel()
            magnitude = np.linalg.norm(left)*np.linalg.norm(right)
            body_opposite = bool(magnitude > (.05*scale)**2 and np.dot(left, right) < 0)
            if not complete and (phase_opposite or body_opposite):
                continue
            counts['directionCompatible'] += 1
            if not complete:
                continue
            counts['completePhase'] += 1
            mismatch = float(np.sqrt(np.mean((left-right)**2)))
            # Prefer intervals whose source wrap already looks playback-feasible.
            # Hard-reject uses support/lower-body joints so incidental head drift
            # cannot empty otherwise-valid geometric proposals.
            _, excess, increments = seam_errors(points[start:stop])
            support_points = points[start:stop][:, support_idx] if support_idx else points[start:stop]
            step_ratio = float(np.max(excess, initial=0.)) / max(
                MAX_STEP_EXCESS_BODY_RATIO * scale, 1e-9)
            vel_ratio = (
                float(np.max(np.linalg.norm(increments, axis=-1), initial=0.)) * fps
                / max(MAX_VELOCITY_MISMATCH_BODY_RATIO * scale, 1e-9))
            wrap_ratio = max(step_ratio, vel_ratio)
            boundary = _boundary_motion_metrics(support_points, fps=fps, scale=scale)
            endpoint_support_pinned = all(
                name in names and contacts[frame, names.index(name)]
                for frame in (start, endpoint_index)
                for side in ('left', 'right')
                for name in (f'{side}_ankle', f'{side}_foot')
            )
            repairable_wrap = bool(allow_repairable_support_wrap and endpoint_support_pinned)
            if (boundary['sourceSupportWrapOverLimitRatio'] > MAX_RANKED_SOURCE_WRAP_RATIO
                    and not repairable_wrap):
                continue
            counts['wrapFeasible'] += 1
            deferred_reasons = boundary.get('rejectionReasons') or []
            if (not boundary['passed']
                    and not (repairable_wrap
                             and deferred_reasons == ['source_support_wrap_unrepairable'])):
                if diagnostics is not None:
                    previous = diagnostics.get('boundaryMotion')
                    if (previous is None or boundary['maximumEndpointVelocityDifferenceMetersPerSecond']
                            < previous['maximumEndpointVelocityDifferenceMetersPerSecond']):
                        diagnostics['boundaryMotion'] = boundary
                continue
            counts['boundaryMotionCompatible'] += 1
            # Whole-body opposite velocity is advisory on complete returns.
            score = (wrap_ratio + 0.2 * (jump / scale) + 0.05 * (mismatch / scale)
                     + (0.25 if body_opposite else 0.)
                     + .01 * (1 - (stop - start) / count))
            retained = np.linalg.norm(np.ptp(features[start:stop], axis=0), axis=-1)
            complete_proposals.append(
                (score, start, stop, jump, mismatch, wrap_ratio, retained))
    # Whole-clip feature range includes multi-rep drift. A single observed cycle
    # must preserve one-repetition excursion, not incidental drift across the
    # entire source window (same intent as the phase_values path above).
    if complete_proposals:
        cycle_range = np.max([retained for *_, retained in complete_proposals], axis=0)
        moving_cycle = cycle_range > .1 * scale
    else:
        cycle_range = full_range
        moving_cycle = moving
    # A collection of nearly still windows is not a reference repetition.
    # Fall back to the observed excursion before filtering, not just when
    # reporting the ratio; otherwise tiny pauses consume every proposal slot.
    range_basis = cycle_range if moving_cycle.any() else full_range
    moving_basis = moving_cycle if moving_cycle.any() else moving
    accepted = []
    for score, start, stop, jump, mismatch, wrap_ratio, retained in sorted(complete_proposals):
        if np.any(retained[moving_basis] < .9 * range_basis[moving_basis]):
            continue
        counts['rangePreserved'] += 1
        # Nearby boundary shifts of the same repetition are not useful fit
        # alternatives: they preserve nearly all the same frames and tend to
        # produce the same support/root-travel failure. Deduplicate by interval
        # overlap so candidates separated by just over 100 ms do not consume
        # another expensive controlled-motion solve.
        candidate_length = stop - start
        duplicate_overlap = any(
            (overlap := max(
                0,
                min(stop, candidate['stopFrameExclusive'])
                - max(start, candidate['startFrame']),
            ))
            / max(
                min(
                    candidate_length,
                    candidate['stopFrameExclusive'] - candidate['startFrame'],
                ),
                1,
            )
            >= .9
            for candidate in accepted
        )
        if duplicate_overlap:
            continue
        accepted.append({'startFrame': start, 'stopFrameExclusive': stop,
                         'score': score, 'endpointGapMeters': jump,
                         'velocityMismatchRmsMetersPerSecond': mismatch,
                         'sourceWrapOverLimitRatio': wrap_ratio,
                         'sourceWrapDeferredToSupportInitialization': bool(
                             allow_repairable_support_wrap and all(
                                 name in names and contacts[frame, names.index(name)]
                                 for frame in (start, stop if stop < count else count - 1)
                                 for side in ('left', 'right')
                                 for name in (f'{side}_ankle', f'{side}_foot'))),
                         'requiresEndpointCorrection': jump > .08*scale,
                         'minimumRetainedRangeRatio': float(
                             np.min(retained[moving_basis] / np.maximum(range_basis[moving_basis], 1e-12))
                             if moving_basis.any() else 1.)})
        if len(accepted) >= max_candidates:
            break
    if diagnostics is not None and counts['boundaryMotionCompatible']:
        diagnostics.pop('boundaryMotion', None)
    return accepted


def slice_loop_cycle(payload, selection):
    """Slice a proposal while preserving source timing and contact provenance."""
    start, stop = selection['startFrame'], selection['stopFrameExclusive']
    original_count = len(payload['frames'])
    if not 0 <= start < stop <= original_count or stop-start < 7:
        raise ValueError('Invalid cycle interval')
    if payload.get('fixedRig'):
        raise ValueError('Select a source cycle before fitting its fixed rig')
    result = deepcopy(payload)
    fps, count = float(payload['fps']), stop-start
    result['frames'] = result['frames'][start:stop]
    for index, frame in enumerate(result['frames']):
        frame.setdefault('cycleSourceTimeSec', frame['timeSec'])
        frame.setdefault('cycleSourceFrameIndex', start+index)
        frame['frameIndex'] = index
        frame['timeSec'] = index/fps
    evidence = deepcopy(payload.get('sourceFootSupportEvidence') or {})

    def clipped_contacts(records):
        contacts = []
        for contact in records:
            # Observed foot-patch intervals stay on their native source clock.
            # The fit view maps them onto this cycle's sourceTimeSec rows.
            if contact.get('supportKind') == 'observed_foot_patch':
                contacts.append(contact)
                continue
            first, last = contact_frame_bounds(contact, original_count)
            first, last = max(first, start), min(last, stop-1)
            if first > last:
                continue
            contacts.append({**contact, 'startFrame': first-start, 'endFrame': last-start,
                             'startRatio': (first-start)/(count-1), 'endRatio': (last-start)/(count-1)})
        return contacts

    contacts = clipped_contacts(motion_support_contacts(evidence))
    if 'footContactCandidates' in evidence:
        evidence['footContactCandidates'] = clipped_contacts(evidence['footContactCandidates'])
    # Keep footPatchEvidence native and internally aligned: states, rays,
    # heel observations, timestamps and patch contacts are one source-clock
    # record. The fit-time mapper selects the cycle rows without rewriting it.
    # Normalize the three accepted input representations to avoid retaining
    # unsliced duplicate contact intervals in legacy fields.
    evidence.pop('feet', None)
    evidence.pop('supportContacts', None)
    evidence['contacts'] = contacts
    result['sourceFootSupportEvidence'] = evidence
    result['frameCount'] = count
    result['totalFrames'] = count
    result['durationSec'] = count/fps
    result['loop'] = {'enabled': True, 'startFrame': 0, 'endFrame': count-1,
                      'durationSec': count/fps, 'transition': 'continuous',
                      'label': 'Observed repetition'}
    result['loopCycleSelection'] = {**selection, 'inputPoseDigest': pose_digest(payload),
                                    'inputFrameCount': original_count,
                                    'sourceStartTimeSec': payload['frames'][start]['timeSec'],
                                    'sourceStopTimeSec': payload['frames'][stop-1]['timeSec']+1/fps}
    result.pop('controlledMotionFit', None)
    result.pop('sequenceStabilization', None)
    refresh_motion_bounds(result)
    return result
