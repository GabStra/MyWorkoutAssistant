"""Shared, explicitly observed support constraints for fitting and acceptance.

Support planes are geometry evidence, not exercise-name templates. Unknown
contacts must not be promoted to confirmed contacts by the motion solver.
"""
from __future__ import annotations

import numpy as np

POLICY_VERSION = 5
TOLERANCE_METERS = .005


def observed_foot_patch_stationarity_threshold(body_span: float) -> float:
    """Return the body-relative local-range limit used for observed shoe patches."""
    return TOLERANCE_METERS / max(float(body_span), 1e-9)


def declare_support_requirements(payload, contract):
    """Recheck observed contact authority; contracts do not establish contact."""
    from .body_support_observation import remove_unobserved_torso_support
    for key in ('sourceFootSupportEvidence', 'motionSpaceSupportEvidence'):
        evidence = payload.get(key)
        if isinstance(evidence, dict):
            remove_unobserved_torso_support(evidence)


def support_evidence(payload):
    from .body_support_observation import materialize_stationary_sole_support
    # The fitter uses a temporally materialized motion-space view. Rebuild that
    # same view for downstream geometry checks so cached full-clip foot anchors
    # cannot outlive contradictory or incomplete contact observations.
    materialized = materialize_stationary_sole_support(payload)
    support = dict(materialized.get('bodySupport', {}))
    # Geometry residuals and their downstream validators need the same mapped
    # per-frame contact authority as the fitter. A bodySupport summary alone
    # loses releases and unknown frames at the edges of a source interval.
    for key in ('contacts', 'supportContacts', 'feet', 'footPatchEvidence',
                '_fitFrameStateIndices', '_fitFrameCount'):
        if key in materialized:
            support[key] = materialized[key]
    pitches = payload.get('footRestPitchRadians')
    if isinstance(pitches, dict):
        support = dict(support)
        support['materialFootRestPitchRadians'] = pitches
    return support


def support_contact_readiness(payload, *, evidence=None):
    """Classify support evidence without confusing missing evidence with conflict.

    Per-side contact observations are consumed only when the materializer has
    produced the same exact-time point contact for the fitter. A coarse
    stationary summary or a stationary ankle track alone is not contact proof.
    """
    from . import body_support_observation
    materialize_stationary_sole_support = body_support_observation.materialize_stationary_sole_support
    validated_body_support_answer = body_support_observation.validated_body_support_answer
    from .contact_constraints import (
        _body_timeline_parent_exposure_time, is_stationary_contact, motion_support_contacts,
        source_support_mapping_unresolved,
    )
    if source_support_mapping_unresolved(payload):
        return _support_readiness_result(
            status='incomplete', required_sides=(), reason='source_support_mapping_unavailable',
            evaluated=False)
    evidence = materialize_stationary_sole_support(payload) if evidence is None else evidence
    observed = evidence.get('bodySupportObservation') or {}
    answer = validated_body_support_answer(observed)
    if observed and answer is None:
        return _support_readiness_result(
            status='incomplete', required_sides=('left', 'right'),
            reason='source_support_observation_invalid')
    required = {side for side in ('left', 'right')
                if answer is not None
                and answer.get(f'{side}Foot') in {'stationary_full_sole', 'stationary_forefoot'}}
    support = evidence.get('bodySupport') or {}
    timeline_raw_present = isinstance(observed, dict) and 'contactTimeline' in observed
    timeline_rows = body_support_observation.validated_body_support_contact_timeline(observed)
    timeline_rows = timeline_rows if isinstance(timeline_rows, list) else []
    timeline_by_sample = {
        str(row.get('sampleId')): row for row in timeline_rows
        if isinstance(row, dict) and row.get('sampleId') is not None
    }
    mapping = evidence.get('motionSpaceMapping') or {}
    swapped = mapping.get('bilateralAssignment') == 'swapped'
    supported = set()
    # A full-cycle sole plane is also a fitter-consumed physical constraint,
    # but only when the current, per-side patch proves uninterrupted full-sole
    # contact and the materializer retained its exact-video identity.
    support_digest = str(support.get('sourceVideoSha256') or '').casefold()
    observed_digest = str(observed.get('sourceVideoSha256') or '').casefold()
    if (support.get('status') == 'confirmed' and support_digest
            and support_digest == observed_digest):
        from .body_support_observation import _has_uninterrupted_full_sole_patch
        for sole in support.get('soleContacts') or []:
            joints = sole.get('joints') or []
            if len(joints) != 3 or not joints[1].endswith('_ankle'):
                continue
            side = joints[1].split('_', 1)[0]
            if _has_uninterrupted_full_sole_patch(evidence, side):
                supported.add(side)
    # The producer materializes these same observations as exact-time point
    # contacts. Require the join so readiness cannot pass while the fitter sees
    # no corresponding physical constraint.
    for contact in motion_support_contacts(evidence):
        name = str(contact.get('jointName') or '')
        if not name.endswith(('_ankle', '_foot')) or not is_stationary_contact(contact):
            continue
        # A reconstruction-compatible track is not independent contact evidence.
        if contact.get('reconstructed3dSupport') or contact.get('continuousSupportSource'):
            continue
        side = name.split('_', 1)[0]
        sample_id = contact.get('contactTimelineSampleId')
        if sample_id is not None:
            row = timeline_by_sample.get(str(sample_id))
            expected_rig_side = (('right' if row.get('side') == 'left' else 'left')
                                 if row is not None and swapped else (row or {}).get('side'))
            expected_state = {'full_sole': 'full_sole', 'forefoot': 'toe_only',
                              'heel_only': 'heel_only'}.get((row or {}).get('contactState'))
            source_timeline_mapping = evidence.get('_fitSourceTimelineMapping')
            parent_exposure_time = (
                _body_timeline_parent_exposure_time(
                    row, source_timeline_mapping,
                    str(observed.get('sourceVideoSha256') or '').casefold())
                if isinstance(row, dict) else None
            )
            if (row is None or expected_rig_side != side
                    or row.get('sourceTrackStationary') is not True
                    or row.get('visible') is not True
                    or row.get('surface') != 'ground'
                    or row.get('contactState') not in {'full_sole', 'forefoot'}
                    or contact.get('contactState') != expected_state
                    or contact.get('surfaceKind') not in {None, row.get('surface')}
                    or contact.get('sourceTimeBasis') != 'absolute_source_video'
                    or contact.get('contactTimelineSourceClock') != 'video_frame_zero_seconds'
                    or not _same_source_time(contact.get('contactTimelineSourceTimeSec'), row.get('sourceTimeSec'))
                    or parent_exposure_time is None
                    or not _same_source_time(contact.get('sourceTimeSec'),
                                              parent_exposure_time)):
                continue
            if contact.get('contactTimelineSourceVideoSha256') != observed.get('sourceVideoSha256'):
                continue
            supported.add(expected_rig_side)
            continue
        patch = evidence.get('footPatchEvidence') or {}
        side_patch = ((patch.get('feet') or {}).get(side) or {})
        side_has_observations = isinstance(side_patch.get('states'), list) and bool(side_patch.get('states'))
        state = str(contact.get('contactState') or '').casefold()
        if side_has_observations:
            if state not in {'full_sole', 'toe_only', 'heel_only'}:
                continue
        elif state not in {'full_sole', 'toe_only', 'heel_only'}:
            # Without a patch track, only an explicitly observed physical
            # contact state can complement an independently stationary track.
            continue
        supported.add(side)
    unresolved = sorted(required - supported)
    # A present but invalid timeline is missing/unresolved evidence, never a
    # contradictory source. Explicit same-time disagreement is evaluated
    # separately by source_support_contact_conflicts below.
    conflict = [item for item in source_support_contact_conflicts(evidence, timeline_rows)
                if item.get('rigSide', item.get('side')) in required]
    # Disagreement between two observation channels is inconclusive evidence,
    # not proof that the source violates an exercise requirement. This gate
    # does not own the verified, time-scoped contract needed to make that call.
    if timeline_raw_present and not timeline_rows and required:
        unresolved = sorted(set(unresolved) | set(required))
    result = _support_readiness_result(
        status='ready' if not unresolved and not conflict else 'incomplete',
        required_sides=required,
        resolved_sides=(required - set(unresolved)) if not conflict else (),
        unresolved_sides=(unresolved if not conflict else required),
        reason='source_support_contact_evidence_incomplete' if unresolved or conflict else None)
    if conflict:
        result['evidenceDisagreements'] = conflict
    return result


def _same_source_time(left, right):
    try:
        left, right = float(left), float(right)
    except (TypeError, ValueError, OverflowError):
        return False
    return np.isfinite(left) and np.isfinite(right) and abs(left - right) <= 1e-6


def source_support_contact_conflicts(evidence, timeline_rows):
    """Return only explicit same-side, same-time visual/patch disagreements."""
    patch = evidence.get('footPatchEvidence') or {}
    times = patch.get('sourceTimesSec')
    if not isinstance(times, list) or not times:
        return []
    patch_digest = str(patch.get('sourceVideoSha256') or '').casefold()
    evidence_digest = str(evidence.get('sourceVideoSha256') or '').casefold()
    if not patch_digest or patch_digest != evidence_digest:
        return []
    observed_digest = str(
        ((evidence.get('bodySupportObservation') or {}).get('sourceVideoSha256') or '')
    ).casefold()
    if observed_digest and observed_digest != patch_digest:
        return []
    patch_state_to_visual_state = {
        'full_sole': 'full_sole', 'toe_only': 'forefoot',
        'heel_only': 'heel_only', 'airborne': 'airborne',
    }
    conflicts = []
    for row in timeline_rows:
        if not isinstance(row, dict) or row.get('side') not in {'left', 'right'}:
            continue
        state = row.get('contactState')
        if state not in {'full_sole', 'forefoot', 'heel_only', 'airborne'}:
            continue
        mapping = evidence.get('motionSpaceMapping') or {}
        rig_side = (('right' if row['side'] == 'left' else 'left')
                    if mapping.get('bilateralAssignment') == 'swapped' else row['side'])
        patch_side = ((patch.get('feet') or {}).get(rig_side) or {})
        patch_states = patch_side.get('states')
        if not isinstance(patch_states, list):
            continue
        for index, timestamp in enumerate(times):
            if (index >= len(patch_states)
                    or not _same_source_time(timestamp, row.get('sourceTimeSec', 0.))):
                continue
            patch_state = str(patch_states[index]).casefold()
            if (patch_state in patch_state_to_visual_state
                    and patch_state_to_visual_state[patch_state] != state):
                conflicts.append({'side': row['side'], 'rigSide': rig_side,
                                  'sourceTimeSec': row.get('sourceTimeSec'),
                                  'visualState': state, 'patchState': patch_state})
    return conflicts


def _support_readiness_result(*, status, required_sides, reason=None,
                              resolved_sides=None, unresolved_sides=None,
                              evaluated=True, conflicts=None):
    required = sorted(set(required_sides))
    resolved = sorted(set(resolved_sides or ()))
    unresolved = sorted(set(unresolved_sides if unresolved_sides is not None else set(required) - set(resolved)))
    reasons = [reason] if reason else []
    result = {'status': status, 'required': bool(required), 'available': status == 'ready',
              'evaluated': evaluated, 'passed': status == 'ready',
              'requiredSides': required, 'resolvedSides': resolved,
              'unresolvedSides': unresolved, 'rejectionReasons': reasons}
    if conflicts:
        result['conflicts'] = conflicts
    return result


def pre_reconstruction_source_support_readiness(source_evidence):
    """Apply the final fit gate's normal evidence materialization before reconstruction."""
    evidence = source_evidence if isinstance(source_evidence, dict) else {}
    return support_contact_readiness({'sourceFootSupportEvidence': evidence})


# Distal plants owned by contact pins / plant projection. Torso/back support still
# needs the heavy initialize_supported_motion solve.
PLANT_ONLY_SUPPORT_JOINTS = frozenset({
    'left_ankle', 'left_foot', 'right_ankle', 'right_foot',
})


def plant_only_body_support(evidence):
    """True when confirmed support is only planted feet/ankles, not a torso surface."""
    if not isinstance(evidence, dict):
        return False
    if not evidence.get('required') or evidence.get('status') != 'confirmed':
        return False
    stationary = evidence.get('stationaryJoints') or []
    return bool(stationary) and set(stationary).issubset(PLANT_ONLY_SUPPORT_JOINTS)


def evidence_is_complete(evidence, names):
    stationary = evidence.get('stationaryJoints') or []
    if not stationary or not set(stationary).issubset(names):
        return False
    for group in evidence.get('coplanarGroups', []) + evidence.get('nonPenetrationChains', []) + evidence.get('soleContacts', []):
        try:
            normal = np.asarray(group.get('normal', []), dtype=float)
        except (TypeError, ValueError):
            return False
        joints = group.get('joints', []) + group.get('endpoints', [])
        if (normal.shape != (3,) or not np.isfinite(normal).all() or np.linalg.norm(normal) < 1e-8
                or not joints or not set(joints).issubset(names)):
            return False
    if any(len(group.get('joints', [])) < (1 if 'planeOffsetMeters' in group else 2)
           or group.get('anchorJoint', group['joints'][0]) not in group['joints']
           for group in evidence.get('coplanarGroups', [])):
        return False
    for group in evidence.get('coplanarGroups', []):
        if 'planeOffsetMeters' in group:
            try:
                if not np.isfinite(float(group['planeOffsetMeters'])):
                    return False
            except (TypeError, ValueError):
                return False
    if any(len(chain.get('endpoints', [])) != 2 or not chain.get('joints')
           for chain in evidence.get('nonPenetrationChains', [])):
        return False
    if any(len(contact.get('joints', [])) != 3 for contact in evidence.get('soleContacts', [])):
        return False
    return True


def _missing_material_sole_pitch_sides(evidence):
    """Full-sole geometry needs an independently calibrated shoe pitch."""
    pitches = (evidence.get('materialFootRestPitchRadians')
               or evidence.get('footRestPitchRadians') or {})
    missing = []
    for contact in evidence.get('soleContacts', []):
        joints = contact.get('joints') or []
        if len(joints) != 3:
            continue
        side = str(joints[1]).split('_', 1)[0]
        try:
            pitch = float(pitches[side])
        except (KeyError, TypeError, ValueError, OverflowError):
            missing.append(side)
            continue
        if not np.isfinite(pitch):
            missing.append(side)
    return sorted(set(missing))


def chain_support_plane(chain, evidence):
    """Use observed anchors instead of letting a free endpoint lower clearance."""
    normal = np.asarray(chain['normal'], dtype=float)
    normal /= np.linalg.norm(normal)
    for group in evidence.get('coplanarGroups', []):
        group_normal = np.asarray(group['normal'], dtype=float)
        group_normal /= np.linalg.norm(group_normal)
        if (set(chain['endpoints']).intersection(group['joints'])
                and len(set(group['joints'])-set(chain['joints'])-set(chain['endpoints'])) > 0
                and abs(np.dot(normal, group_normal)) > 1.-1e-6):
            return group
    return None


def geometry_errors(points, names, evidence, *, frame_positions=None):
    """Plane equality and one-sided chain clearance in observed contact time."""
    errors = []
    active, _ = support_contact_masks(
        evidence, names, len(points), frame_positions=frame_positions)
    full_sole_active = full_sole_contact_masks(
        evidence, names, len(points), frame_positions=frame_positions)
    missing_pitch_sides = set(_missing_material_sole_pitch_sides(evidence))
    for contact in evidence.get('soleContacts', []):
        _, ankle, toe = (points[:, names.index(n)] for n in contact['joints'])
        side = str(contact['joints'][1]).split('_', 1)[0]
        sole_active = (full_sole_active[:, names.index(contact['joints'][1])] &
                       full_sole_active[:, names.index(contact['joints'][2])])
        if side in missing_pitch_sides:
            # Keep optimizer residuals finite while making absent geometry
            # authority impossible to satisfy during full-sole contact. A
            # toe-only episode does not establish heel material geometry.
            errors.append(np.where(sole_active, 2. * TOLERANCE_METERS, 0.)[:, None])
            continue
        normal = np.asarray(contact['normal'], dtype=float)
        normal /= np.linalg.norm(normal)
        pitches = evidence.get('materialFootRestPitchRadians') or evidence.get('footRestPitchRadians') or {}
        try:
            rest_pitch = float(pitches.get(side, 0.))
        except (AttributeError, TypeError, ValueError, OverflowError):
            rest_pitch = 0.
        error = _material_sole_plane_error(ankle, toe, normal, rest_pitch)
        errors.append(np.where(sole_active, error, 0.)[:, None])
    for group in evidence.get('coplanarGroups', []):
        indices = [names.index(n) for n in group['joints']]
        normal = np.asarray(group['normal'], dtype=float)
        normal /= np.linalg.norm(normal)
        heights = points[:, indices] @ normal
        group_active = np.logical_and.reduce([active[:, index] for index in indices])
        errors.append(np.where(group_active[:, None], heights[:, 1:] - heights[:, :1], 0.))
        if 'planeOffsetMeters' in group:
            errors.append(np.where(group_active[:, None],
                                   heights[:, :1]-float(group['planeOffsetMeters']), 0.))
    for chain in evidence.get('nonPenetrationChains', []):
        normal = np.asarray(chain['normal'], dtype=float)
        normal /= np.linalg.norm(normal)
        plane = chain_support_plane(chain, evidence)
        if plane is not None:
            # Endpoints are also subject to the observed support: otherwise a
            # lowered neck can redefine a sloping chord that legitimizes sag.
            anchor_index = names.index(plane['joints'][0])
            anchor = points[:, anchor_index]
            chain_active = active[:, anchor_index]
            for name in dict.fromkeys(chain['joints']+chain['endpoints']):
                error = np.minimum((points[:, names.index(name)]-anchor) @ normal, 0.)
                errors.append(np.where(chain_active, error, 0.)[:, None])
            continue
        start, end = (points[:, names.index(n)] for n in chain['endpoints'])
        chain_active = active[:, names.index(chain['endpoints'][0])] & active[:, names.index(chain['endpoints'][1])]
        direction = end - start
        denominator = np.maximum(np.sum(direction * direction, axis=-1), 1e-12)
        for name in chain['joints']:
            point = points[:, names.index(name)]
            ratio = np.clip(np.sum((point-start)*direction, axis=-1)/denominator, 0., 1.)
            chord = start + ratio[:, None]*direction
            error = np.minimum(np.sum((point-chord)*normal, axis=-1), 0.)
            errors.append(np.where(chain_active, error, 0.)[:, None])
    return np.concatenate(errors, axis=1) if errors else np.empty((len(points), 0))


def _support_source_frame_count(support, fallback, positions=None):
    count = support.get('_fitFrameCount')
    if isinstance(count, int) and count > 0:
        return count
    indexes = support.get('_fitFrameStateIndices')
    if isinstance(indexes, (list, tuple)) and indexes:
        maximum_index = max(indexes)
        # A fully unresolved source clock is commonly represented by all -1
        # rows. It conveys no native frame count; returning zero later makes
        # otherwise empty anchor tracks unindexable. Fall through to retained
        # source-state/position metadata while preserving the unresolved mask.
        if maximum_index >= 0:
            return maximum_index + 1
    contacts = list(support.get('contacts') or []) + list(support.get('supportContacts') or [])
    for contact in contacts:
        count = contact.get('_fitFrameCount')
        if isinstance(count, int) and count > 0:
            return count
    states = (support.get('footPatchEvidence') or {}).get('feet') or {}
    state_counts = [len(foot.get('states') or []) for foot in states.values()
                    if isinstance(foot, dict)]
    if state_counts and max(state_counts) > 0:
        return max(state_counts)
    if positions is not None and len(positions):
        inferred = int(np.ceil(np.max(positions))) + 1
        if inferred > 0:
            return inferred
    return fallback


def _timed_support_joint_names(support):
    """Return joints whose support interval is owned by explicit timing evidence."""
    support = support if isinstance(support, dict) else {}
    timed_names = set()
    raw_contacts = [(contact, None) for contact in
                    list(support.get('contacts') or [])
                    + list(support.get('supportContacts') or [])]
    raw_contacts += [(record, f'{side}_ankle') for side, record in
                     (support.get('feet') or {}).items() if isinstance(record, dict)]
    timing_keys = ('_fitFrameBounds', '_fitFrameRuns', 'startRatio', 'endRatio',
                   'startFrame', 'endFrame')
    for contact, default_name in raw_contacts:
        if not isinstance(contact, dict):
            continue
        if not any(key in contact and (key.startswith('_fit') or contact.get(key) is not None)
                   for key in timing_keys):
            continue
        name = str(contact.get('jointName') or default_name or '')
        if name:
            timed_names.add(name)
            if name.endswith(('_ankle', '_foot')):
                side = name.split('_', 1)[0]
                timed_names.update(f'{side}_{part}' for part in ('ankle', 'foot'))
    patch = support.get('footPatchEvidence') or {}
    patch_feet = patch.get('feet') or {}
    state_indices = support.get('_fitFrameStateIndices')
    for side, foot in patch_feet.items():
        if (patch.get('available') is True and isinstance(foot, dict)
                and isinstance(foot.get('states'), (list, tuple))):
            timed_names.update(f'{side}_{part}' for part in ('ankle', 'foot'))
    if state_indices is not None:
        for side in ('left', 'right'):
            timed_names.update(f'{side}_{part}' for part in ('ankle', 'foot'))
    return timed_names


def _mapped_contact_mask(contact, positions, source_count):
    from .contact_constraints import contact_frame_bounds
    start, end = contact_frame_bounds(contact, source_count)
    return (positions >= start) & (positions <= end) if start <= end else np.zeros(len(positions), dtype=bool)


def support_contact_masks(evidence, names, count, *, frame_positions=None):
    """Return exact active pins and anchor identities for this frame clock.

    Explicit patch or mapped contact timing is authoritative, including unknown
    frames. Legacy confirmed support without timed contact records retains its
    direct whole-clip scope. Single-pose initializer probes have no frame clock
    and evaluate the supplied representative supported pose directly.
    """
    from .sequence_stabilization import contact_mask
    from .contact_constraints import motion_support_contacts, stationary_contact_anchor_ids

    support = evidence if isinstance(evidence, dict) else {}
    if frame_positions is None:
        masks = contact_mask({}, names, count, support_evidence=support)
        positions = None
        source_count = count
    else:
        from .contact_constraints import is_stationary_contact
        positions = np.asarray(frame_positions, dtype=float)
        if positions.shape != (count,) or not np.isfinite(positions).all():
            raise ValueError('Support frame positions must match sampled points')
        source_count = _support_source_frame_count(support, count, positions)
        masks = np.zeros((count, len(names)), dtype=bool)
        for contact in motion_support_contacts(support):
            state = contact.get('contactState')
            if (state == 'heel_only' or contact.get('verticalOnly') is True
                    or (state == 'toe_only' and contact.get('verticalOnly') is not False)
                    or not is_stationary_contact(contact)):
                continue
            name = str(contact.get('jointName') or '')
            if name not in names:
                continue
            active = _mapped_contact_mask(contact, positions, source_count)
            masks[active, names.index(name)] = True
            if state == 'full_sole' and name.endswith(('_ankle', '_foot')):
                side = name.split('_', 1)[0]
                for part in ('ankle', 'foot'):
                    sibling = f'{side}_{part}'
                    if sibling in names:
                        masks[active, names.index(sibling)] = True
    if count == 1 and support.get('_fitFrameCount') not in (None, 1):
        # Support calibration evaluates one selected stance pose, not an
        # exported one-frame sequence; the caller owns choosing that pose.
        masks[:, :] = False
        for name in support.get('stationaryJoints') or []:
            if name in names:
                masks[:, names.index(name)] = True
    else:
        timed_names = _timed_support_joint_names(support)
        for name in support.get('stationaryJoints') or []:
            if name not in names:
                continue
            if name not in timed_names:
                # A direct stationary-joint assertion has whole-clip scope only
                # for that joint. Other joints keep their own timed evidence.
                masks[:, names.index(name)] = True
    anchor_ids = stationary_contact_anchor_ids(support, names, source_count)
    if positions is not None:
        nearest = np.clip(np.rint(positions).astype(int), 0, source_count - 1)
        anchor_ids = anchor_ids[nearest]
    return masks, anchor_ids


def full_sole_contact_masks(evidence, names, count, *, frame_positions=None):
    """Identify only timed full-sole frames for shoe-plane constraints."""
    from .contact_constraints import contact_frame_bounds, is_stationary_contact, motion_support_contacts

    support = evidence if isinstance(evidence, dict) else {}
    masks = np.zeros((count, len(names)), dtype=bool)
    contacts = motion_support_contacts(support)
    timed_names = _timed_support_joint_names(support)
    for contact in contacts:
        if (contact.get('contactState') != 'full_sole'
                or contact.get('verticalOnly') is True
                or not is_stationary_contact(contact)):
            continue
        try:
            positions = (np.arange(count, dtype=float) if frame_positions is None
                         else np.asarray(frame_positions, dtype=float))
            source_count = (count if frame_positions is None
                            else _support_source_frame_count(support, count, positions))
            active = _mapped_contact_mask(contact, positions, source_count)
        except (TypeError, ValueError):
            continue
        if not np.any(active):
            continue
        name = str(contact.get('jointName') or '')
        joints = [name]
        if name.endswith(('_ankle', '_foot')):
            side = name.split('_', 1)[0]
            joints = [f'{side}_ankle', f'{side}_foot']
        for joint in joints:
            if joint in names:
                masks[active, names.index(joint)] = True
    # Legacy sole geometry has whole-clip scope only for sides with no
    # authoritative contact clock. One side's clock must not erase the other's
    # direct evidence or make an unknown timed state look full-sole.
    for contact in support.get('soleContacts') or []:
        joints = contact.get('joints', [])[1:]
        if not joints:
            continue
        if any(joint in timed_names for joint in joints):
            continue
        for joint in joints:
            if joint in names:
                masks[:, names.index(joint)] = True
    return masks


def _material_sole_plane_error(ankle, toe, normal, rest_pitch):
    """Signed heel-to-forefoot height using the renderer's calibrated shoe pitch."""
    from .foot_geometry import SHOE_LENGTH_RATIO

    ankle = np.asarray(ankle, dtype=float)
    toe = np.asarray(toe, dtype=float)
    normal = np.asarray(normal, dtype=float)
    normal = normal / max(np.linalg.norm(normal), 1e-12)
    vector = toe - ankle
    length = np.linalg.norm(vector, axis=-1)
    forward = vector / np.maximum(length[..., None], 1e-12)
    up = normal - np.sum(normal * forward, axis=-1, keepdims=True) * forward
    up_length = np.linalg.norm(up, axis=-1)
    up = up / np.maximum(up_length[..., None], 1e-12)
    material_forward = (forward * np.cos(rest_pitch)
                        - up * np.sin(rest_pitch))
    # When the ankle-to-toe bone is nearly parallel to the plane normal,
    # sagittal pitch is undefined; retain a strong finite error rather than
    # manufacturing a flat sole orientation from an unstable axis.
    signed_height = -SHOE_LENGTH_RATIO * length * np.sum(material_forward * normal, axis=-1)
    return np.where(up_length > 1e-8, signed_height, SHOE_LENGTH_RATIO * length)


def validate_support_geometry(payload, points=None, names=None, *, frame_positions=None):
    from .body_support_observation import materialize_stationary_sole_support
    materialized = materialize_stationary_sole_support(payload)
    readiness = support_contact_readiness(payload, evidence=materialized)
    if not readiness['passed']:
        return {**readiness, 'policyVersion': POLICY_VERSION}
    evidence = {**(materialized.get('bodySupport') or {})}
    for key in ('contacts', 'supportContacts', 'feet', 'footPatchEvidence',
                '_fitFrameStateIndices', '_fitFrameCount'):
        if key in materialized:
            evidence[key] = materialized[key]
    pitches = payload.get('footRestPitchRadians')
    if isinstance(pitches, dict):
        evidence = {**evidence, 'materialFootRestPitchRadians': pitches}
    if not evidence.get('required'):
        return {'required': False, 'passed': True, 'policyVersion': POLICY_VERSION,
                'sourceContactReadiness': readiness}
    if evidence.get('status') != 'confirmed':
        return {'required': True, 'passed': False, 'policyVersion': POLICY_VERSION,
                'rejectionReasons': ['supported_body_evidence_unresolved']}
    names = names or payload.get('jointNames', [])
    if not evidence_is_complete(evidence, names) or (points is None and not payload.get('frames')):
        return {'required': True, 'passed': False, 'policyVersion': POLICY_VERSION,
                'rejectionReasons': ['supported_body_evidence_unresolved']}
    if points is None:
        try:
            points = np.array([[f['joints'][n] for n in names] for f in payload['frames']], dtype=float)
        except (KeyError, TypeError, ValueError):
            return {'required': True, 'passed': False, 'policyVersion': POLICY_VERSION,
                    'rejectionReasons': ['supported_body_geometry_unavailable']}
    if not np.isfinite(points).all():
        return {'required': True, 'passed': False, 'policyVersion': POLICY_VERSION,
                'rejectionReasons': ['supported_body_geometry_unavailable']}
    active, anchor_ids = support_contact_masks(
        evidence, names, len(points), frame_positions=frame_positions)
    full_sole_active = full_sole_contact_masks(
        evidence, names, len(points), frame_positions=frame_positions)
    active_sole_sides = {
        str(contact['joints'][1]).split('_', 1)[0]
        for contact in evidence.get('soleContacts', [])
        if len(contact.get('joints') or []) == 3
        and contact['joints'][1] in names and contact['joints'][2] in names
        and np.any(full_sole_active[:, names.index(contact['joints'][1])] &
                   full_sole_active[:, names.index(contact['joints'][2])])
    }
    missing_pitch_sides = sorted(
        active_sole_sides.intersection(_missing_material_sole_pitch_sides(evidence)))
    if missing_pitch_sides:
        return {'required': True, 'passed': False, 'policyVersion': POLICY_VERSION,
                'unresolvedSides': missing_pitch_sides,
                'rejectionReasons': ['supported_material_sole_pitch_unavailable']}
    stationary = [name for name in evidence.get('stationaryJoints', []) if name in names]
    unresolved = [name for name in stationary if not np.any(active[:, names.index(name)])]
    if unresolved:
        return {'required': True, 'passed': False, 'policyVersion': POLICY_VERSION,
                'rejectionReasons': ['support_contact_timing_unresolved'],
                'unresolvedJoints': unresolved}
    drift = 0.
    for name in stationary:
        joint = names.index(name)
        indexes = np.flatnonzero(active[:, joint])
        if not len(indexes):
            continue
        # Never compare across a release/unknown frame or between distinct
        # observed anchors. Each active episode owns one stationary position.
        run_start = 0
        groups = []
        for offset in range(1, len(indexes) + 1):
            split = offset == len(indexes)
            if not split:
                previous, current = indexes[offset - 1], indexes[offset]
                split = (current != previous + 1 or
                         (anchor_ids[previous, joint] is not None and
                          anchor_ids[current, joint] != anchor_ids[previous, joint]))
            if split:
                groups.append(indexes[run_start:offset])
                run_start = offset
        for episode in groups:
            drift = max(drift, float(np.linalg.norm(
                np.ptp(points[episode, joint], axis=0))))
    geometry = float(np.max(np.abs(geometry_errors(
        points, names, evidence, frame_positions=frame_positions)), initial=0.))
    reasons = []
    if drift > TOLERANCE_METERS:
        reasons.append('supported_body_moves')
    if geometry > TOLERANCE_METERS:
        reasons.append('support_surface_geometry_mismatch')
    active_counts = {name: int(active[:, names.index(name)].sum()) for name in stationary}
    return {'required': True, 'passed': not reasons, 'policyVersion': POLICY_VERSION,
            'maximumStationaryJointRangeMeters': drift,
            'maximumSurfaceErrorMeters': geometry,
            'toleranceMeters': TOLERANCE_METERS, 'rejectionReasons': reasons,
            'activeContactFrameCountByJoint': active_counts}


def geometry_dependencies(rig, evidence):
    """Sparse dependency rows in exactly the same order as geometry_errors."""
    from .controlled_motion import joint_dependencies
    rows = []
    for contact in evidence.get('soleContacts', []):
        knee, ankle, toe = contact['joints']
        rows.append(joint_dependencies(rig, [ankle, toe]))
    for group in evidence.get('coplanarGroups', []):
        rows.extend(joint_dependencies(rig, [group['joints'][0], name]) for name in group['joints'][1:])
        if 'planeOffsetMeters' in group:
            rows.append(joint_dependencies(rig, [group['joints'][0]]))
    for chain in evidence.get('nonPenetrationChains', []):
        plane = chain_support_plane(chain, evidence)
        if plane is not None:
            rows.extend(joint_dependencies(rig, [plane['joints'][0], name])
                        for name in dict.fromkeys(chain['joints']+chain['endpoints']))
        else:
            rows.extend(joint_dependencies(rig, chain['endpoints']+[name]) for name in chain['joints'])
    return np.asarray(rows).reshape(-1, rig.width)


def validate_supported_shoe_orientation(payload, *, points=None, cursors=None):
    """Check rendered shoe-up during full-sole contact at stored or dense times."""
    evidence = support_evidence(payload)
    contacts = evidence.get('soleContacts', [])
    if not contacts:
        return {'required': False, 'passed': True}
    if evidence.get('status') != 'confirmed' or not evidence_is_complete(evidence, payload.get('jointNames', [])):
        return {'required': True, 'passed': False, 'reason': 'sole_orientation_evidence_unresolved'}
    names = payload.get('jointNames', [])
    frames = payload.get('frames') or []
    dense_input = points is not None
    if not dense_input:
        points = np.asarray([[frame['joints'][name] for name in names]
                             for frame in frames], dtype=float)
        sample_positions = np.arange(len(frames), dtype=float)
    else:
        points = np.asarray(points, dtype=float)
        if cursors is None:
            raise ValueError('Dense shoe-orientation samples require cursors')
        sample_positions = np.asarray(cursors, dtype=float)
        if points.shape != (len(sample_positions), len(names), 3):
            raise ValueError('shoe-orientation points must match the cursor clock')
    full_sole_active = full_sole_contact_masks(
        evidence, names, len(points), frame_positions=sample_positions)
    timed_names = _timed_support_joint_names(evidence)
    from .contact_constraints import motion_support_contacts
    unresolved_timed_sides = set()
    known_states = {'full_sole', 'toe_only', 'heel_only', 'airborne'}
    for contact in motion_support_contacts(evidence):
        name = str(contact.get('jointName') or '')
        # Stationary ankle entries synthesized from confirmed bodySupport are
        # geometric anchors whose timing can be inherited from the matching
        # observed foot patch. A timed foot record itself still needs an
        # explicit state, even when it came through a legacy contact schema.
        synthesized_ankle_anchor = (
            name.endswith('_ankle')
            and contact.get('supportKind') != 'observed_foot_patch'
            and not contact.get('contactState')
        )
        if (synthesized_ankle_anchor or name not in timed_names
                or not name.endswith(('_ankle', '_foot'))):
            continue
        state = str(contact.get('contactState') or '').casefold()
        if state not in known_states:
            unresolved_timed_sides.add(name.split('_', 1)[0])
    relevant_sides = {
        str(contact['joints'][1]).split('_', 1)[0]
        for contact in contacts
        if contact['joints'][1] in names and contact['joints'][2] in names
        and np.any(full_sole_active[:, names.index(contact['joints'][1])] &
                   full_sole_active[:, names.index(contact['joints'][2])])
    }
    sole_sides = {str(contact['joints'][1]).split('_', 1)[0] for contact in contacts}
    unresolved_sides = sorted(unresolved_timed_sides.intersection(sole_sides))
    if unresolved_sides:
        return {'required': True, 'passed': False,
                'reason': 'sole_contact_timing_unresolved',
                'unresolvedSides': unresolved_sides}
    if not relevant_sides:
        # Timed toe-only, heel-only, airborne, or unknown intervals do not
        # authorize a whole-foot material orientation constraint.
        return {'required': False, 'passed': True, 'reason': 'no_active_full_sole_contact'}
    if relevant_sides.intersection(_missing_material_sole_pitch_sides(evidence)):
        return {'required': True, 'passed': False, 'reason': 'sole_orientation_unavailable'}
    maximum = 0.
    pitches = (evidence.get('materialFootRestPitchRadians')
               or payload.get('footRestPitchRadians') or {})
    try:
        if not payload.get('frames'):
            raise ValueError('Missing frames')
        from .foot_geometry import _sample_material_foot_geometry
        try:
            geometry = _sample_material_foot_geometry(payload, sample_positions, points)
        except KeyError:
            # Small retained fixtures may contain foot-side evidence without
            # the renderer's complete leg chain. Production payloads use the
            # renderer helper above; this fallback transports the stored side
            # onto the sampled ankle-to-toe axis for those partial fixtures.
                geometry = {}
                from .temporal_quality import transport_side
                first = np.floor(sample_positions).astype(int)
                last = np.minimum(first + 1, len(frames) - 1)
                alpha = sample_positions - first
                for side_name in relevant_sides:
                    candidates = [contact['joints'] for contact in contacts
                                  if str(contact['joints'][1]).split('_', 1)[0] == side_name]
                    if not candidates:
                        continue
                    _, ankle, toe = candidates[0]
                    key = f'{ankle}->{toe}'
                    axes = []
                    for row, (a, b, amount) in enumerate(zip(first, last, alpha)):
                        vector = points[row, names.index(toe)] - points[row, names.index(ankle)]
                        axis = vector / max(np.linalg.norm(vector), 1e-12)
                        endpoints = []
                        for frame_index in (a, b):
                            frame = frames[frame_index]
                            old = np.asarray(frame['joints'][toe]) - np.asarray(frame['joints'][ankle])
                            old /= max(np.linalg.norm(old), 1e-12)
                            endpoints.append(transport_side(
                                np.asarray(frame['boneSides'][key], dtype=float), old, axis))
                        lateral = endpoints[0] * (1. - amount) + endpoints[1] * amount
                        lateral -= axis * np.dot(lateral, axis)
                        axes.append(lateral / max(np.linalg.norm(lateral), 1e-12))
                geometry[side_name] = {'lateral': np.asarray(axes), 'orientation': None}
        for contact in contacts:
            _, ankle, toe = contact['joints']
            side_name = str(ankle).split('_', 1)[0]
            if side_name not in relevant_sides or side_name not in geometry:
                continue
            rest_pitch = float(pitches[side_name])
            normal = np.asarray(contact['normal'], dtype=float)
            normal /= np.linalg.norm(normal)
            ankle_index = names.index(ankle)
            toe_index = names.index(toe)
            material = geometry[side_name]
            for frame_index in range(len(points)):
                if not (full_sole_active[frame_index, ankle_index]
                        and full_sole_active[frame_index, toe_index]):
                    continue
                ankle_point = points[frame_index, ankle_index]
                toe_point = points[frame_index, toe_index]
                vector = toe_point - ankle_point
                length = np.linalg.norm(vector)
                if length < 1e-8:
                    raise ValueError('Degenerate foot')
                forward = vector / length
                side = np.asarray(material['lateral'][frame_index], dtype=float)
                side -= forward*np.dot(side, forward)
                side_length = np.linalg.norm(side)
                if side_length < 1e-8:
                    raise ValueError('Degenerate shoe side')
                side /= side_length
                from .foot_geometry import material_foot_points
                orientation = material.get('orientation')
                if orientation is not None:
                    material_forward = orientation['forward'][frame_index]
                    side = orientation['side'][frame_index]
                else:
                    heel, material_toe = material_foot_points(
                        ankle_point, toe_point, side, rest_pitch)
                    material_forward = material_toe - heel
                    material_forward /= np.linalg.norm(material_forward)
                up = np.cross(side, material_forward)
                up /= max(np.linalg.norm(up), 1e-12)
                error = np.linalg.norm(up-normal)*length
                if not np.isfinite(error):
                    raise ValueError('Nonfinite shoe orientation')
                maximum = max(maximum, float(error))
    except (KeyError, TypeError, ValueError):
        return {'required': True, 'passed': False, 'reason': 'sole_orientation_unavailable'}
    return {'required': True, 'passed': maximum <= TOLERANCE_METERS,
            'maximumOrientationErrorMeters': maximum}


# The support-corrected reference is an observed fit target, never rendered:
# payload-side anatomy gates keep their 1e-6 feasibility bound, but the
# reference's own structure rows are judged at this file's material tolerance.
# Measured conflict on a real deadlift reference: the source observation's
# planted feet cannot be held stationary while fully satisfying
# anatomy_torso_bend (1.45mm residual at fold-adjacent frames), and a pinned
# re-projection cannot satisfy both — the residual is an observation property,
# not a repairable defect.
SUPPORT_REFERENCE_MATERIAL_TOLERANCE_METERS = 0.005


def _reference_is_valid(payload, reference, names, frame_count):
    from .anatomical_repair import repair_residuals
    from .support_alignment import validate_payload_alignment
    return (reference.shape == (frame_count, len(names), 3)
            and np.isfinite(reference).all()
            and not np.any(repair_residuals(reference, names, reference=reference)[0]
                           > SUPPORT_REFERENCE_MATERIAL_TOLERANCE_METERS)
            and validate_support_geometry(payload, reference, names)['passed']
            and validate_payload_alignment(payload, reference)['passed'])


def validated_support_reference(payload):
    """One independently checked correction reference for all final validators."""
    from .anatomical_repair import repair_residuals
    from .support_alignment import validate_payload_alignment
    names = payload.get('jointNames', [])
    frames = payload.get('frames', [])
    if not names or not frames or not all(
            all(n in frame.get('supportCorrectedReferenceJoints', {}) for n in names) for frame in frames):
        return None, 'support_corrected_reference_unavailable'
    try:
        reference = np.asarray([[f['supportCorrectedReferenceJoints'][n] for n in names] for f in frames], dtype=float)
        valid = _reference_is_valid(payload, reference, names, len(frames))
    except (TypeError, ValueError, KeyError):
        valid = False
    if not valid:
        return None, 'support_corrected_reference_invalid'
    return reference, None


def _head_articulation_residual(points, reference, names):
    from .temporal_quality import body_local_head_direction
    source = body_local_head_direction(reference, names)
    current = body_local_head_direction(points, names)
    if source is None or current is None:
        return np.empty((len(points), 0))
    angle = np.arccos(np.clip(np.sum(source * current, axis=1), -1., 1.))
    return np.maximum(angle - np.deg2rad(14.), 0.)[:, None]


def _head_articulation_dependencies(rig, points):
    from .controlled_motion import joint_dependencies
    if not _head_articulation_residual(points, points, rig.names).shape[1]:
        return np.empty((0, rig.width))
    return joint_dependencies(rig, ('pelvis', 'left_hip', 'right_hip', 'neck', 'head'))[None, :]


def calibrate_support_pose(rig, points, evidence, alignment_reference=None, *, articulation_reference=None):
    """Find one feasible fixed-rig support pose, retaining bone lengths."""
    from scipy.optimize import least_squares
    from .physical_validation import anatomical_structure_residuals, collision_clearances, body_scale
    from .controlled_motion import ANATOMY_FIT_MARGIN, SUPPORT_HEAD_ARTICULATION_FIT_WEIGHT

    if evidence.get('status') != 'confirmed' or not evidence_is_complete(evidence, rig.names):
        return None, {'passed': False, 'reason': 'supported_body_evidence_unresolved'}
    missing_pitch_sides = _missing_material_sole_pitch_sides(evidence)
    if missing_pitch_sides:
        return None, {'passed': False, 'reason': 'supported_material_sole_pitch_unavailable',
                      'unresolvedSides': missing_pitch_sides}
    indices = [rig.names.index(n) for n in evidence.get('stationaryJoints', [])]
    target = np.median(points, axis=0)
    closest = int(np.argmin(np.sum((points[:, indices]-target[indices])**2, axis=(1, 2))))
    initial = rig.initial[closest].copy()
    head_reference = (points if articulation_reference is None else articulation_reference)[closest:closest+1]
    scale = body_scale(points, rig.names)
    from .support_alignment import (alignment_features, alignment_constraint_errors,
                                    alignment_dependencies)
    source_alignment = np.median(alignment_features(
        points if alignment_reference is None else alignment_reference, rig.names, evidence), axis=0, keepdims=True)

    def residual(values):
        candidate = rig.decode(values[None, :])
        # Preserve the observed plane's height; equality alone could move both
        # feet upward and satisfy the group while losing the original support.
        anchor_errors = []
        for group in evidence.get('coplanarGroups', []):
            index = rig.names.index(group.get('anchorJoint', group['joints'][0]))
            normal = np.asarray(group['normal'], dtype=float)
            normal /= np.linalg.norm(normal)
            height = float(group.get('planeOffsetMeters', np.dot(target[index], normal)))
            anchor_errors.append(np.dot(candidate[0, index], normal)-height)
        return np.r_[(candidate[0]-target).ravel(),
                     200.*alignment_constraint_errors(candidate, source_alignment, rig.names, evidence).ravel(),
                     1000.*geometry_errors(candidate, rig.names, evidence).ravel(),
                     1000.*np.asarray(anchor_errors),
                     1000.*anatomical_structure_residuals(
                         candidate, rig.names, pose_only=True, margin=ANATOMY_FIT_MARGIN)[0].ravel(),
                     SUPPORT_HEAD_ARTICULATION_FIT_WEIGHT*_head_articulation_residual(
                         candidate, head_reference, rig.names).ravel(),
                     1000.*np.minimum(collision_clearances(candidate, rig.names, scale)[0]-.003*scale, 0.).ravel(),
                     .001*(values-initial)]

    # This solve used to run dense finite differences: every Jacobian perturbed
    # all ~70 coordinates, so ~86 iterations cost ~6000 full residual
    # evaluations and dominated the whole fit. Assemble the residual's exact
    # sparsity from the same dependency builders the trajectory fit uses (in
    # the residual's exact row order) so grouped differences cost a dozen
    # evaluations per Jacobian instead of seventy, with identical values.
    from .physical_validation import collision_specs
    from .controlled_motion import joint_dependencies, anatomical_structure_dependencies
    initial_points = rig.decode(initial[None, :])
    rows: list[np.ndarray] = []
    for index, _name in enumerate(rig.names):
        rows.append(rig.dependencies[index*3:(index+1)*3])
    alignment_rows = np.atleast_2d(alignment_dependencies(rig, evidence))
    geometry_rows = np.atleast_2d(geometry_dependencies(rig, evidence))
    rows.extend(alignment_rows)
    rows.extend(geometry_rows)
    for group in evidence.get('coplanarGroups', []):
        anchor = group.get('anchorJoint', group['joints'][0])
        rows.append(np.asarray(joint_dependencies(rig, [anchor])))
    structure_rows = np.atleast_2d(anatomical_structure_dependencies(rig, initial_points, rig.names))
    rows.extend(structure_rows)
    rows.extend(_head_articulation_dependencies(rig, initial_points))
    for _label, first, second, _ratio, _adjacent in collision_specs(rig.names):
        rows.append(np.asarray(joint_dependencies(rig, [*first, *second])))
    rows.append(np.eye(rig.width))
    pattern = np.asarray(np.vstack([
        np.atleast_2d(row) if np.asarray(row).ndim > 0 else np.zeros((0, rig.width))
        for row in rows
    ]), dtype=bool)
    from scipy.sparse import csr_matrix
    # Measured on real calibrations: the surface error is ~0.01-0.05 mm by 40
    # evaluations against a 2.5 mm gate - the remaining ~85 evaluations only
    # polished invisible precision and made this stage the dominant fit cost.
    # The post-solve gate below still rejects anything short of the tolerance.
    solved = least_squares(residual, initial, jac_sparsity=csr_matrix(pattern),
                           max_nfev=40, x_scale='jac', ftol=1e-6, xtol=1e-6)
    pose = rig.decode(solved.x[None, :])[0]
    error = float(np.max(np.abs(geometry_errors(pose[None], rig.names, evidence)), initial=0.))
    return (pose if error < TOLERANCE_METERS*.5 else None), {
        'passed': error < TOLERANCE_METERS*.5, 'surfaceErrorMeters': error,
        'evaluations': solved.nfev, 'coordinates': solved.x.tolist(),
        'jacobianSparsityRows': int(pattern.shape[0]),
        'referenceCoordinates': initial.tolist()}


def preserve_free_limb_motion(rig, original, stationary_names, frozen_columns):
    """Rebase moving subtrees on calibrated anchors without inheriting twist.

    Free limbs retain observed world-space directions. Simply replacing torso
    rotations transports its calibration twist into the arms and changes grip.
    """
    from scipy.spatial.transform import Rotation
    from .controlled_motion import align_vectors

    anchored = {rig.names.index(n) for n in stationary_names}
    calibrated = rig.decode(rig.initial)
    desired = original.copy()
    for joint in rig.order:
        ancestor = joint
        while ancestor >= 0 and ancestor not in anchored:
            ancestor = rig.parents[ancestor]
        if ancestor >= 0:
            desired[:, joint] += calibrated[:, ancestor] - original[:, ancestor]
    rotations = {}
    identity = Rotation.identity(len(original))
    for joint in rig.order:
        parent = rig.parents[joint]
        parent_rotation = rotations.get(parent, identity)
        if joint not in rig.slots:
            rotations[joint] = parent_rotation
            continue
        slot = rig.slots[joint]
        local = Rotation.from_rotvec(rig.initial[:, slot:slot+3])
        if parent >= 0 and not frozen_columns[slot:slot+3].any():
            target = parent_rotation.inv().apply(desired[:, joint]-desired[:, parent])
            current = local.apply(np.tile(rig.offsets[joint], (len(original), 1)))
            local = Rotation.from_rotvec(align_vectors(current, target))*local
            rig.initial[:, slot:slot+3] = local.as_rotvec()
        rotations[joint] = parent_rotation*local


def moving_support_articulations(points, names, evidence, *, support_corrected_points=None,
                                constraint_endpoints=()):
    """Meaningful articulation to retain while relocating support contacts."""
    from .physical_validation import ARTICULATIONS, angles
    from .smpl_joint_names import SMPL_JOINT_NAMES, SMPL_JOINT_PARENTS
    constrained_chain = set()
    for name in [*evidence.get('stationaryJoints', []), *constraint_endpoints]:
        if name not in SMPL_JOINT_NAMES:
            continue
        index = SMPL_JOINT_NAMES.index(name)
        while index >= 0:
            constrained_chain.add(SMPL_JOINT_NAMES[index])
            index = SMPL_JOINT_PARENTS[index]
    corrected_ankles = {group['joints'][1] for group in evidence.get('soleContacts', [])}
    result = []
    for label, a, b, c, _ in ARTICULATIONS:
        if label in corrected_ankles or not {a, b, c}.issubset(names):
            continue
        indices = [names.index(n) for n in (a, b, c)]
        # A supported distal endpoint can require a different shoulder/hip
        # excursion. Its feasible reference already passed independent support,
        # anatomy and alignment checks. Free chains retain the original range.
        reference = (support_corrected_points if support_corrected_points is not None
                     and c in constrained_chain else points)
        track = angles(*(reference[:, j] for j in indices))
        if np.ptp(track) > np.deg2rad(20.):
            result.append((label, indices, track))
    return result


def initialize_supported_motion(rig, original, evidence, pose, calibration, deadline, fps=30., alignment_reference=None,
                                *, pinned=None, contact_targets=None, equipment=None, max_evaluations=40,
                                articulation_reference=None):
    """Project observed articulation onto contacts without locking ancestors."""
    from time import monotonic
    from scipy.sparse import eye, kron, csr_matrix, vstack
    from .controlled_motion import (joint_dependencies, solve_trajectory, anatomical_structure_dependencies,
                                    ANATOMY_FIT_MARGIN, SUPPORT_HEAD_ARTICULATION_FIT_WEIGHT)
    from .physical_validation import SOCKET_ALIGNMENT_MAX_LATERAL_RATIO
    from .physical_validation import anatomical_structure_residuals, collision_clearances, collision_specs, body_scale

    stationary = evidence['stationaryJoints']
    indices = [rig.names.index(n) for n in stationary]
    source_coordinates = rig.initial.copy()
    source_points = rig.decode(source_coordinates)
    head_reference = original if articulation_reference is None else articulation_reference
    count = len(original)
    contact_active = np.zeros(source_points.shape[:2], dtype=bool) if pinned is None else pinned.copy()
    contact_active[:, indices] = True
    targets = source_points.copy() if contact_targets is None else contact_targets.copy()
    if contact_targets is None:
        targets[:, indices] = pose[indices]
    contact_indices = np.flatnonzero(np.any(contact_active, axis=0))
    from .equipment_constraints import grip_residual
    equipment = equipment or {}
    corrected_feet = {group['joints'][2] for group in evidence.get('soleContacts', [])}
    direction_children = [j for j in rig.order[1:] if rig.names[j] not in corrected_feet]
    direction_parents = [rig.parents[j] for j in direction_children]
    source_directions = source_points[:, direction_children]-source_points[:, direction_parents]
    # Start from observed articulation. Transporting a static calibration's
    # ancestor rotations through moving limbs can enter a different IK branch.
    placement_shift = np.mean(pose[indices]-source_points[:, indices], axis=1)
    rig.initial[:, :3] += placement_shift
    desired = source_points.copy()
    # Translate motion with its nearest supported ancestor. Other joints keep
    # their observed shape under a shared placement correction; independently
    # recentering each joint on a median calibration pose changes articulation.
    for joint in rig.order:
        ancestor = joint
        while ancestor >= 0 and ancestor not in indices:
            ancestor = rig.parents[ancestor]
        if ancestor >= 0:
            desired[:, joint] += pose[ancestor]-source_points[:, ancestor]
        else:
            desired[:, joint] += placement_shift
    desired[:, indices] = pose[indices]
    desired[contact_active] = targets[contact_active]
    scale = body_scale(original, rig.names)
    from .support_alignment import alignment_features, alignment_constraint_errors, alignment_dependencies
    source_alignment = alignment_features(original if alignment_reference is None else alignment_reference, rig.names, evidence)
    best_coordinates = rig.initial.copy()
    best_cost = float('inf')

    def residual(values):
        nonlocal best_coordinates, best_cost
        from .fit_runtime import fit_should_yield_for_priority
        if fit_should_yield_for_priority() or monotonic() > deadline:
            raise TimeoutError
        coordinates = values.reshape(count, rig.width)
        candidate = rig.decode(coordinates)
        # Angles alone permit a different torso lean or limb direction with
        # identical flexion. Preserve the observed vectors; explicit support
        # and anatomical constraints still take priority over this soft target.
        direction_errors = candidate[:, direction_children]-candidate[:, direction_parents]-source_directions
        frame_errors = np.concatenate([
            (candidate-desired).reshape(count, -1),
            (20.*direction_errors).reshape(count, -1),
            (2000.*(candidate[:, contact_indices]-targets[:, contact_indices])
             *contact_active[:, contact_indices, None]).reshape(count, -1),
            2000.*grip_residual(candidate, rig.names, equipment),
            2000.*geometry_errors(candidate, rig.names, evidence),
            # Alignment was under-weighted vs plant/contact (10 vs 2000), so
            # support init planted feet by introducing ~12 mm spine lateral
            # offset and failed support_correction_introduced_torso_deformation.
            200.*alignment_constraint_errors(candidate, source_alignment, rig.names, evidence),
            1000.*anatomical_structure_residuals(
                candidate, rig.names, pose_only=True, margin=ANATOMY_FIT_MARGIN)[0],
            SUPPORT_HEAD_ARTICULATION_FIT_WEIGHT*_head_articulation_residual(
                candidate, head_reference, rig.names),
            1000.*np.minimum(collision_clearances(candidate, rig.names, scale)[0]-.003*scale, 0.),
            .0001*(coordinates-source_coordinates),
        ], axis=1).ravel()
        # Independent pose projections can choose different redundant spine
        # configurations in adjacent frames. Regularize the correction itself
        # before making it the reference for the final trajectory fit.
        correction_acceleration = np.diff(candidate-desired, n=2, axis=0)*(fps*.15)**2
        errors = np.r_[frame_errors, correction_acceleration.ravel()]
        cost = float(errors @ errors)
        if cost < best_cost:
            best_coordinates, best_cost = coordinates.copy(), cost
        return errors

    contact_rows = [j*3+k for j in contact_indices for k in range(3)]
    grip_rows = (np.asarray([joint_dependencies(rig, equipment['endpointPair'])])
                 if equipment.get('handRelationship') == 'rigid_pair' and equipment.get('available')
                 else np.empty((0, rig.width)))
    collision_rows = [joint_dependencies(rig, [*a, *b]) for _, a, b, _, _ in collision_specs(rig.names)]
    direction_rows = np.repeat(np.asarray([joint_dependencies(rig, [rig.names[j], rig.names[parent]])
                                         for j, parent in zip(direction_children, direction_parents)]), 3, axis=0)
    frame_pattern = np.vstack([rig.dependencies, direction_rows, rig.dependencies[contact_rows], grip_rows,
        geometry_dependencies(rig, evidence), alignment_dependencies(rig, evidence), anatomical_structure_dependencies(rig, original, rig.names),
        _head_articulation_dependencies(rig, original), collision_rows, np.eye(rig.width)])
    pattern = kron(eye(count), csr_matrix(frame_pattern), format='csr')
    d2 = csr_matrix(abs(np.diff(np.eye(count), n=2, axis=0)))
    pattern = vstack([pattern, kron(d2, csr_matrix(rig.dependencies))], format='csr')
    if pattern.shape != (residual(rig.initial.ravel()).size, rig.initial.size):
        raise ValueError('Support projection residual and dependency shapes differ')
    try:
        solved = solve_trajectory(residual, rig.initial.ravel(), pattern, max(1, int(max_evaluations)))
    except TimeoutError:
        # Preserve evaluated progress for the caller's independent support gates.
        rig.initial[:] = best_coordinates
        raise
    calibration['projectionEvaluations'] = solved.nfev
    calibration['projectionEvaluationBudget'] = int(max_evaluations)
    rig.initial[:] = solved.x.reshape(count, rig.width)
    rig.project_neck_attachment(maximum_lateral_ratio=SOCKET_ALIGNMENT_MAX_LATERAL_RATIO-ANATOMY_FIT_MARGIN)
    return rig.decode(rig.initial)
