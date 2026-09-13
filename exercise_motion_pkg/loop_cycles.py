"""Choose observed repetition boundaries before attempting cyclic fitting.

Selection never synthesizes a bridge, fades a restart, or removes root travel.
The returned intervals are proposals: the fitted playback must still pass all
anatomical, contact, motion-preservation and seam checks.
"""
from copy import deepcopy

import numpy as np
from scipy.ndimage import gaussian_filter1d

from .contact_constraints import contact_frame_bounds, motion_support_contacts
from .physical_validation import body_scale
from .sequence_stabilization import contact_mask, pose_digest
from .temporal_quality import refresh_motion_bounds
from .repetition_phase import complete_repetition


def rank_loop_cycles(payload, *, max_candidates=5, endpoint_correction_ratio=0., diagnostics=None,
                     phase_values=None):
    """Rank matching poses with compatible velocity, support and full excursion.

    End frames are exclusive: the matching endpoint is the first sample of the
    next repetition, not a duplicated pause at the end of this one.
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
    minimum_frames = max(6, round(fps*.5))
    proposals = []
    counts = {'intervalPairs': 0, 'contactCompatible': 0, 'endpointFeasible': 0,
              'directionCompatible': 0, 'completePhase': 0, 'rangePreserved': 0}
    if diagnostics is not None:
        diagnostics.update(counts=counts, endpointGapLimitMeters=max(.08, 2*endpoint_correction_ratio)*scale)
    for start in range(count-minimum_frames):
        for stop in range(start+minimum_frames, count):
            counts['intervalPairs'] += 1
            if not np.array_equal(contacts[start], contacts[stop]):
                continue
            counts['contactCompatible'] += 1
            jump = float(np.max(np.linalg.norm(points[start]-points[stop], axis=-1)))
            # Bounded fit feasibility, not permission to accept a final seam.
            if jump > max(.08, 2*endpoint_correction_ratio)*scale:
                continue
            counts['endpointFeasible'] += 1
            left, right = velocity[start].ravel(), velocity[stop].ravel()
            magnitude = np.linalg.norm(left)*np.linalg.norm(right)
            if magnitude > (.05*scale)**2 and np.dot(left, right) < 0:
                continue
            counts['directionCompatible'] += 1
            mismatch = float(np.sqrt(np.mean((left-right)**2)))
            score = (jump+.15*mismatch)/scale + .01*(1-(stop-start)/count)
            proposals.append((score, start, stop, jump, mismatch))
    accepted = []
    for score, start, stop, jump, mismatch in sorted(proposals):
        complete, _ = complete_repetition(phase_track[start:stop].tolist())
        if not complete:
            continue
        counts['completePhase'] += 1
        retained = np.linalg.norm(np.ptp(features[start:stop], axis=0), axis=-1)
        if np.any(retained[moving] < .9*full_range[moving]):
            continue
        counts['rangePreserved'] += 1
        # Do not spend every bounded fit attempt on the adjacent sample of the
        # same proposed phase. Keep alternatives separated in phase or duration.
        if any(abs(start-c['startFrame']) < max(2, round(fps*.1))
               and abs(stop-c['stopFrameExclusive']) < max(2, round(fps*.1)) for c in accepted):
            continue
        accepted.append({'startFrame': start, 'stopFrameExclusive': stop,
                         'score': score, 'endpointGapMeters': jump,
                         'velocityMismatchRmsMetersPerSecond': mismatch,
                         'requiresEndpointCorrection': jump > .08*scale,
                         'minimumRetainedRangeRatio': float(np.min(retained[moving]/full_range[moving]))})
        if len(accepted) >= max_candidates:
            break
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
    patches = evidence.get('footPatchEvidence') or {}
    if 'contacts' in patches:
        patches['contacts'] = clipped_contacts(patches['contacts'])
    for foot in (patches.get('feet') or {}).values():
        states = foot.get('states') or []
        if states:
            # Keep the neighboring observations at either boundary, so slicing
            # cannot hide contradictory release evidence between sample times.
            first = int(np.floor(start*(len(states)-1)/(original_count-1)))
            last = int(np.ceil((stop-1)*(len(states)-1)/(original_count-1)))
            foot['states'] = states[first:last+1]
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
