"""Shared, explicitly observed support constraints for fitting and acceptance.

Support planes are geometry evidence, not exercise-name templates. Unknown
contacts must not be promoted to confirmed contacts by the motion solver.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

POLICY_VERSION = 5
TOLERANCE_METERS = .005
# Heel, midfoot and forefoot bottom-edge vertices from the production
# three-ring shoe mesh returned by foot_geometry.shoe_vertices.
_NATIVE_SHOE_SOLE_RING_VERTICES = (5, 6, 13, 14, 21, 22)


def _surface_receipt_sha256(value):
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
    ).encode('utf-8')).hexdigest()


def _required_body_surface_direct_contact_ids(source_evidence):
    if not isinstance(source_evidence, dict):
        return set()
    bundle = source_evidence.get('bodySurfaceContactEvidence') or {}
    if not isinstance(bundle, dict):
        return set()
    required = set()
    for review in bundle.get('reviews') or []:
        if not isinstance(review, dict):
            continue
        requirement = review.get('requirement') or {}
        record = review.get('record') or {}
        source = record.get('sourceEvidence') if isinstance(record, dict) else None
        rows = source.get('observations') if isinstance(source, dict) else None
        if not isinstance(requirement, dict):
            continue
        if (requirement.get('disposition') == 'required'
                and isinstance(record, dict)
                and any(row.get('contactState') == 'direct_contact' and row.get('visible') is True
                        for row in (rows or [])
                        if isinstance(row, dict))):
            contact_id = str(review.get('contactId') or record.get('contactId') or '')
            if contact_id:
                required.add(contact_id)
    return required


def _is_deferred_body_surface_geometry_error(error):
    return ('required_contact_binding_missing' in error
            or 'geometry_binding_missing' in error)


def _body_surface_source_review_errors(payload, source_evidence, source_pose, source_video_path):
    """Verify required visual contacts before 3D calibration is available."""
    required_ids = _required_body_surface_direct_contact_ids(source_evidence)
    if not required_ids:
        return []
    bundle = source_evidence.get('bodySurfaceContactEvidence') or {}
    if not isinstance(bundle, dict) or bundle.get('status') != 'observed':
        return ['body_surface_contact_source_review_unresolved']
    reviews = {row.get('contactId'): row for row in bundle.get('reviews') or []
               if isinstance(row, dict) and row.get('contactId')}
    if source_pose is None or source_video_path is None:
        return ['body_surface_contact_source_receipt_context_unavailable']
    from .body_surface_evidence import verify_body_surface_contact_evidence
    errors = []
    for contact_id in sorted(required_ids):
        review = reviews.get(contact_id)
        record = review.get('record') if isinstance(review, dict) else None
        if not isinstance(record, dict) or review.get('status') != 'observed':
            errors.append(f'body_surface_contact_review_missing:{contact_id}')
            continue
        try:
            verified = verify_body_surface_contact_evidence(
                record, source_video_path, source_pose,
                review_receipt_path=review.get('receiptPath'),
                review_receipt_sha256=review.get('receiptSha256'))
            coverage = verified.get('coverage') or {}
            if (coverage.get('allCanonicalPoseFramesObserved') is not True
                    or len(verified.get('samples') or [])
                    != coverage.get('canonicalPoseFrameCount')):
                raise ValueError('required source contact review coverage is incomplete')
        except (OSError, TypeError, ValueError) as exc:
            errors.append(f'body_surface_contact_source_receipt_invalid:{contact_id}:{exc}')
    return errors


def _body_surface_contact_records(payload, source_evidence):
    """Bind inferred surface geometry to the exact observed source record."""
    if not isinstance(source_evidence, dict):
        return [], ['body_surface_contact_source_evidence_malformed']
    support = source_evidence.get('bodySupport') or {}
    if not isinstance(support, dict):
        return [], ['body_surface_contact_support_container_malformed']
    raw_records = support.get('bodySurfaceContacts')
    errors = []
    required_review_ids = _required_body_surface_direct_contact_ids(source_evidence)
    if raw_records is None:
        raw_records = []
    if not isinstance(raw_records, list):
        return [], ['body_surface_contact_records_malformed']
    if not raw_records and not required_review_ids:
        return [], []
    reference = payload.get('sourcePoseCameraReference') or {}
    if not isinstance(reference, dict):
        return [], ['body_surface_contact_camera_mapping_unavailable']
    timeline = reference.get('sourceTimelineMapping') or {}
    source_pose = reference.get('sourcePose') or {}
    camera = reference.get('camera') or {}
    if not all(isinstance(value, dict) for value in (timeline, source_pose, camera)):
        return [], ['body_surface_contact_camera_mapping_unavailable']
    assignment = camera.get('bilateralAssignment')
    if assignment not in {'identity', 'swapped'}:
        return [], ['body_surface_contact_camera_mapping_unavailable']
    bundle = source_evidence.get('bodySurfaceContactEvidence') or {}
    if not isinstance(bundle, dict):
        return [], ['body_surface_contact_source_review_malformed']
    digest = str(timeline.get('selectedSegmentSha256') or '').casefold()
    pose_digest = str(timeline.get('sourcePosePayloadSha256') or '').casefold()
    clock_digest = str(timeline.get('selectedFrameClockReceiptSha256') or '').casefold()
    if (not digest or digest != str(source_pose.get('sourceVideoSha256') or '').casefold()
            or str(bundle.get('sourceVideoSha256') or '').casefold() != digest):
        return [], ['body_surface_contact_source_video_mapping_mismatch']
    if bundle.get('status') != 'observed':
        return [], ['body_surface_contact_source_review_unresolved']

    from .body_surface_contacts import normalize_body_surface_contact

    review_rows = bundle.get('reviews') or []
    if not isinstance(review_rows, list):
        return [], ['body_surface_contact_source_review_malformed']
    reviews = {item.get('contactId'): item for item in review_rows
               if isinstance(item, dict) and item.get('contactId')}
    raw_ids = {row.get('contactId') for row in raw_records if isinstance(row, dict)}
    missing_required_ids = required_review_ids - raw_ids
    validation_records = [(row, True) for row in raw_records]
    validation_records.extend((reviews[contact_id].get('record'), False)
                              for contact_id in missing_required_ids
                              if contact_id in reviews)
    normalized = []
    normalized_ids = set()
    for index, (raw, has_geometry_binding_record) in enumerate(validation_records):
        try:
            record = normalize_body_surface_contact(raw)
        except (TypeError, ValueError) as exc:
            errors.append(f'body_surface_contact_record_{index}_invalid:{exc}')
            continue
        source = record['sourceEvidence']
        if (source['sourceVideoSha256'].casefold() != digest
                or source['sourcePosePayloadSha256'].casefold() != pose_digest
                or source['sourceFrameClockReceiptSha256'].casefold() != clock_digest):
            errors.append(f'body_surface_contact_record_{index}_source_mapping_mismatch')
            continue
        review = reviews.get(record['contactId'])
        reviewed = review.get('record') if isinstance(review, dict) else None
        if (not isinstance(reviewed, dict) or review.get('status') != 'observed'
                or any(reviewed.get(key) != record.get(key) for key in
                       ('contactId', 'bodyRegion', 'contactMode', 'sourceEvidence'))):
            errors.append(f'body_surface_contact_record_{index}_does_not_match_review')
            continue
        coverage = review.get('coverage') or {}
        source_rows = source['observations']
        if (coverage.get('allCanonicalPoseFramesObserved') is not True
                or coverage.get('canonicalPoseFrameCount') != len(source_rows)
                or sorted(row['sourcePoseFrameIndex'] for row in source_rows)
                != list(range(len(source_rows)))):
            errors.append(f'body_surface_contact_record_{index}_source_coverage_incomplete')
            continue
        receipt_path = review.get('receiptPath')
        receipt_sha = review.get('receiptSha256')
        try:
            receipt_bytes = Path(receipt_path).read_bytes()
            if hashlib.sha256(receipt_bytes).hexdigest() != receipt_sha:
                raise ValueError('receipt hash mismatch')
            receipt = json.loads(receipt_bytes)
            request = receipt['requestBinding']
            if not isinstance(request, dict):
                raise ValueError('receipt request binding malformed')
            if (receipt.get('schemaVersion') != 1
                    or receipt.get('reviewIdentity') != request.get('reviewIdentity')
                    or receipt.get('promptPolicyVersion') != request.get('policyVersion')
                    or receipt.get('requestSha256') != _surface_receipt_sha256(request)
                    or request.get('contactId') != record['contactId']
                    or request.get('bodyRegion') != record['bodyRegion']
                    or request.get('contactMode') != record['contactMode']
                    or str(request.get('sourceVideoSha256') or '').casefold() != digest
                    or str(request.get('sourcePosePayloadSha256') or '').casefold() != pose_digest
                    or str(request.get('sourceFrameClockReceiptSha256') or '').casefold() != clock_digest):
                raise ValueError('receipt request identity mismatch')
            bound_rows = request.get('samples')
            raw_responses = receipt.get('rawResponses')
            if (not isinstance(bound_rows, list) or len(bound_rows) != len(source_rows)
                    or not isinstance(raw_responses, dict)
                    or set(raw_responses) != {row['sampleId'] for row in source_rows}):
                raise ValueError('receipt sample set mismatch')
            for row, bound in zip(source_rows, bound_rows):
                if not isinstance(bound, dict):
                    raise ValueError('receipt sample mapping malformed')
                if any(bound.get(key) != row.get(key) for key in (
                        'sampleId', 'sourceTimeSec', 'sourcePoseFrameIndex',
                        'sourceFrameIndex', 'sourceFps', 'surfaceId')):
                    raise ValueError('receipt sample mapping mismatch')
                answer = json.loads(raw_responses[row['sampleId']])
                choice = answer.get('choice') if isinstance(answer, dict) else None
                expected = {'direct_contact': ('direct_contact', True),
                            'no_contact': ('no_contact', True),
                            'unresolved': ('unknown', False)}.get(choice)
                if expected != (row['contactState'], row['visible']):
                    raise ValueError('receipt choice differs from reviewed sample')
        except (OSError, TypeError, KeyError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f'body_surface_contact_record_{index}_receipt_invalid:{exc}')
            continue

        # Contact geometry is expressed in source anatomical labels. Match the
        # reviewed identity first, then map side-qualified primitive IDs into
        # the fitted rig's bilateral assignment.
        if assignment == 'swapped':
            side = record['bodyRegion']['side']
            if side in {'left', 'right'}:
                record['bodyRegion']['side'] = 'right' if side == 'left' else 'left'
            if record.get('patchBinding') is not None:
                primitive = record['patchBinding']['primitiveId']
                record['patchBinding']['primitiveId'] = primitive.replace(
                    'left_', '__side__').replace('right_', 'left_').replace('__side__', 'right_')
        if not has_geometry_binding_record:
            continue
        if record.get('patchBinding') is None or record.get('surfaceEstimate') is None:
            errors.append(f'body_surface_contact_record_{index}_geometry_binding_missing')
        normalized.append(record)
        normalized_ids.add(record['contactId'])
    if not required_review_ids.issubset(normalized_ids):
        errors.append('body_surface_required_contact_binding_missing')
    return normalized, errors


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


def support_evidence(payload, *, materialized=None):
    from .body_support_observation import materialize_stationary_sole_support
    # The fitter uses a temporally materialized motion-space view. Rebuild that
    # same view for downstream geometry checks so cached full-clip foot anchors
    # cannot outlive contradictory or incomplete contact observations.
    if materialized is None:
        materialized = materialize_stationary_sole_support(payload)
    support = dict(materialized.get('bodySupport', {}))
    if 'nativeFootGeometry' in payload:
        from .native_foot_geometry import validated_native_foot_geometry
        native_foot_geometry = validated_native_foot_geometry(
            payload.get('nativeFootGeometry'))
        if native_foot_geometry is None:
            support.setdefault('_bodySurfaceContactErrors', []).append(
                'native_foot_geometry_invalid')
        else:
            support['nativeFootGeometry'] = native_foot_geometry
    body_surface_contacts, body_surface_errors = _body_surface_contact_records(
        payload, payload.get('sourceFootSupportEvidence') or {})
    if body_surface_contacts:
        support['bodySurfaceContacts'] = body_surface_contacts
    if body_surface_errors:
        errors = support.setdefault('_bodySurfaceContactErrors', [])
        errors.extend(error for error in body_surface_errors if error not in errors)
    required_surface_ids = _required_body_surface_direct_contact_ids(
        payload.get('sourceFootSupportEvidence') or {})
    if required_surface_ids:
        support['_bodySurfaceGenericRequired'] = True
        support['required'] = True
        source_errors = [error for error in body_surface_errors
                         if not _is_deferred_body_surface_geometry_error(error)]
        support['_bodySurfaceSourceBound'] = not source_errors
        support['_bodySurfaceGeometryPending'] = bool(body_surface_errors)
        support['status'] = 'confirmed' if not source_errors else 'unknown'
        if not any(support.get(key) for key in (
                'stationaryJoints', 'soleContacts', 'coplanarGroups', 'nonPenetrationChains')):
            support['_bodySurfaceOnlyRequired'] = True
    from .material_region_support import calibrated_region_contacts
    regions = calibrated_region_contacts(payload)
    if regions:
        support.update(required=True, status='confirmed', materialRegionContacts=regions)
        support.setdefault('stationaryJoints', [])
    # Geometry residuals and their downstream validators need the same mapped
    # per-frame contact authority as the fitter. A bodySupport summary alone
    # loses releases and unknown frames at the edges of a source interval.
    for key in ('contacts', 'supportContacts', 'feet', 'footPatchEvidence',
                '_fitFrameStateIndices', '_fitFrameCount'):
        if key in materialized:
            support[key] = materialized[key]
    fixed_rig = payload.get('fixedRig') or {}
    contact_tracks = fixed_rig.get('contactFootTracks') if isinstance(fixed_rig, dict) else None
    if isinstance(contact_tracks, dict) and contact_tracks.get('version') == 2:
        try:
            from .contact_interpolation import _validated_native_side_track
            frame_count = len(fixed_rig.get('coordinates') or [])
            if frame_count < 2:
                raise ValueError('native material contact rig has too few frames')
            for side in ('left', 'right'):
                if side in contact_tracks:
                    _validated_native_side_track(contact_tracks[side], frame_count, side)
            support['_nativeFootMaterialTracks'] = contact_tracks
            if support.get('nativeFootGeometry') is None:
                raise ValueError('native material contact lacks validated nativeFootGeometry')
            from .foot_geometry import foot_scale_from_pose
            first_points = np.asarray([payload['frames'][0]['joints'][name]
                                       for name in payload['jointNames']], dtype=float)
            support['_nativeFootScale'] = float(foot_scale_from_pose(first_points, payload['jointNames']))
            from .contact_interpolation import validate_native_contact_track_geometry
            side_axes = {side: np.asarray(contact_tracks[side]['sideAxes'], dtype=float)
                         for side in ('left', 'right') if side in contact_tracks}
            validate_native_contact_track_geometry(
                np.asarray([[frame['joints'][name] for name in payload['jointNames']]
                            for frame in payload['frames']], dtype=float),
                payload['jointNames'], side_axes, contact_tracks,
                support['nativeFootGeometry'], support['_nativeFootScale'])
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            support.pop('_nativeFootMaterialTracks', None)
            support.pop('_nativeFootScale', None)
            support['_nativeFootMaterialErrors'] = [str(exc)]
    pitches = payload.get('footRestPitchRadians')
    if isinstance(pitches, dict):
        support = dict(support)
        support['materialFootRestPitchRadians'] = pitches
    from .body_support_observation import validated_body_support_answer
    observed = materialized.get('bodySupportObservation') or {}
    observation = (validated_body_support_answer(observed) or {}) if (
        support.get('sourceVideoSha256') and
        support.get('sourceVideoSha256') == observed.get('sourceVideoSha256')) else {}
    floor = payload.get('renderFloorY')
    joints = [name for name in support.get('stationaryJoints', [])
              if name in {'left_knee', 'right_knee'}
              and observation.get(name.split('_')[0]+'Knee') == 'stationary_support'
              and observation.get(name.split('_')[0]+'KneeContactSurface') == 'floor']
    if joints and not (isinstance(floor, (int, float)) and np.isfinite(floor)):
        support['_materialFloorUnresolved'] = True
    if isinstance(floor, (int, float)) and np.isfinite(floor):
        if payload.get('frames'):
            # Preserve native shoe orientation/contact authority, including unknowns.
            support['_materialShoePayload'] = payload
        if joints and payload.get('frames'):
            from .render_geometry import material_leg_sides
            frames = payload['frames']
            support['_floorMaterialContacts'] = joints
            support['_renderFloorY'] = float(floor)
            support['_materialLoopable'] = bool((payload.get('loop') or {}).get('enabled'))
            support['_materialLegSides'] = material_leg_sides(frames, loopable=bool((payload.get('loop') or {}).get('enabled')))
            support['_materialFloorUnresolved'] = any(
                joint.split('_')[0]+'_knee->'+joint.split('_')[0]+'_ankle' not in row
                for joint in joints for row in support['_materialLegSides'])
            from .render_geometry import material_body_axes
            material_points = np.asarray([[frame['joints'][name] for name in payload['jointNames']] for frame in frames])
            support['_materialBodyAxes'] = material_body_axes(material_points, payload['jointNames'])
            support['_materialReferencePoints'] = material_points
            support['_materialSegmentLengths'] = {
                side: [float(np.linalg.norm(np.asarray(frames[0]['joints'][side+'_'+b])-
                                            frames[0]['joints'][side+'_'+a]))
                       for a,b in [('hip','knee'),('knee','ankle')]]
                for side in ('left','right')}
    return support


def support_contact_readiness(payload, *, evidence=None, source_pose=None, source_video_path=None,
                              require_geometry=True, exercise_motion_contract=None):
    """Classify support evidence without confusing missing evidence with conflict.

    Point contacts must match the fitter's exact-time materialized contacts.
    Raised-foot region observations instead require coverage of every verified
    canonical pose frame and never create joint anchors. Coarse summaries alone
    are not contact proof.
    """
    from . import body_support_observation
    materialize_stationary_sole_support = body_support_observation.materialize_stationary_sole_support
    validated_body_support_answer = body_support_observation.validated_body_support_answer
    from .contact_constraints import (
        is_stationary_contact, motion_support_contacts, source_support_mapping_unresolved,
        validated_support_contact_timeline_row,
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
    if exercise_motion_contract is None:
        exercise_motion_contract = payload.get('exerciseMotionContract')
    explicit_support = _validated_structured_definition_support(exercise_motion_contract)
    required = {side for side in ('left', 'right')
                if answer is not None
                and answer.get(f'{side}Foot') in {'stationary_full_sole', 'stationary_forefoot'}}
    required_any_foot = []
    stationary_required_sides = set()
    if explicit_support is not None:
        # Discovery/coarse labels describe candidate observations, not hard
        # whole-clip obligations. Keep strict behavior for explicit foot intent.
        required = set()
        for requirement in explicit_support['required']:
            if (requirement.get('region') != 'foot'
                    or requirement.get('contactMode', 'stationary') != 'stationary'):
                # Moving/rolling foot requirements are evaluated by the
                # existing typed contact-requirement validator, not as plants.
                continue
            side = requirement.get('side')
            if side in {'left', 'right'}:
                required.add(side)
                stationary_required_sides.add(side)
            elif side == 'both':
                required.update(('left', 'right'))
                stationary_required_sides.update(('left', 'right'))
            elif side == 'either':
                required_any_foot.append(requirement)
                stationary_required_sides.update(('left', 'right'))
        stance = explicit_support['bilateralExecution'].get('stance')
        if stance == 'stationary_bilateral':
            required.update(('left', 'right'))
            stationary_required_sides.update(('left', 'right'))
    source_surface_evidence = payload.get('sourceFootSupportEvidence') or {}
    if require_geometry:
        surface_records, surface_errors = _body_surface_contact_records(
            payload, source_surface_evidence)
        surface_blockers = surface_errors
    else:
        surface_records = []
        surface_blockers = _body_surface_source_review_errors(
            payload, source_surface_evidence, source_pose, source_video_path)
    if surface_blockers:
        return _support_readiness_result(
            status='incomplete', required_sides=required,
            reason=('body_surface_contact_geometry_unavailable' if require_geometry
                    else 'body_surface_contact_source_evidence_unavailable'),
            evaluated=False)
    timeline_raw_present = isinstance(observed, dict) and 'contactTimeline' in observed
    timeline_rows = body_support_observation.validated_body_support_contact_timeline(observed)
    timeline_rows = timeline_rows if isinstance(timeline_rows, list) else []
    supported = set()
    regional_foot_sides = set()
    if source_pose is not None:
        from .body_support_observation import _has_timed_regional_direct_contact
        pose = source_pose.get('pose') if isinstance(source_pose.get('pose'), dict) else source_pose
        coverage_sides = set(required)
        if required_any_foot:
            coverage_sides.update(('left', 'right'))
        for side in coverage_sides:
            surface = answer.get(f'{side}FootSurface')
            if surface != 'raised_surface':
                continue
            # Regional rows may clear this source gate only when rebound to the
            # canonical pose receipt for this exact selected video.
            from .body_support_observation import _verified_source_pose_track_proof
            digest = observed.get('sourceVideoSha256')
            proof, verified_pose = (_verified_source_pose_track_proof(
                source_video_path, side, digest) if source_video_path and digest else (None, None))
            if (not proof or not isinstance(verified_pose, dict)
                    or verified_pose.get('frames') != pose.get('frames')):
                continue
            if not _has_timed_regional_direct_contact(observed, 'foot', surface, source_pose, side=side):
                continue
            side_rows = [row for row in timeline_rows if row.get('landmark') == 'region'
                         and row.get('contactRegion') == 'foot' and row.get('side') == side
                         and row.get('contactState') == 'direct_contact'
                         and row.get('surface') == surface and row.get('visible') is True]
            expected_times = [float(frame['sourceTimeSec']) for frame in pose.get('frames') or []
                              if isinstance(frame, dict)
                              and isinstance(frame.get('sourceTimeSec'), (int, float))]
            observed_times = {float(row['sourceTimeSec']) for row in side_rows}
            if (expected_times and len(expected_times) == len(pose.get('frames') or [])
                    and len(observed_times) == len(expected_times)
                    and all(any(abs(value - target) <= 1e-6 for value in observed_times)
                            for target in expected_times)):
                regional_foot_sides.add(side)
                supported.add(side)
    support = evidence.get('bodySupport') or {}
    full_cycle_sides = set()
    verified_contacts = []
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
                full_cycle_sides.add(side)
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
        if contact.get('contactTimelineSampleId') is not None:
            row = validated_support_contact_timeline_row(contact, evidence)
            if row is None or row.get('reviewOnly') is True:
                continue
            supported.add(side)
            verified_contacts.append(contact)
            continue
        patch = evidence.get('footPatchEvidence') or {}
        side_patch = ((patch.get('feet') or {}).get(side) or {})
        side_has_observations = isinstance(side_patch.get('states'), list) and bool(side_patch.get('states'))
        state = str(contact.get('contactState') or '').casefold()
        if (name.endswith('_ankle')
                and contact.get('supportKind') == 'observed_stationary_ankle_restraint'
                and str(contact.get('sourceVideoSha256') or '').casefold() == observed_digest
                and answer.get(f'{side}Ankle') == 'stationary_support'
                and contact.get('surfaceKind') == answer.get(f'{side}AnkleContactSurface')):
            supported.add(side)
            verified_contacts.append(contact)
            continue
        if side_has_observations:
            if state not in {'full_sole', 'toe_only', 'heel_only'}:
                continue
        elif state not in {'full_sole', 'toe_only', 'heel_only'}:
            # Without a patch track, only an explicitly observed physical
            # contact state can complement an independently stationary track.
            continue
        supported.add(side)
        verified_contacts.append(contact)
    coverage = {}
    count = len(payload.get('frames') or []) or max(
        (len(foot.get('states') or [])
         for foot in ((evidence.get('footPatchEvidence') or {}).get('feet') or {}).values()),
        default=0)
    if count:
        from .sequence_stabilization import contact_mask
        from .contact_constraints import stationary_contact_anchor_ids
        names = [f'{side}_{part}' for side in ('left', 'right') for part in ('ankle', 'foot')]
        contact_evidence = {'contacts': verified_contacts}
        pinned = contact_mask(payload, names, count, support_evidence=contact_evidence)
        anchor_ids = stationary_contact_anchor_ids(contact_evidence, names, count)
        for side in required:
            if side in regional_foot_sides:
                coverage[side] = {
                    'coveredFrames': len(pose['frames']), 'requiredFrames': len(pose['frames']),
                    'coverageDomain': 'canonical_source_pose_frames',
                    'evidenceKind': 'exact_source_raised_foot_region_contacts',
                    'timedEvidence': [
                        {'sourceTimeSec': row['sourceTimeSec'],
                         'sourcePoseFrameIndex': row['sourcePoseFrameIndex'],
                         'side': side, 'surface': row['surface'],
                         'contactState': row['contactState']}
                        for row in timeline_rows if row.get('landmark') == 'region'
                        and row.get('contactRegion') == 'foot' and row.get('side') == side
                        and row.get('contactState') == 'direct_contact'
                        and row.get('surface') == 'raised_surface' and row.get('visible') is True],
                    'intervalCoverageProven': True,
                    'observedSampleCount': len({row['sourceTimeSec'] for row in timeline_rows
                        if row.get('landmark') == 'region' and row.get('contactRegion') == 'foot'
                        and row.get('side') == side and row.get('contactState') == 'direct_contact'
                        and row.get('surface') == 'raised_surface' and row.get('visible') is True}),
                    'jointAnchorsCreated': False,
                }
                continue
            active = (pinned[:, names.index(f'{side}_ankle')]
                      | pinned[:, names.index(f'{side}_foot')])
            if side in full_cycle_sides:
                active[:] = True
            coverage[side] = {'coveredFrames': int(active.sum()), 'requiredFrames': count}
            # A stationary whole-source claim needs coverage between observations,
            # and cannot join distinct replants into one immutable stance.
            changed_anchor = any(len({value for value in anchor_ids[:, names.index(f'{side}_{part}')]
                                      if value is not None}) > 1 for part in ('ankle', 'foot'))
            continuous = (answer.get(f'{side}FootContactContinuity') == 'continuous'
                          or side in stationary_required_sides)
            if not np.any(active) or (continuous and (not np.all(active) or changed_anchor)):
                supported.discard(side)
    from .material_region_support import observed_region_sides
    region_required = {side for side in ('left', 'right')
                       if answer is not None and answer.get(side+'Foot') == 'supported_dorsum'}
    if ((payload.get('sourcePoseCameraReference') or {}).get('camera') or {}).get('bilateralAssignment') == 'swapped':
        region_required = {'right' if side == 'left' else 'left' for side in region_required}
    required.update(region_required)
    for side in observed_region_sides(payload):
        supported.add(side)
        coverage[side] = {'coveredFrames': count, 'requiredFrames': count,
                          'constraint': 'rolling_material_region',
                          'geometryCalibrationRequired': True}
    unresolved = sorted(required - supported)
    # A present but invalid timeline is missing/unresolved evidence, never a
    # contradictory source. Explicit same-time disagreement is evaluated
    # separately by source_support_contact_conflicts below.
    conflict = source_support_contact_conflicts(evidence, timeline_rows)
    # Disagreement between two observation channels is inconclusive evidence,
    # not proof that the source violates an exercise requirement. This gate
    # does not own the verified, time-scoped contract needed to make that call.
    if timeline_raw_present and not timeline_rows and required:
        unresolved = sorted(set(unresolved) | set(required))
    either_foot_satisfied = bool(supported.intersection({'left', 'right'}))
    either_foot_unresolved = bool(required_any_foot) and not either_foot_satisfied
    result = _support_readiness_result(
        status='ready' if not unresolved and not conflict and not either_foot_unresolved else 'incomplete',
        required_sides=required,
        resolved_sides=(required - set(unresolved)) if not conflict else (),
        unresolved_sides=(unresolved if not conflict else required),
        reason='source_support_contact_evidence_incomplete'
        if unresolved or conflict or either_foot_unresolved else None)
    if required_any_foot:
        result['required'] = True
        result['requiredContactRequirements'] = [dict(row) for row in required_any_foot]
        if either_foot_unresolved:
            result['unresolvedContactRequirements'] = [dict(row) for row in required_any_foot]
    if conflict:
        result['evidenceDisagreements'] = conflict
    result['stationaryContactCoverage'] = coverage
    result['raisedFootRegionSupportSides'] = sorted(regional_foot_sides)
    return result


def _validated_structured_definition_support(contract):
    """Return approved, definition-owned typed support intent or None.

    Callers without a current approved definition keep the legacy coarse-side
    requirement behavior. Inferred discovery hints are intentionally ignored.
    """
    if not isinstance(contract, dict) or contract.get('contractScope') != 'definition_only':
        return None
    if contract.get('actionDefinitionAuthority') != 'structured_definition':
        return None
    context = contract.get('motionContext')
    definition = context.get('exerciseDefinition') if isinstance(context, dict) else None
    if (not isinstance(definition, dict)
            or (definition.get('review') or {}).get('status') != 'approved'):
        return None
    from .youtube import (
        EXERCISE_MOTION_CONTRACT_POLICY_VERSION,
        exercise_motion_context_action_definition,
        normalize_bilateral_execution,
        normalize_body_support_requirements,
    )
    if contract.get('contractPolicyVersion') != EXERCISE_MOTION_CONTRACT_POLICY_VERSION:
        return None
    if exercise_motion_context_action_definition(context) is None:
        return None
    if contract.get('bilateralExecutionAuthority') != 'structured_definition':
        return None
    try:
        definition_bilateral = normalize_bilateral_execution(definition.get('bilateralExecution'))
        contract_bilateral = normalize_bilateral_execution(contract.get('bilateralExecution'))
    except (TypeError, ValueError):
        return None
    if contract_bilateral != definition_bilateral:
        return None
    actual = normalize_body_support_requirements(contract.get('bodySupportRequirements'))
    if actual is None:
        return None
    source_value = definition.get('bodySupportRequirements')
    expected = (normalize_body_support_requirements(source_value)
                if source_value is not None else {'required': [], 'prohibited': []})
    if expected is None or actual != expected:
        return None
    return {**actual, 'bilateralExecution': contract_bilateral}


def _same_source_time(left, right):
    try:
        left, right = float(left), float(right)
    except (TypeError, ValueError, OverflowError):
        return False
    return np.isfinite(left) and np.isfinite(right) and abs(left - right) <= 1e-6


def source_support_contact_conflicts(evidence, timeline_rows):
    """Return explicit same-side, same-time visual/patch disagreements.

    A ``toe_only`` patch from the uncalibrated classifier confirms forefoot
    contact but does not establish heel lift. It therefore cannot contradict a
    full-sole review unless the patch has an observed heel reference.
    """
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
    from .contact_constraints import (
        _indistinguishable_forefoot_patch_at_time,
        _neutral_pitch_forefoot_patch_at_time,
    )
    conflicts = []
    for row in timeline_rows:
        if (not isinstance(row, dict)
                or row.get('reviewOnly') is True
                or row.get('side') not in {'left', 'right'}):
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
            reviewed_as_full_sole_without_patch_heel = (
                state == 'full_sole' and patch_state == 'toe_only'
                and (patch_side.get('pitchReferenceSource') == 'heel_unobserved'
                     or _indistinguishable_forefoot_patch_at_time(
                         evidence, rig_side, timestamp)
                     or _neutral_pitch_forefoot_patch_at_time(
                         evidence, rig_side, timestamp))
            )
            disagreement = (
                patch_state in patch_state_to_visual_state
                and patch_state_to_visual_state[patch_state] != state
                and not reviewed_as_full_sole_without_patch_heel
            )
            if disagreement:
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


def pre_reconstruction_source_support_readiness(
        source_evidence, *, source_frames=None, ground_contact_mode=None,
        source_pose=None, source_video_path=None, exercise_motion_contract=None):
    """Join contact points and required ground authority before reconstruction."""
    evidence = source_evidence if isinstance(source_evidence, dict) else {}
    payload = {'sourceFootSupportEvidence': evidence, 'groundContactMode': ground_contact_mode}
    if exercise_motion_contract is not None:
        payload['exerciseMotionContract'] = exercise_motion_contract
    if source_frames is not None:
        payload['frames'] = [{'sourceTimeSec': frame.get('sourceTimeSec')} for frame in source_frames]
    readiness = support_contact_readiness(
        payload, source_pose=source_pose, source_video_path=source_video_path,
        require_geometry=False, exercise_motion_contract=exercise_motion_contract)
    if readiness['passed'] and ground_contact_mode in {'continuous', 'intermittent'}:
        from .body_support_observation import materialize_stationary_sole_support
        from .controlled_motion import source_support_authority
        authority = source_support_authority(
            payload, materialize_stationary_sole_support(payload), {})
        if authority.get('reason') == 'stationary_contact_evidence_unavailable':
            readiness = {**readiness, 'status': 'incomplete', 'available': False,
                         'passed': False, 'rejectionReasons': [authority['reason']]}
        elif authority.get('required') and authority.get('observedSupportContactCount'):
            # Observed support exists; regional evidence never creates anchors.
            # Camera/side-mapping and anchored-fit validation need the actual
            # reconstruction, so they stay deferred exactly as they are for
            # observed ground support.
            readiness = {
                **readiness,
                'observedSupportContactCount': authority['observedSupportContactCount'],
                'observedNonGroundSupportContactCount': authority.get(
                    'observedNonGroundSupportContactCount', 0),
                'requiredSourceSupportValidationDeferred': True,
            }
    return readiness


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
    if evidence.get('materialRegionContacts'):
        return False
    stationary = evidence.get('stationaryJoints') or []
    return bool(stationary) and set(stationary).issubset(PLANT_ONLY_SUPPORT_JOINTS)


def evidence_is_complete(evidence, names):
    if evidence.get('_materialFloorUnresolved'):
        return False
    stationary = evidence.get('stationaryJoints') or []
    generic_contacts = evidence.get('bodySurfaceContacts') or []
    generic_complete = bool(generic_contacts) and (
        evidence.get('_bodySurfaceSourceBound') is True
        and not evidence.get('_bodySurfaceGeometryPending')
        and not evidence.get('_bodySurfaceContactErrors')
        and all(isinstance(contact.get('patchBinding'), dict)
                and isinstance(contact.get('surfaceEstimate'), dict)
                for contact in generic_contacts))
    if ((not stationary and not evidence.get('materialRegionContacts') and not generic_complete)
            or not set(stationary).issubset(names)):
        return False
    if evidence.get('_bodySurfaceGenericRequired') and not generic_complete:
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


def _native_fullsole_coverage(evidence, side, frame_count, frame_positions=None):
    """Return frames covered by a validated native full-sole plane episode."""
    tracks = evidence.get('_nativeFootMaterialTracks')
    track = tracks.get(side) if isinstance(tracks, dict) and tracks.get('version') == 2 else None
    if not isinstance(track, dict):
        return np.zeros(frame_count, dtype=bool)
    try:
        from .contact_interpolation import _validated_native_side_track
        active, _, _, _ = _validated_native_side_track(track, len(track['active']), side)
        positions = (np.arange(frame_count, dtype=float) if frame_positions is None
                     else np.asarray(frame_positions, dtype=float))
        if positions.shape != (frame_count,) or not np.isfinite(positions).all():
            raise ValueError('native full-sole coverage clock is invalid')
        coverage = np.zeros(frame_count, dtype=bool)
        for episode in track['episodes']:
            if (episode.get('regionRole') == 'full_sole'
                    and np.asarray(episode.get('surfaceNormal'), dtype=float).shape == (3,)
                    and np.isfinite(float(episode.get('planeOffsetMeters')))):
                coverage |= ((positions >= episode['startFrame'] - 1e-9)
                             & (positions <= episode['endFrame'] + 1e-9))
        return coverage & np.asarray([
            0 <= value < len(active) and active[int(np.clip(np.floor(value), 0, len(active)-1))]
            for value in positions], dtype=bool)
    except (KeyError, TypeError, ValueError, IndexError, OverflowError):
        return np.zeros(frame_count, dtype=bool)


def _missing_material_sole_pitch_sides(evidence, names=None, frame_count=None,
                                       frame_positions=None, full_sole_active=None):
    """Require legacy pitch only where no validated native fullsole plane is bound."""
    pitches = (evidence.get('materialFootRestPitchRadians')
               or evidence.get('footRestPitchRadians') or {})
    if full_sole_active is None and names is not None and frame_count is not None:
        full_sole_active = full_sole_contact_masks(
            evidence, names, frame_count, frame_positions=frame_positions)
    missing = []
    for contact in evidence.get('soleContacts', []):
        joints = contact.get('joints') or []
        if len(joints) != 3:
            continue
        side = str(joints[1]).split('_', 1)[0]
        try:
            pitch = float(pitches[side])
        except (KeyError, TypeError, ValueError, OverflowError):
            pitch_missing = True
        else:
            pitch_missing = not np.isfinite(pitch)
        if pitch_missing:
            if (names is not None and full_sole_active is not None
                    and len(joints) == 3 and joints[1] in names and joints[2] in names):
                sole_active = (full_sole_active[:, names.index(joints[1])] &
                               full_sole_active[:, names.index(joints[2])])
                native_active = _native_fullsole_coverage(
                    evidence, side, len(sole_active), frame_positions)
                if not np.any(sole_active & ~native_active):
                    continue
            missing.append(side)
            continue
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


def _body_surface_contact_columns(record):
    mode = record.get('contactMode')
    if mode == 'rolling':
        return 1
    points = len((record.get('patchBinding') or {}).get('points') or [])
    if points <= 0:
        return 1
    polygon_columns = 1 if (record.get('surfaceEstimate') or {}).get('polygonWorld') else 0
    # Every stationary/sliding contact also owns one whole-material
    # nonpenetration row, independent of the binding's patch point.
    return points * ((3 if mode == 'stationary' else 1) + polygon_columns) + 1


def _surface_polygon_outside_distances(points, polygon, normal):
    """Distance of 3D points outside a finite planar polygon, in meters."""
    points = np.asarray(points, dtype=float)
    polygon = np.asarray(polygon, dtype=float)
    normal = np.asarray(normal, dtype=float)
    if (points.ndim != 2 or points.shape[1] != 3 or polygon.ndim != 2
            or polygon.shape[1] != 3 or len(polygon) < 3
            or not np.isfinite(points).all() or not np.isfinite(polygon).all()
            or normal.shape != (3,) or not np.isfinite(normal).all()):
        raise ValueError('body_surface_contact_polygon_unsupported')
    axis = np.eye(3)[int(np.argmin(np.abs(normal)))]
    tangent_one = np.cross(normal, axis)
    tangent_one /= max(np.linalg.norm(tangent_one), 1e-12)
    tangent_two = np.cross(normal, tangent_one)
    projected_polygon = np.stack((polygon @ tangent_one, polygon @ tangent_two), axis=1)
    projected_points = np.stack((points @ tangent_one, points @ tangent_two), axis=1)
    edges = np.roll(projected_polygon, -1, axis=0) - projected_polygon
    lengths_squared = np.einsum('ij,ij->i', edges, edges)
    if np.any(lengths_squared <= 1e-16):
        raise ValueError('body_surface_contact_polygon_unsupported')
    relative = projected_points[:, None, :] - projected_polygon[None, :, :]
    fractions = np.clip(np.einsum('pvi,vi->pv', relative, edges) / lengths_squared, 0., 1.)
    nearest = projected_polygon[None, :, :] + fractions[:, :, None] * edges[None, :, :]
    edge_distances = np.linalg.norm(projected_points[:, None, :] - nearest, axis=2)
    outside_distance = np.min(edge_distances, axis=1)
    inside = np.zeros(len(projected_points), dtype=bool)
    x, y = projected_points.T
    for index, start in enumerate(projected_polygon):
        end = projected_polygon[(index + 1) % len(projected_polygon)]
        crosses = ((start[1] > y) != (end[1] > y)) & (
            x < (end[0] - start[0]) * (y - start[1]) /
            (end[1] - start[1] + np.finfo(float).tiny) + start[0])
        inside ^= crosses
    return np.where(inside, 0., outside_distance)


def _body_surface_contact_frame_map(record, count, frame_positions=None):
    positions = (np.arange(count, dtype=float) if frame_positions is None
                 else np.asarray(frame_positions, dtype=float))
    if positions.shape != (count,) or not np.isfinite(positions).all():
        return None, 'body_surface_contact_fit_clock_invalid'
    rows = [row for row in (record.get('sourceEvidence') or {}).get('observations') or []
            if row.get('contactState') == 'direct_contact' and row.get('visible') is True]
    if not rows:
        return None, 'body_surface_contact_has_no_direct_samples'
    active = np.zeros(count, dtype=bool)
    for row in rows:
        source_index = row.get('sourcePoseFrameIndex')
        if isinstance(source_index, bool) or not isinstance(source_index, int):
            return None, 'body_surface_contact_source_frame_index_invalid'
        matches = np.flatnonzero(np.abs(positions - source_index) <= 1e-6)
        # Contacts outside this selected fit window are not missing evidence;
        # a repeated source key may map to multiple playback rows. Fractional
        # positions never match and therefore never inherit a nearby contact.
        active[matches] = True
    return active, None


def _body_surface_penetration(primitive, normal, offset, polygon):
    """Whole-native penetration below a support; positive gap is allowed."""
    from .body_surface_geometry import native_min_signed_distance
    minimum_distance = native_min_signed_distance(
        primitive['vertices'], primitive['triangles'], normal, offset, polygon)
    return np.where(
        np.isfinite(minimum_distance), np.minimum(minimum_distance, 0.), 0.)


def _body_surface_contact_residuals(points, names, evidence, *, frame_positions=None):
    """Material-patch surface residuals on directly observed source samples only."""
    records = evidence.get('bodySurfaceContacts') or []
    count = len(points)
    if not records and not evidence.get('_bodySurfaceContactErrors'):
        return np.empty((count, 0)), []
    columns = []
    declared_errors = list(evidence.get('_bodySurfaceContactErrors') or [])
    errors = list(declared_errors)
    if frame_positions is None:
        selected_mapping = evidence.get('_fitFrameStateIndices')
        if isinstance(selected_mapping, list) and len(selected_mapping) == count:
            frame_positions = selected_mapping
    meshes = None
    for record in records:
        mode = record.get('contactMode')
        width = _body_surface_contact_columns(record)
        active, mapping_error = _body_surface_contact_frame_map(
            record, count, frame_positions)
        if active is None:
            errors.append(mapping_error or 'body_surface_contact_mapping_unresolved')
            columns.append(np.full((count, width), 2. * TOLERANCE_METERS))
            continue
        try:
            if meshes is None:
                from .body_surface_geometry import body_surface_primitive_meshes
                binding = {}
                native_foot_geometry = evidence.get('nativeFootGeometry')
                if native_foot_geometry is not None:
                    binding['nativeFootGeometry'] = native_foot_geometry
                meshes = body_surface_primitive_meshes(
                    points, names, binding=binding)
            from .body_surface_geometry import evaluate_contact_patch
            patch_points = evaluate_contact_patch(meshes, record['patchBinding'])
            estimate = record['surfaceEstimate']
            normal = np.asarray(estimate['normal'], dtype=float)
            offset = float(estimate['offsetMeters'])
            primitive = meshes[record['patchBinding']['primitiveId']]
            if mode == 'rolling':
                if estimate.get('polygonWorld'):
                    raise ValueError('body_surface_contact_finite_polygon_rolling_unsupported')
                vertex_distances = np.einsum(
                    'fvc,c->fv', primitive['vertices'], normal) - offset
                # Signed minimum over the complete bound mesh gives both the
                # contact gap (>0) and deepest penetration (<0), while allowing
                # the supporting material point to migrate during rolling.
                minimum_distance = np.min(vertex_distances, axis=1)
                residual = np.where(active[:, None], minimum_distance[:, None], 0.)
            elif mode == 'sliding':
                penetration = _body_surface_penetration(
                    primitive, normal, offset, estimate.get('polygonWorld'))
                signed_distance = np.einsum('fpc,c->fp', patch_points, normal) - offset
                residual_parts = [signed_distance]
                if estimate.get('polygonWorld'):
                    outside = _surface_polygon_outside_distances(
                        patch_points.reshape(-1, 3), estimate['polygonWorld'], normal
                    ).reshape(count, -1)
                    residual_parts.append(outside)
                residual = np.concatenate(
                    residual_parts + [penetration[:, None]], axis=1)
                residual = np.where(active[:, None], residual, 0.)
            elif mode == 'stationary':
                penetration = _body_surface_penetration(
                    primitive, normal, offset, estimate.get('polygonWorld'))
                signed_distance = np.einsum('fpc,c->fp', patch_points, normal) - offset
                active_rows = np.flatnonzero(active)
                reference = patch_points[active_rows[0]]
                axis = np.eye(3)[int(np.argmin(np.abs(normal)))]
                tangent_one = np.cross(normal, axis)
                tangent_one /= max(np.linalg.norm(tangent_one), 1e-12)
                tangent_two = np.cross(normal, tangent_one)
                displacement = patch_points - reference[None, :, :]
                tangent_one_delta = np.einsum('fpc,c->fp', displacement, tangent_one)
                tangent_two_delta = np.einsum('fpc,c->fp', displacement, tangent_two)
                residual_parts = [signed_distance, tangent_one_delta, tangent_two_delta]
                if estimate.get('polygonWorld'):
                    outside = _surface_polygon_outside_distances(
                        patch_points.reshape(-1, 3), estimate['polygonWorld'], normal
                    ).reshape(count, -1)
                    residual_parts.append(outside)
                residual = np.concatenate([
                    np.stack(residual_parts, axis=-1).reshape(count, -1),
                    penetration[:, None],
                ], axis=1)
                residual = np.where(active[:, None], residual, 0.)
            else:
                raise ValueError('body_surface_contact_mode_unsupported')
            if residual.shape != (count, width) or not np.isfinite(residual).all():
                raise ValueError('body_surface_contact_residual_shape_invalid')
            columns.append(residual)
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            errors.append(f"body_surface_contact_{record.get('contactId')}_geometry_unavailable:{exc}")
            columns.append(np.full((count, width), 2. * TOLERANCE_METERS))
    if declared_errors:
        columns.append(np.full((count, len(declared_errors)), 2. * TOLERANCE_METERS))
    return np.concatenate(columns, axis=1) if columns else np.empty((count, 0)), errors


def _body_surface_contact_validation(points, names, evidence, *, frame_positions=None):
    residuals, errors = _body_surface_contact_residuals(
        points, names, evidence, frame_positions=frame_positions)
    if not evidence.get('bodySurfaceContacts') and not evidence.get('_bodySurfaceContactErrors'):
        return {'required': False, 'passed': True}
    maximum = float(np.max(np.abs(residuals), initial=0.))
    reasons = ['body_surface_contact_evidence_unresolved'] if errors else []
    if maximum > TOLERANCE_METERS:
        reasons.append('body_surface_contact_geometry_mismatch')
    return {'required': True, 'passed': not reasons,
            'maximumSurfaceErrorMeters': maximum,
            'toleranceMeters': TOLERANCE_METERS,
            'rejectionReasons': reasons, 'evidenceErrors': errors}


def _native_foot_material_contact_residuals(points, names, evidence, *, frame_positions=None,
                                           side_axes_override=None):
    """Evaluate bound native shoe points without fabricating body-surface source rows."""
    declared_errors = list(evidence.get('_nativeFootMaterialErrors') or [])
    tracks = evidence.get('_nativeFootMaterialTracks')
    if not isinstance(tracks, dict) or tracks.get('version') != 2:
        if declared_errors:
            return np.full((len(points), len(declared_errors)), 2. * TOLERANCE_METERS), declared_errors
        return np.empty((len(points), 0)), []
    from .native_foot_geometry import validated_native_foot_geometry
    from .foot_geometry import foot_scale_from_pose, shoe_vertices
    from .material_region_support import shoe_triangles
    native = validated_native_foot_geometry(evidence.get('nativeFootGeometry'))
    if native is None:
        errors = declared_errors or ['native_foot_material_geometry_unavailable']
        return np.full((len(points), len(errors)), 2. * TOLERANCE_METERS), errors
    positions = (np.arange(len(points), dtype=float) if frame_positions is None
                 else np.asarray(frame_positions, dtype=float))
    if positions.shape != (len(points),) or not np.isfinite(positions).all():
        return np.full((len(points), 1), 2. * TOLERANCE_METERS), [
            'native_foot_material_fit_clock_invalid']
    if '_nativeFootScale' in evidence:
        scale = float(evidence['_nativeFootScale'])
    else:
        scale = float(foot_scale_from_pose(points[0], names))
    if not np.isfinite(scale) or scale <= 0.:
        return np.full((len(points), 1), 2. * TOLERANCE_METERS), [
            'native_foot_material_foot_scale_invalid']
    triangles = shoe_triangles()
    errors, columns = list(declared_errors), []
    axes_at_positions = {}
    if declared_errors:
        columns.append(np.full((len(points), len(declared_errors)), 2. * TOLERANCE_METERS))
    for side in ('left', 'right'):
        track = tracks.get(side)
        if track is None:
            continue
        try:
            ankle_i, foot_i = names.index(f'{side}_ankle'), names.index(f'{side}_foot')
            directions = np.asarray(track['directions'], dtype=float)
            override = (side_axes_override or {}).get(side)
            side_axes = np.asarray(track['sideAxes'] if override is None else override,
                                   dtype=float)
            if (directions.shape != (len(tracks[side]['active']), 3)
                    or side_axes.ndim != 2 or side_axes.shape[1] != 3
                    or not np.isfinite(side_axes).all()
                    or (override is None and side_axes.shape != directions.shape)
                    or (override is not None and len(side_axes) != len(points))):
                raise ValueError('native material track basis is malformed')
            count = len(directions)
            if len(points) != count and np.max(positions, initial=0.) >= count:
                raise ValueError('native material track frame map is unavailable')
        except (KeyError, ValueError, IndexError) as exc:
            errors.append(f'native_foot_material_{side}_track_unavailable:{exc}')
            columns.append(np.full((len(points), 1), 2. * TOLERANCE_METERS))
            continue
        if override is None:
            first = np.clip(np.floor(positions).astype(int), 0, count - 1)
            last = np.clip(first + 1, 0, count - 1)
            alpha = (positions - np.floor(positions))[:, None]
            axis_rows = side_axes[first] * (1. - alpha) + side_axes[last] * alpha
        else:
            axis_rows = side_axes
        axes_at_positions[side] = axis_rows
        for episode in track.get('episodes') or []:
            try:
                normal = np.asarray(episode['surfaceNormal'], dtype=float)
                plane_offset = float(episode['planeOffsetMeters'])
                triangle_index = int(episode['triangleIndex'])
                bary = np.asarray(episode['barycentric'], dtype=float)
                if (normal.shape != (3,) or abs(np.linalg.norm(normal) - 1.) > 1e-6
                        or not 0 <= triangle_index < len(triangles) or bary.shape != (3,)
                        or not np.isfinite(bary).all() or np.any(bary < 0.)
                        or not np.isclose(bary.sum(), 1., atol=1e-6, rtol=0.)):
                    raise ValueError('native material binding is malformed')
            except (KeyError, TypeError, ValueError, OverflowError) as exc:
                errors.append(f'native_foot_material_{side}_binding_unavailable:{exc}')
                columns.append(np.full((len(points), 1), 2. * TOLERANCE_METERS))
                continue
            active = (positions >= int(episode['startFrame']) - 1e-9) & (
                positions <= int(episode['endFrame']) + 1e-9)
            ankle, foot = points[:, ankle_i], points[:, foot_i]
            vector = foot - ankle
            lengths = np.linalg.norm(vector, axis=1)
            if np.any(lengths <= 1e-9):
                errors.append(f'native_foot_material_{side}_zero_bone')
                columns.append(np.full((len(points), 1), 2. * TOLERANCE_METERS))
                continue
            forward = vector / lengths[:, None]
            lateral = axis_rows - forward * np.sum(axis_rows * forward, axis=1, keepdims=True)
            lateral_length = np.linalg.norm(lateral, axis=1)
            if np.any(lateral_length <= 1e-9):
                errors.append(f'native_foot_material_{side}_side_axis_collinear')
                columns.append(np.full((len(points), 1), 2. * TOLERANCE_METERS))
                continue
            lateral /= lateral_length[:, None]
            shoes = shoe_vertices(
                ankle, foot, lateral, None, scale,
                native_geometry=native['sides'][side])
            from .body_surface_geometry import evaluate_contact_patch
            primitive_id = episode['primitiveId']
            material = evaluate_contact_patch(
                {primitive_id: {'vertices': shoes, 'triangles': triangles}},
                {'primitiveId': primitive_id,
                 'points': [{'triangleIndex': triangle_index,
                             'barycentric': bary.tolist()}]})[:, 0]
            if episode.get('mode') == 'verticalOnly':
                contact_error = (material @ normal - plane_offset)[:, None]
            else:
                target = np.asarray(episode['targetWorld'], dtype=float)
                contact_error = material - target
            penetration = np.minimum(np.min(shoes @ normal - plane_offset, axis=1), 0.)[:, None]
            residual_parts = [contact_error, penetration]
            if episode.get('regionRole') == 'full_sole':
                # The native rendered shoe uses three 8-vertex rings. Vertices
                # 5/6 in each ring are the heel, midfoot, and forefoot sole edge
                # samples; constrain those actual mesh points to the observed
                # plane so a fixed barycentric anchor cannot hide a lifted heel.
                sole_vertices = shoes[:, _NATIVE_SHOE_SOLE_RING_VERTICES]
                residual_parts.append(
                    np.einsum('fvc,c->fv', sole_vertices, normal) - plane_offset)
            residual = np.concatenate(residual_parts, axis=1)
            columns.append(np.where(active[:, None], residual, 0.))
    if evidence.get('_nativeFootMirrorRequired') is True and all(
            f'{side}_{joint}' in names for side in ('left', 'right')
            for joint in ('hip', 'ankle', 'foot')):
        try:
            hip_axis = (points[:, names.index('right_hip')]
                        - points[:, names.index('left_hip')])
            # Canonical stance reflection is a vertical sagittal plane. Hip
            # height asymmetry must not tilt that plane and reflect foot
            # material through the ground; the world-up direction is shared.
            hip_axis[:, 1] = 0.
            hip_length = np.linalg.norm(hip_axis, axis=1, keepdims=True)
            if np.any(hip_length <= 1e-9):
                raise ValueError('bilateral hip reflection axis is degenerate')
            hip_axis /= hip_length
            left_forward = points[:, names.index('left_foot')] - points[:, names.index('left_ankle')]
            right_forward = points[:, names.index('right_foot')] - points[:, names.index('right_ankle')]
            left_forward /= np.maximum(np.linalg.norm(left_forward, axis=1, keepdims=True), 1e-9)
            right_forward /= np.maximum(np.linalg.norm(right_forward, axis=1, keepdims=True), 1e-9)
            left_axis = np.asarray((side_axes_override or {}).get(
                'left', tracks['left']['sideAxes']), dtype=float)
            right_axis = np.asarray((side_axes_override or {}).get(
                'right', tracks['right']['sideAxes']), dtype=float)
            left_axis -= left_forward * np.sum(left_axis * left_forward, axis=1, keepdims=True)
            right_axis -= right_forward * np.sum(right_axis * right_forward, axis=1, keepdims=True)
            left_axis /= np.maximum(np.linalg.norm(left_axis, axis=1, keepdims=True), 1e-9)
            right_axis /= np.maximum(np.linalg.norm(right_axis, axis=1, keepdims=True), 1e-9)
            reflected_forward = right_forward - 2. * hip_axis * np.sum(
                right_forward * hip_axis, axis=1, keepdims=True)
            reflected_axis = right_axis - 2. * hip_axis * np.sum(
                right_axis * hip_axis, axis=1, keepdims=True)
            # The side axis is cross(forward, up), an axial vector under
            # reflection; unlike forward it picks up the determinant sign.
            left_ankle = points[:, names.index('left_ankle')]
            right_ankle = points[:, names.index('right_ankle')]
            left_mesh = shoe_vertices(
                left_ankle, points[:, names.index('left_foot')], left_axis,
                None, scale, native_geometry=native['sides']['left'])
            right_mesh = shoe_vertices(
                right_ankle, points[:, names.index('right_foot')], right_axis,
                None, scale, native_geometry=native['sides']['right'])
            left_relative, right_relative = (left_mesh - left_ankle[:, None, :],
                                             right_mesh - right_ankle[:, None, :])
            forward_reach = np.maximum(
                np.max(np.abs(np.sum(left_relative * left_forward[:, None, :], axis=2)), axis=1),
                np.max(np.abs(np.sum(right_relative * right_forward[:, None, :], axis=2)), axis=1))
            lateral_reach = np.maximum(
                np.max(np.abs(np.sum(left_relative * left_axis[:, None, :], axis=2)), axis=1),
                np.max(np.abs(np.sum(right_relative * right_axis[:, None, :], axis=2)), axis=1))
            # Convert orientation-vector disagreement into the displacement it
            # creates at the actual rendered shoe's longitudinal and lateral
            # extents. These residuals are therefore meters, like the geometry
            # tolerance, rather than unitless direction deltas.
            columns.append(np.concatenate((
                (left_forward - reflected_forward) * forward_reach[:, None],
                (left_axis + reflected_axis) * lateral_reach[:, None]), axis=1))
        except (KeyError, ValueError, TypeError, IndexError) as exc:
            errors.append(f'native_foot_material_bilateral_orientation_unavailable:{exc}')
            columns.append(np.full((len(points), 6), 2. * TOLERANCE_METERS))
    fit_constraints = evidence.get('_nativeFullsoleFitConstraints')
    if isinstance(fit_constraints, dict):
        first = np.clip(np.floor(positions).astype(int), 0, count - 1)
        last = np.clip(np.ceil(positions).astype(int), 0, count - 1)
        alpha = (positions - np.floor(positions))[:, None]
        for side, values in (fit_constraints.get('orientationTargets') or {}).items():
            try:
                active = np.asarray(values['active'], dtype=bool)
                target_axes = np.asarray(values['sideAxes'], dtype=float)
                current_axes = np.asarray(axes_at_positions[side], dtype=float)
                if (active.shape != (len(tracks[side]['active']),)
                        or target_axes.shape != (len(active), 3)
                        or current_axes.shape != (len(points), 3)
                        or len(points) != len(active)):
                    raise ValueError('native full-sole fit orientation binding is malformed')
                rows = active[first] & active[last]
                target = target_axes[first] * (1. - alpha) + target_axes[last] * alpha
                # A stationary full-sole material episode fixes its carried
                # lateral axis as well as its anchor and plane. Keep this fit
                # target separate from source observations and source pins.
                columns.append(np.where(rows[:, None], scale * (current_axes - target), 0.))
            except (KeyError, TypeError, ValueError, IndexError) as exc:
                errors.append(f'native_foot_material_{side}_fit_orientation_unavailable:{exc}')
                columns.append(np.full((len(points), 3), 2. * TOLERANCE_METERS))
    if not columns:
        return np.empty((len(points), 0)), errors
    return np.concatenate(columns, axis=1), errors


def _native_marker_observations_at_frame(observations, frame_index):
    """Select nearest per-side marker evidence only inside its source interval."""
    by_side = {}
    for row in observations or []:
        left, right = float(row['leftFrame']), float(row['rightFrame'])
        if left <= frame_index <= right:
            side = row['motionSide']
            distance = abs(left + float(row['alpha']) - frame_index)
            previous = by_side.get(side)
            if previous is None or distance < previous[0]:
                by_side[side] = (distance, row)
    return [row for _, row in by_side.values()]


def _native_side_axes_for_coordinates(rig, coordinates, evidence, frame_indices=None,
                                      *, frame_positions=None, wrap=False, publication=True):
    """Apply current FK rotations to carried axes on the actual sample clock.

    A stationary full-sole episode binds one source-measured local material
    axis for its interval. Per-frame world observations can contain small
    basis jitter; transporting each as a different foot-local axis would make
    one rigid shoe deform during a claimed stationary contact.
    """
    if publication and getattr(rig, 'material_frames', None) is not None:
        from .controlled_motion import _sampling_payload
        from .native_material_frames import material_axes
        values = np.asarray(coordinates, dtype=float).reshape(-1, rig.width)
        positions = (frame_positions if frame_positions is not None else
                     frame_indices if frame_indices is not None else np.arange(len(values)))
        # Reference curves are immutable; sampled current q is local and complete
        # for each query, so no missing remote current state is invented.
        return material_axes(_sampling_payload(rig, rig.initial), positions,
                             wrap=wrap, coordinates=values)
    tracks = evidence.get('_nativeFootMaterialTracks')
    if not isinstance(tracks, dict) or tracks.get('version') != 2:
        return None
    values = np.asarray(coordinates, dtype=float)
    if values.ndim == 1:
        values = values[None, :]
    reference = getattr(rig, 'material_reference_coordinates', rig.initial)
    current_world = rig.global_rotations(values)
    fractional = frame_positions is not None
    if fractional:
        positions = np.asarray(frame_positions, dtype=float).reshape(-1)
        frame_count = len(reference)
        if positions.shape != (len(values),) or not np.isfinite(positions).all() or frame_count <= 0:
            raise ValueError('native material FK frame positions are unavailable')
        positions = (np.mod(positions, frame_count) if wrap
                     else np.clip(positions, 0., frame_count - 1.))
        first = np.floor(positions).astype(int)
        last = (first + 1) % frame_count if wrap else np.minimum(first + 1, frame_count - 1)
        alpha = positions - first
        from .rig_interpolation import INTERPOLATION, hermite_samples
        from .rig_playback import sample_rig_coordinates
        reference_rig = {'coordinates': reference, 'interpolation': INTERPOLATION}
        reference_coordinates = sample_rig_coordinates(
            reference_rig, positions, wrap=wrap)
        reference_world = rig.global_rotations(reference_coordinates)
        smooth_limiter = True  # Native v2 axes use the v2 quaternion-Hermite clock.
    else:
        if frame_indices is None:
            frame_indices = np.arange(len(values), dtype=int)
        frame_indices = np.asarray(frame_indices, dtype=int).reshape(-1)
        if frame_indices.shape != (len(values),) or np.any(frame_indices < 0) or np.any(
                frame_indices >= len(reference)):
            raise ValueError('native material FK frame mapping is unavailable')
        initial_world = rig.global_rotations(reference[frame_indices])
    result = {}
    for side in ('left', 'right'):
        track = tracks.get(side)
        if track is None:
            continue
        source = np.asarray(track.get('sideAxes'), dtype=float)
        if (source.ndim != 2 or source.shape[1] != 3
                or len(source) != len(reference)
                or not np.isfinite(source).all()):
            raise ValueError(f'{side} native material source side-axis mapping is invalid')
        foot = rig.names.index(f'{side}_foot')
        reference_world_all = rig.global_rotations(reference)
        local_source_all = np.einsum(
            'fji,fj->fi', reference_world_all[foot], source)
        calibrated_local_all = local_source_all.copy()
        episode_bindings = []
        active = np.asarray(track.get('active', ()), dtype=bool)
        anchor_ids = np.asarray(track.get('anchorIds', ()), dtype=object)
        if (active.shape == (len(reference),)
                and (anchor_ids.shape == (len(reference),)
                     or not track.get('anchorIds'))):
            bound_frames = np.zeros(len(reference), dtype=bool)
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
                if start < 0 or end < start or end >= len(reference):
                    continue
                rows_mask = active & (np.arange(len(reference)) >= start) & (
                    np.arange(len(reference)) <= end)
                anchor_id = episode.get('anchorId')
                if anchor_id is not None:
                    if anchor_ids.shape != (len(reference),):
                        continue
                    rows_mask &= anchor_ids == anchor_id
                rows = np.flatnonzero(rows_mask)
                if len(rows) < 2 or np.any(bound_frames[rows]):
                    continue
                local_rows = local_source_all[rows]
                lengths = np.linalg.norm(local_rows, axis=1)
                valid = np.isfinite(lengths) & (lengths > 1e-8)
                rows, local_rows, lengths = rows[valid], local_rows[valid], lengths[valid]
                if len(rows) < 2:
                    continue
                directions = local_rows / lengths[:, None]
                reference_row = int(np.argmin(
                    np.sum(1. - np.clip(directions @ directions.T, -1., 1.), axis=1)))
                reference_axis = directions[reference_row] * float(np.median(lengths))
                calibrated_local_all[rows] = reference_axis
                bound_frames[rows] = True
                episode_bindings.append({
                    'startFrame': start,
                    'endFrame': end,
                    'anchorId': anchor_id,
                    'frames': rows,
                    'localAxis': reference_axis,
                })
        if fractional:
            local = np.einsum(
                'fji,fj->fi', reference_world[foot],
                hermite_samples(source, first, last, alpha, wrap=wrap,
                                smooth_limiter=smooth_limiter))
            for binding in episode_bindings:
                positions_in_episode = ((positions >= binding['startFrame'])
                                        & (positions <= binding['endFrame']))
                left_active = active[first]
                right_active = active[last]
                positions_in_episode &= left_active & right_active
                if binding['anchorId'] is not None:
                    positions_in_episode &= (
                        anchor_ids[first] == binding['anchorId']) & (
                            anchor_ids[last] == binding['anchorId'])
                local[positions_in_episode] = binding['localAxis']
        else:
            local = calibrated_local_all[frame_indices]
        result[side] = np.einsum('fij,fj->fi', current_world[foot], local)
    return result


def geometry_errors(points, names, evidence, *, frame_positions=None, bounded=False,
                    native_side_axes=None):
    """Plane equality and one-sided chain clearance in observed contact time."""
    errors = []
    active, _ = support_contact_masks(
        evidence, names, len(points), frame_positions=frame_positions)
    full_sole_active = full_sole_contact_masks(
        evidence, names, len(points), frame_positions=frame_positions)
    missing_pitch_sides = set(_missing_material_sole_pitch_sides(
        evidence, names, len(points), frame_positions, full_sole_active))
    native_fullsole = {
        side: _native_fullsole_coverage(evidence, side, len(points), frame_positions)
        for side in ('left', 'right')}
    for contact in evidence.get('soleContacts', []):
        _, ankle, toe = (points[:, names.index(n)] for n in contact['joints'])
        side = str(contact['joints'][1]).split('_', 1)[0]
        sole_active = (full_sole_active[:, names.index(contact['joints'][1])] &
                       full_sole_active[:, names.index(contact['joints'][2])])
        native_active = native_fullsole.get(side, np.zeros(len(points), dtype=bool))
        legacy_active = sole_active & ~native_active
        if side in missing_pitch_sides:
            # Keep optimizer residuals finite while making absent geometry
            # authority impossible to satisfy where the legacy proxy remains
            # authoritative. A toe-only episode cannot replace heel geometry.
            errors.append(np.where(legacy_active, 2. * TOLERANCE_METERS, 0.)[:, None])
            continue
        normal = np.asarray(contact['normal'], dtype=float)
        normal /= np.linalg.norm(normal)
        pitches = evidence.get('materialFootRestPitchRadians') or evidence.get('footRestPitchRadians') or {}
        try:
            rest_pitch = float(pitches.get(side, 0.))
        except (AttributeError, TypeError, ValueError, OverflowError):
            rest_pitch = 0.
        error = _material_sole_plane_error(ankle, toe, normal, rest_pitch)
        errors.append(np.where(legacy_active, error, 0.)[:, None])
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
    for joint in evidence.get('_floorMaterialContacts', []):
        region = _floor_material_region(points, names, evidence, joint, frame_positions)
        minimum = region[:, :, 1].min(axis=1)-evidence['_renderFloorY']
        if bounded:
            minimum = np.minimum(minimum, 0.) + np.maximum(minimum - TOLERANCE_METERS, 0.)
        errors.append(np.where(active[:, names.index(joint)], minimum, np.minimum(minimum, 0.))[:, None])
    body_surface_errors, _ = _body_surface_contact_residuals(
        points, names, evidence, frame_positions=frame_positions)
    if body_surface_errors.shape[1]:
        errors.append(body_surface_errors)
    native_errors, _ = _native_foot_material_contact_residuals(
        points, names, evidence, frame_positions=frame_positions,
        side_axes_override=native_side_axes)
    if native_errors.shape[1]:
        errors.append(native_errors)
    return np.concatenate(errors, axis=1) if errors else np.empty((len(points), 0))


def geometry_constraint_errors(points, names, evidence, *, frame_positions=None,
                              native_side_axes=None):
    """Fit within observed floor-contact tolerance without trading away fixed anchors."""
    return geometry_errors(points, names, evidence, frame_positions=frame_positions,
                           bounded=True, native_side_axes=native_side_axes)


def candidate_material_evidence(points, names, evidence):
    """Predict the same material frames native playback builds from stored joints."""
    if not evidence.get('_floorMaterialContacts'):
        return evidence
    from .render_geometry import material_body_axes, material_leg_sides
    frames = [{'joints': dict(zip(names, row.tolist()))} for row in points]
    return {**evidence, '_materialReferencePoints': points,
            '_materialBodyAxes': material_body_axes(points, names),
            '_materialLegSides': material_leg_sides(frames, loopable=bool(evidence.get('_materialLoopable')))}


def _floor_material_region(points, names, evidence, joint, positions):
    from .render_geometry import knee_support_region
    side = joint.split('_')[0]
    tracks = evidence.get('_materialLegSides') or []
    # A one-pose calibration uses the representative source material frame;
    # trajectory/dense callers supply their actual source frame positions.
    positions = (np.full(len(points),evidence['_materialCalibrationPosition'])
                 if positions is None and '_materialCalibrationPosition' in evidence else
                 np.linspace(0, max(0,len(tracks)-1),len(points))
                 if positions is None else np.asarray(positions))
    key = side+'_knee->'+side+'_ankle'
    axes = np.asarray([row.get(key, [1.,0.,0.]) for row in tracks])
    first = np.floor(positions).astype(int)
    first = np.clip(first, 0, len(axes)-1)
    last = ((first+1) % len(axes) if evidence.get('_materialLoopable') else
            np.minimum(first+1,len(axes)-1))
    alpha = (positions-np.floor(positions))[:,None]
    sampled = axes[first]*(1-alpha)+axes[last]*alpha
    body = evidence.get('_materialBodyAxes')
    # The native renderer holds its stabilized body axes at playbackIndex;
    # only limb-side tracks interpolate toward playbackNextIndex.
    body_sampled = None if body is None else body[first].copy()
    reference = evidence.get('_materialReferencePoints')
    if reference is not None and not evidence.get('_materialFinalValidation'):
        source = np.stack([np.column_stack([
            np.interp(positions,np.arange(len(reference)),reference[:,joint_index,i])
            for i in range(3)]) for joint_index in range(len(names))],axis=1)
        def frame(values):
            unit = lambda a: a / np.maximum(np.linalg.norm(a,axis=1,keepdims=True),1e-12)
            lateral = unit(values[:,names.index('right_hip')]-values[:,names.index('left_hip')])
            up = values[:,names.index('neck')]-values[:,names.index('pelvis')]
            up = unit(up-lateral*np.sum(up*lateral,axis=1)[:,None])
            return np.stack([lateral,up,unit(np.cross(lateral,up))],axis=1)
        source_frame, candidate_frame = frame(source), frame(points)
        if body_sampled is not None:
            local = np.einsum('fai,fbi->fab',body_sampled,source_frame)
            body_sampled = np.einsum('fab,fbi->fai',local,candidate_frame)
        from .foot_geometry import transport_sides
        unit = lambda a: a / np.maximum(np.linalg.norm(a,axis=1,keepdims=True),1e-12)
        a,b = names.index(side+'_knee'),names.index(side+'_ankle')
        sampled = transport_sides(sampled,unit(source[:,b]-source[:,a]),
                                  unit(points[:,b]-points[:,a]),candidate_frame[:,0])
    return knee_support_region(points,names,joint,
        lengths=evidence['_materialSegmentLengths'][side],side_axes=sampled,body_axes=body_sampled)


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


def _stationary_geometry_contact_masks(
    evidence, names, active, anchor_ids, frame_times, frame_positions=None,
):
    """Add derived ankle stationarity only when a pinned toe has timed full-sole support.

    The resulting mask is used only for physical geometry validation. It does
    not add XYZ pins or change the source contact anchor mask.
    """
    stationary = np.asarray(active, dtype=bool).copy()
    identities = np.asarray(anchor_ids, dtype=object).copy()
    source_count = len(frame_times) if frame_times is not None else 0
    if source_count <= 0:
        return stationary, identities
    from .contact_constraints import fit_frame_full_sole_masks
    full_sole_by_side = fit_frame_full_sole_masks(
        evidence, frame_times, source_count)
    if frame_positions is None:
        if len(stationary) != source_count:
            return stationary, identities
        positions = np.arange(source_count, dtype=float)
    else:
        positions = np.asarray(frame_positions, dtype=float)
        if positions.shape != (len(stationary),) or not np.isfinite(positions).all():
            return stationary, identities
        if (evidence.get('_materialLoopable') is True and source_count > 0):
            positions = np.mod(positions, source_count)
        else:
            positions = np.clip(positions, 0., max(0, source_count - 1))
    first = np.floor(positions).astype(int)
    last = np.ceil(positions).astype(int)
    if evidence.get('_materialLoopable') is True:
        last %= source_count
    else:
        last = np.clip(last, 0, source_count - 1)
    for side in ('left', 'right'):
        ankle_name, toe_name = f'{side}_ankle', f'{side}_foot'
        if ankle_name not in names or toe_name not in names:
            continue
        full_sole = np.asarray(full_sole_by_side.get(side), dtype=bool)
        if full_sole.shape != (source_count,):
            continue
        toe = names.index(toe_name)
        ankle = names.index(ankle_name)
        physical_sole = full_sole[first] & full_sole[last]
        derived = physical_sole & stationary[:, toe] & ~stationary[:, ankle]
        stationary[derived, ankle] = True
        identities[derived, ankle] = identities[derived, toe]
    return stationary, identities


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


def validate_support_geometry(payload, points=None, names=None, *, frame_positions=None,
                              evidence_override=None, native_side_axes=None):
    from .material_region_support import native_region_geometry
    material = native_region_geometry(payload, points=points, cursors=frame_positions)
    skeletal = _validate_skeletal_support_geometry(
        payload, points, names, frame_positions=frame_positions,
        evidence_override=evidence_override, native_side_axes=native_side_axes)
    if not material['required']:
        return skeletal
    return {**skeletal, 'required': True,
            'passed': bool(skeletal['passed'] and material['passed']),
            'materialRegionGeometry': material,
            'rejectionReasons': list(skeletal.get('rejectionReasons', [])) + material['rejectionReasons']}


def _validate_skeletal_support_geometry(payload, points=None, names=None, *, frame_positions=None,
                                        evidence_override=None, native_side_axes=None):
    from .body_support_observation import materialize_stationary_sole_support
    materialized = materialize_stationary_sole_support(payload)
    evidence = {
        **support_evidence(payload, materialized=materialized),
        **(evidence_override if isinstance(evidence_override, dict) else {}),
        '_materialFinalValidation': True,
    }
    names = names or payload.get('jointNames', [])
    body_surface = {'required': False, 'passed': True}
    if evidence.get('bodySurfaceContacts') or evidence.get('_bodySurfaceContactErrors'):
        if points is None:
            try:
                points = np.array([[frame['joints'][name] for name in names]
                                   for frame in payload['frames']], dtype=float)
            except (KeyError, TypeError, ValueError):
                return {'required': True, 'passed': False, 'policyVersion': POLICY_VERSION,
                        'rejectionReasons': ['body_surface_contact_geometry_unavailable']}
        points = np.asarray(points, dtype=float)
        if (points.ndim != 3 or points.shape[1:] != (len(names), 3)
                or not np.isfinite(points).all()):
            return {'required': True, 'passed': False, 'policyVersion': POLICY_VERSION,
                    'rejectionReasons': ['body_surface_contact_geometry_unavailable']}
        body_surface = _body_surface_contact_validation(
            points, names, evidence, frame_positions=frame_positions)
        if not body_surface['passed']:
            return {**body_surface, 'policyVersion': POLICY_VERSION}
    readiness = support_contact_readiness(payload, evidence=materialized)
    if not readiness['passed']:
        return {**readiness, 'policyVersion': POLICY_VERSION}
    if evidence.get('_bodySurfaceOnlyRequired'):
        return {**body_surface, 'policyVersion': POLICY_VERSION,
                'sourceContactReadiness': readiness}
    if not evidence.get('required'):
        if body_surface.get('required'):
            return {**body_surface, 'policyVersion': POLICY_VERSION}
        return {'required': False, 'passed': True, 'policyVersion': POLICY_VERSION,
                'sourceContactReadiness': readiness}
    if evidence.get('status') != 'confirmed':
        return {'required': True, 'passed': False, 'policyVersion': POLICY_VERSION,
                'rejectionReasons': ['supported_body_evidence_unresolved']}
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
    if (len(points) == len(payload.get('frames', []))
            and (frame_positions is None or np.array_equal(frame_positions, np.arange(len(points))))):
        evidence = candidate_material_evidence(points, names, evidence)
    active, anchor_ids = support_contact_masks(
        evidence, names, len(points), frame_positions=frame_positions)
    source_frames = payload.get('frames') or []
    source_times = [
        frame.get('sourceTimeSec') if isinstance(frame, dict) else None
        for frame in source_frames
    ]
    stationary_active, stationary_anchor_ids = (
        _stationary_geometry_contact_masks(
            evidence, names, active, anchor_ids, source_times,
            frame_positions=frame_positions,
        )
    )
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
    missing_pitch_sides = sorted(active_sole_sides.intersection(
        _missing_material_sole_pitch_sides(
            evidence, names, len(points), frame_positions, full_sole_active)))
    if missing_pitch_sides:
        return {'required': True, 'passed': False, 'policyVersion': POLICY_VERSION,
                'unresolvedSides': missing_pitch_sides,
                'rejectionReasons': ['supported_material_sole_pitch_unavailable']}
    stationary = [name for name in evidence.get('stationaryJoints', []) if name in names]
    unresolved = [name for name in stationary
                  if not np.any(stationary_active[:, names.index(name)])]
    if unresolved:
        return {'required': True, 'passed': False, 'policyVersion': POLICY_VERSION,
                'rejectionReasons': ['support_contact_timing_unresolved'],
                'unresolvedJoints': unresolved}
    drift = 0.
    for name in stationary:
        joint = names.index(name)
        indexes = np.flatnonzero(stationary_active[:, joint])
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
                         (stationary_anchor_ids[previous, joint] is not None and
                          stationary_anchor_ids[current, joint] !=
                          stationary_anchor_ids[previous, joint]))
            if split:
                groups.append(indexes[run_start:offset])
                run_start = offset
        for episode in groups:
            drift = max(drift, float(np.linalg.norm(
                np.ptp(points[episode, joint], axis=0))))
    if native_side_axes is None and 'materialFrames' in (payload.get('fixedRig') or {}):
        from .foot_geometry import _sample_material_foot_geometry
        cursors = np.arange(len(points)) if frame_positions is None else frame_positions
        native_side_axes = {side: frame['lateral'] for side, frame in
                            _sample_material_foot_geometry(payload, cursors, points).items()}
    geometry = float(np.max(np.abs(geometry_errors(
        points, names, evidence, frame_positions=frame_positions,
        native_side_axes=native_side_axes)), initial=0.))
    reasons = []
    if drift > TOLERANCE_METERS:
        reasons.append('supported_body_moves')
    if geometry > TOLERANCE_METERS:
        reasons.append('support_surface_geometry_mismatch')
    active_counts = {name: int(stationary_active[:, names.index(name)].sum())
                     for name in stationary}
    return {'required': True, 'passed': not reasons and body_surface.get('passed', True), 'policyVersion': POLICY_VERSION,
            'maximumStationaryJointRangeMeters': drift,
            'maximumSurfaceErrorMeters': geometry,
            'toleranceMeters': TOLERANCE_METERS, 'rejectionReasons': reasons,
            'activeContactFrameCountByJoint': active_counts,
            'bodySurfaceContactGeometry': body_surface}


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
    for joint in evidence.get('_floorMaterialContacts', []):
        side = joint.split('_')[0]
        rows.append(joint_dependencies(rig, ['pelvis','neck','left_hip','right_hip',side+'_knee',side+'_ankle']))
    body_surface_rows = []
    for contact in evidence.get('bodySurfaceContacts') or []:
        if contact.get('contactMode') == 'rolling':
            body_surface_rows.append(joint_dependencies(rig, rig.names))
            continue
        body_surface_rows.extend([joint_dependencies(rig, rig.names)]
                                 * _body_surface_contact_columns(contact))
    body_surface_rows.extend([joint_dependencies(rig, rig.names)]
                             * len(evidence.get('_bodySurfaceContactErrors') or []))
    rows.extend(body_surface_rows)
    native_tracks = evidence.get('_nativeFootMaterialTracks')
    if isinstance(native_tracks, dict) and native_tracks.get('version') == 2:
        for side in ('left', 'right'):
            track = native_tracks.get(side) or {}
            for episode in track.get('episodes') or []:
                rows.extend([joint_dependencies(rig, rig.names)]
                * ((2 if episode.get('mode') == 'verticalOnly' else 4)
                   + (6 if episode.get('regionRole') == 'full_sole' else 0)))
        if evidence.get('_nativeFootMirrorRequired') is True:
            rows.extend([joint_dependencies(rig, rig.names)] * 6)
    rows.extend([joint_dependencies(rig, rig.names)]
                * len(evidence.get('_nativeFootMaterialErrors') or []))
    return np.asarray(rows).reshape(-1, rig.width)


def _resolved_sole_contact_side(contact, names):
    """Return the side only for a complete side-qualified sole chain."""
    joints = contact.get('joints') or []
    if len(joints) != 3 or any(joint not in names for joint in joints):
        return None
    side = str(joints[1]).split('_', 1)[0]
    if (side not in {'left', 'right'} or str(joints[0]) != f'{side}_knee'
            or str(joints[1]) != f'{side}_ankle'
            or str(joints[2]) != f'{side}_foot'):
        return None
    return side


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
    resolved_contacts = []
    for contact in contacts:
        side = _resolved_sole_contact_side(contact, names)
        if side is None:
            continue
        ankle, toe = contact['joints'][1], contact['joints'][2]
        if np.any(full_sole_active[:, names.index(ankle)]
                  & full_sole_active[:, names.index(toe)]):
            resolved_contacts.append((contact, side))
    relevant_sides = {side for _, side in resolved_contacts}
    sole_sides = {str(contact['joints'][1]).split('_', 1)[0] for contact in contacts}
    unresolved_sides = sorted(unresolved_timed_sides.intersection(sole_sides))
    if unresolved_sides:
        return {'required': True, 'passed': False,
                'reason': 'sole_contact_timing_unresolved',
                'unresolvedSides': unresolved_sides}
    if not relevant_sides:
        # Timed toe-only, heel-only, airborne, or unknown intervals do not
        # authorize a whole-foot material orientation constraint.
        # A full-sole clock or legacy whole-clip sole plane without a complete
        # side-qualified foot chain is unresolved geometry, not a pass.
        timed_full_sole = any(
            str(contact.get('contactState') or '').casefold() == 'full_sole'
            for contact in motion_support_contacts(evidence))
        if np.any(full_sole_active) or timed_full_sole:
            return {'required': True, 'passed': False,
                    'reason': 'sole_orientation_unavailable'}
        return {'required': False, 'passed': True, 'reason': 'no_active_full_sole_contact'}
    if relevant_sides.intersection(_missing_material_sole_pitch_sides(
            evidence, names, len(points), sample_positions, full_sole_active)):
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
        evaluated_sides = set()
        for contact, side_name in resolved_contacts:
            _, ankle, toe = contact['joints']
            if side_name not in geometry:
                continue
            evaluated_sides.add(side_name)
            try:
                rest_pitch = float(pitches[side_name])
            except (KeyError, TypeError, ValueError, OverflowError):
                rest_pitch = None
            normal = np.asarray(contact['normal'], dtype=float)
            normal /= np.linalg.norm(normal)
            ankle_index = names.index(ankle)
            toe_index = names.index(toe)
            material = geometry[side_name]
            for frame_index in range(len(points)):
                if not (full_sole_active[frame_index, ankle_index]
                        and full_sole_active[frame_index, toe_index]):
                    continue
                if _native_fullsole_coverage(
                        evidence, side_name, len(points), sample_positions)[frame_index]:
                    continue
                if rest_pitch is None:
                    raise ValueError('Legacy full-sole contact has no calibrated pitch')
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
        unresolved_geometry_sides = sorted(relevant_sides - evaluated_sides)
        if unresolved_geometry_sides:
            return {'required': True, 'passed': False,
                    'reason': 'sole_orientation_unavailable',
                    'unresolvedSides': unresolved_geometry_sides}
        native_errors, native_errors_detail = _native_foot_material_contact_residuals(
            points, names, evidence, frame_positions=sample_positions)
        if native_errors_detail:
            raise ValueError('Native sole plane is unavailable')
        if native_errors.shape[1]:
            maximum = max(maximum, float(np.max(np.abs(native_errors), initial=0.)))
    except (KeyError, TypeError, ValueError):
        return {'required': True, 'passed': False, 'reason': 'sole_orientation_unavailable'}
    return {'required': True, 'passed': maximum <= TOLERANCE_METERS,
            'maximumOrientationErrorMeters': maximum}


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


def _stationary_tangent_projectors(rig, evidence):
    projectors = {}
    for name in evidence.get('stationaryJoints', []):
        normals = [group['normal'] for group in evidence.get('coplanarGroups', [])
                   if name in group.get('joints', [])]
        if name in evidence.get('_floorMaterialContacts', []):
            normals.append([0., 1., 0.])
        if normals:
            normals = np.asarray(normals, dtype=float)
            normals /= np.linalg.norm(normals, axis=1, keepdims=True)
            projectors[rig.names.index(name)] = np.eye(3)-np.linalg.pinv(normals)@normals
    return projectors


def _single_pose_shoe_constraint(rig, payload, pose, source_frame, check_budget):
    """Evaluate the native shoe geometry of an actual calibration pose."""
    if not payload or not any({side+'_ankle', side+'_foot'}.issubset(rig.names)
                              for side in ('left', 'right')):
        return None
    from copy import deepcopy
    from .shoe_floor import ShoeFloorConstraint
    static_payload = deepcopy(payload)
    static_payload['frames'] = [deepcopy(payload['frames'][source_frame])]
    static_payload['frameCount'] = 1
    return ShoeFloorConstraint(rig, static_payload, frame_positions=np.array([0]),
                               context=pose[None], check_budget=check_budget,
                               material_frame_positions=np.array([source_frame]))


def validate_static_support_pose(rig, points, evidence, pose, calibration):
    """A cached pose must clear the current physical owner, not its old report."""
    from .controlled_motion import PLAYBACK_FLOOR_LIMIT_METERS
    from .rig_playback import RIG_NUMERICAL_CONSISTENCY_METERS
    from .material_floor import MaterialFloorConstraint
    if _missing_material_sole_pitch_sides(
            evidence, rig.names, len(points),
            full_sole_active=full_sole_contact_masks(evidence, rig.names, len(points))):
        return {'passed': False, 'reason': 'supported_material_sole_pitch_unavailable'}
    try:
        coordinates = np.asarray(calibration['coordinates'], dtype=float).reshape(1, rig.width)
        decoded = rig.decode(coordinates)
        mismatch = float(np.max(np.abs(decoded[0]-np.asarray(pose)), initial=0.))
        reference = np.asarray(calibration.get('referenceCoordinates', coordinates[0])).reshape(1, rig.width)
        closest = int(np.argmin(np.sum((rig.initial-reference)**2, axis=1)))
        evidence = {**evidence, '_materialCalibrationPosition': closest}
        material = (MaterialFloorConstraint(rig, evidence, frame_positions=np.array([closest]))
                    if evidence.get('_floorMaterialContacts') else None)
        local = {**evidence, '_floorMaterialContacts': []} if material is not None else evidence
        native_axes = _native_side_axes_for_coordinates(
            rig, coordinates, local, [closest])
        errors = geometry_errors(decoded, rig.names, local, frame_positions=[closest],
                                 native_side_axes=native_axes).ravel()
        if material is not None:
            errors = np.r_[errors, material.residual(coordinates.ravel(), bounded=False, check=False)]
        shoes = _single_pose_shoe_constraint(rig, evidence.get('_materialShoePayload'),
                                             decoded[0], closest, None)
        shoe_error = float(max(0., -shoes.heights(coordinates.ravel(), check=False).min())) if shoes else 0.
        maximum = float(np.max(np.abs(errors), initial=0.))
        passed = (np.isfinite(decoded).all() and mismatch <= RIG_NUMERICAL_CONSISTENCY_METERS
                  and maximum < TOLERANCE_METERS*.5 and shoe_error <= PLAYBACK_FLOOR_LIMIT_METERS)
        return {'passed': bool(passed), 'surfaceErrorMeters': maximum,
                'shoeSurfacePenetrationMeters': shoe_error, 'poseCoordinateMismatchMeters': mismatch}
    except (KeyError, ValueError, TypeError):
        return {'passed': False, 'reason': 'support_calibration_coordinates_unavailable'}


def calibrate_support_pose(rig, points, evidence, alignment_reference=None, *, articulation_reference=None,
                           canonical_execution=None, deadline=None,
                           source_marker_constraint=None, native_foot_tracks=None):
    """Find one feasible fixed-rig support pose within the caller's support budget."""
    from time import monotonic
    from scipy.optimize import least_squares
    from .physical_validation import anatomical_structure_residuals, collision_clearances, body_scale
    from .controlled_motion import (ANATOMY_FIT_MARGIN, SUPPORT_HEAD_ARTICULATION_FIT_WEIGHT,
                                    SUPPORT_REFERENCE_CONTACT_LIMIT_METERS, PLAYBACK_FLOOR_LIMIT_METERS)

    if evidence.get('status') != 'confirmed' or not evidence_is_complete(evidence, rig.names):
        return None, {'passed': False, 'reason': 'supported_body_evidence_unresolved'}
    missing_pitch_sides = _missing_material_sole_pitch_sides(
        evidence, rig.names, len(points),
        full_sole_active=full_sole_contact_masks(evidence, rig.names, len(points)))
    if missing_pitch_sides:
        return None, {'passed': False, 'reason': 'supported_material_sole_pitch_unavailable',
                      'unresolvedSides': missing_pitch_sides}
    indices = [rig.names.index(n) for n in evidence.get('stationaryJoints', [])]
    target = np.median(points, axis=0)
    closest = int(np.argmin(np.sum((points[:, indices]-target[indices])**2, axis=(1, 2))))
    initial = rig.initial[closest].copy()
    reference_pose = rig.decode(initial[None, :])[0]
    # A stationary observation owns the support's tangential layout. The
    # calibration may place its normal height, but a single optimized pose
    # must not invent a new horizontal stance for the complete trajectory.
    tangent_projectors = _stationary_tangent_projectors(rig, evidence)

    def tangent_errors(candidate):
        return np.asarray([projector @ (candidate[0, index] - reference_pose[index])
                           for index, projector in tangent_projectors.items()]).reshape(-1, 3)

    evidence = {**evidence, '_materialCalibrationPosition': closest}
    head_reference = (points if articulation_reference is None else articulation_reference)[closest:closest+1]
    scale = body_scale(points, rig.names)
    from .support_alignment import (alignment_features, alignment_constraint_errors,
                                    alignment_dependencies, policy_alignment_errors, policy_alignment_dependencies,
                                    POLICY_ALIGNMENT_FIT_WEIGHT)
    source_alignment = np.median(alignment_features(
        points if alignment_reference is None else alignment_reference, rig.names, evidence), axis=0, keepdims=True)
    def check_budget():
        if deadline is not None and monotonic() >= deadline:
            raise TimeoutError
    from .material_floor import MaterialFloorConstraint
    material = (MaterialFloorConstraint(rig, evidence, frame_positions=np.array([closest]),
                                       check_budget=check_budget)
                if evidence.get('_floorMaterialContacts') else None)
    shoes = _single_pose_shoe_constraint(rig, evidence.get('_materialShoePayload'),
                                         reference_pose, closest, check_budget)
    local_geometry = {**evidence, '_floorMaterialContacts': []} if material is not None else evidence
    marker_constraint = None
    marker_observations = (source_marker_constraint or {}).get(
        'sourceFootNativeMarkerVectorObservations') or []
    if marker_observations and isinstance(native_foot_tracks, dict):
        # A static calibration row may only use observations whose source
        # interpolation interval actually covers this calibration frame. Do
        # not pull another phase (or another side) into the one-pose solve.
        selected = _native_marker_observations_at_frame(marker_observations, closest)
        if selected:
            marker_constraint = {
                **source_marker_constraint,
                'sourceFootNativeMarkerVectorObservations': [{
                    **row, 'leftFrame': 0, 'rightFrame': 0, 'alpha': 0.,
                } for row in selected],
            }

    def native_marker_rows(values, candidate):
        if marker_constraint is None:
            return np.empty(0, dtype=float)
        marker_evidence = {**local_geometry, '_nativeFootMaterialTracks': native_foot_tracks}
        axes = _native_side_axes_for_coordinates(
            rig, values, marker_evidence, [closest]) or {}
        from .controlled_motion import _source_native_marker_vector_fit_rows
        return _source_native_marker_vector_fit_rows(
            candidate, marker_constraint, axes)

    best_values, best_cost = initial.copy(), float('inf')

    def local_residual(values):
        check_budget()
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
        errors = np.r_[(candidate[0]-target).ravel(),
                     200.*alignment_constraint_errors(candidate, source_alignment, rig.names, evidence).ravel(),
                     POLICY_ALIGNMENT_FIT_WEIGHT*policy_alignment_errors(
                         candidate, rig.names, canonical_execution).ravel(),
                     1000.*geometry_errors(
                         candidate, rig.names, local_geometry,
                         frame_positions=[closest],
                         native_side_axes=_native_side_axes_for_coordinates(
                             rig, values, local_geometry, [closest])).ravel(),
                     1000.*np.asarray(anchor_errors),
                     1000.*tangent_errors(candidate).ravel(),
                     1000.*anatomical_structure_residuals(
                         candidate, rig.names, pose_only=True, margin=ANATOMY_FIT_MARGIN)[0].ravel(),
                     SUPPORT_HEAD_ARTICULATION_FIT_WEIGHT*_head_articulation_residual(
                         candidate, head_reference, rig.names).ravel(),
                     1000.*np.minimum(collision_clearances(candidate, rig.names, scale)[0]-.003*scale, 0.).ravel(),
                     .001*(values-initial), native_marker_rows(values, candidate)]
        return errors

    def residual(values):
        nonlocal best_values, best_cost
        errors = local_residual(values)
        if material is not None:
            errors = np.r_[errors, 1000. * material.residual(values, bounded=False)]
        if shoes is not None:
            errors = np.r_[errors, 1000.*shoes.residual(values)]
        cost = float(errors @ errors)
        if cost < best_cost:
            best_values, best_cost = values.copy(), cost
        return errors

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
    geometry_rows = np.atleast_2d(geometry_dependencies(rig, local_geometry))
    rows.extend(alignment_rows)
    rows.extend(policy_alignment_dependencies(rig, canonical_execution))
    rows.extend(geometry_rows)
    for group in evidence.get('coplanarGroups', []):
        anchor = group.get('anchorJoint', group['joints'][0])
        rows.append(np.asarray(joint_dependencies(rig, [anchor])))
    for index in tangent_projectors:
        rows.append(np.tile(joint_dependencies(rig, [rig.names[index]]), (3, 1)))
    structure_rows = np.atleast_2d(anatomical_structure_dependencies(rig, initial_points, rig.names))
    rows.extend(structure_rows)
    rows.extend(_head_articulation_dependencies(rig, initial_points))
    for _label, first, second, _ratio, _adjacent in collision_specs(rig.names):
        rows.append(np.asarray(joint_dependencies(rig, [*first, *second])))
    rows.append(np.eye(rig.width))
    if marker_constraint is not None:
        marker_sides = sorted({row['motionSide'] for row in
                               marker_constraint['sourceFootNativeMarkerVectorObservations']})
        for marker_side in marker_sides:
            marker_dependencies = np.asarray(joint_dependencies(
                rig, [f'{marker_side}_foot']), dtype=bool)
            rows.extend((marker_dependencies, marker_dependencies))
    pattern = np.asarray(np.vstack([
        np.atleast_2d(row) if np.asarray(row).ndim > 0 else np.zeros((0, rig.width))
        for row in rows
    ]), dtype=bool)
    from scipy.sparse import csr_matrix
    solver_options = {'jac_sparsity': csr_matrix(pattern)}
    if material is not None or shoes is not None:
        from scipy.optimize._numdiff import approx_derivative
        from scipy.sparse import vstack
        def jacobian(values):
            check_budget()
            local = approx_derivative(local_residual, values, method='2-point', sparsity=csr_matrix(pattern))
            tails = ([1000.*material.jacobian(values, bounded=False)] if material is not None else [])
            if shoes is not None:
                tails.append(1000.*shoes.jacobian(values))
            return vstack([local, *tails], format='csr')
        solver_options = {'jac': jacobian}
    def raw_geometry(values):
        candidate = rig.decode(values[None, :])
        raw = geometry_errors(
            candidate, rig.names, local_geometry, frame_positions=[closest],
            native_side_axes=_native_side_axes_for_coordinates(
                rig, values, local_geometry, [closest])).ravel()
        if material is not None:
            raw = np.r_[raw, material.residual(values, bounded=False, check=False)]
        if shoes is not None:
            raw = np.r_[raw, shoes.residual(values, check=False)]
        return raw
    # Forty evaluations remain the fast path; an improving unfinished solve
    # can continue under the caller's existing support deadline.
    current, evaluations, continuations = initial.copy(), 0, 0
    native_point_reselection_attempted = False
    stop_reason = 'evaluation_limit'
    while True:
        try:
            before = residual(current)
            cost_before = .5 * float(before @ before)
            solved = least_squares(residual, current, **solver_options,
                                   max_nfev=40, x_scale='jac', ftol=1e-6, xtol=1e-6)
        except TimeoutError:
            current, stop_reason = best_values.copy(), 'deadline'
            break
        current = solved.x.copy()
        evaluations += solved.nfev
        pose = rig.decode(current[None, :])[0]
        error = float(np.max(np.abs(raw_geometry(current)), initial=0.))
        shoe_error = (float(max(0., -shoes.heights(current, check=False).min())) if shoes is not None else 0.)
        tangent_error = float(np.max(np.linalg.norm(tangent_errors(pose[None]), axis=-1), initial=0.))
        if (error < TOLERANCE_METERS*.5 and tangent_error < SUPPORT_REFERENCE_CONTACT_LIMIT_METERS
                and shoe_error <= PLAYBACK_FLOOR_LIMIT_METERS):
            stop_reason = 'passed'
            break
        # The first binding is selected from the source-pose shoe mesh. A
        # calibration can legitimately correct its orientation enough that a
        # different point in the same observed region becomes the support-facing
        # material patch. Reselect once, at this corrected fixed pose, then use
        # only the remaining existing deadline for the same calibration.
        tracks = local_geometry.get('_nativeFootMaterialTracks')
        if (not native_point_reselection_attempted
                and isinstance(tracks, dict) and tracks.get('version') == 2
                and solved.status != 0
                and deadline is not None and monotonic() < deadline):
            native_point_reselection_attempted = True
            axes = _native_side_axes_for_coordinates(rig, current, local_geometry, [closest]) or {}
            from .contact_interpolation import reselect_native_material_episode_at_pose
            changed = False
            for side in ('left', 'right'):
                if side not in axes:
                    continue
                tracks, side_changed = reselect_native_material_episode_at_pose(
                    tracks, side, rig.names, pose, axes[side][0],
                    evidence.get('nativeFootGeometry'), evidence.get('_nativeFootScale'), closest)
                changed |= side_changed
            if changed:
                local_geometry['_nativeFootMaterialTracks'] = tracks
                # The objective changed with the material binding. Discard the
                # previous objective's fallback candidate and seed the new one
                # at the current corrected pose before continuing.
                best_values, best_cost = current.copy(), float('inf')
                residual(current)
                continuations += 1
                continue
        if deadline is None:
            break
        if solved.status != 0:
            stop_reason = 'converged'
            break
        if solved.cost >= cost_before * (1. - 1e-6):
            stop_reason = 'objective_stalled'
            break
        continuations += 1
    pose = rig.decode(current[None, :])[0]
    error = float(np.max(np.abs(raw_geometry(current)), initial=0.))
    tangent_error = float(np.max(np.linalg.norm(tangent_errors(pose[None]), axis=-1), initial=0.))
    shoe_error = (float(max(0., -shoes.heights(current, check=False).min())) if shoes is not None else 0.)
    passed = (error < TOLERANCE_METERS*.5 and tangent_error < SUPPORT_REFERENCE_CONTACT_LIMIT_METERS
              and shoe_error <= PLAYBACK_FLOOR_LIMIT_METERS)
    return (pose if passed else None), {
        'passed': passed, 'surfaceErrorMeters': error,
        'stationaryTangentErrorMeters': tangent_error,
        'shoeSurfacePenetrationMeters': shoe_error,
        'evaluations': evaluations, 'coordinates': current.tolist(),
        'continuations': continuations, 'stopReason': stop_reason,
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
    from .body_support_observation import BODY_SUPPORT_ANCHORS
    stationary = set(evidence.get('stationaryJoints', ()))
    body_frame_supported = set(BODY_SUPPORT_ANCHORS).issubset(stationary)
    corrected_ankles = {group['joints'][1] for group in evidence.get('soleContacts', [])}
    result = []
    for label, a, b, c, _ in ARTICULATIONS:
        if label in corrected_ankles or not {a, b, c}.issubset(names):
            continue
        indices = [names.index(n) for n in (a, b, c)]
        track = angles(*(points[:, j] for j in indices))
        if np.ptp(track) > np.deg2rad(20.):
            if (support_corrected_points is not None and body_frame_supported
                    and b in BODY_SUPPORT_ANCHORS
                    and c not in stationary and c not in constraint_endpoints):
                # A supported body frame owns this proximal body axis. Keep
                # immutable free limb vectors; held knees/ankles retain raw ROM.
                corrected = np.asarray(support_corrected_points, dtype=float)
                body_axis = corrected[:, indices[0]] - corrected[:, indices[1]]
                free_vector = points[:, indices[2]] - points[:, indices[1]]
                track = angles(body_axis, np.zeros_like(body_axis), free_vector)
            result.append((label, indices, track))
    return result


def _support_foot_p95_rows(rig, coordinates, reference, direction_authority=None,
                           heading_authority=None, *, jacobian=False, bounded=True):
    """Fit the same qualified scalar direction guards used at the handoff.

    ``heading_authority`` optionally removes heading rows whose yaw is owned by
    observed camera rays; pitch rows keep their existing qualified mask.
    """
    from .controlled_motion import support_foot_direction_changes, ARTICULATIONS
    from scipy.sparse import csr_matrix
    points = rig.decode(coordinates)
    changes = support_foot_direction_changes(
        reference, points, rig.names, direction_authority, heading_authority)
    rows, selected, residuals = [], [], []
    for side in ('left', 'right'):
        tolerance = np.deg2rad(next(value for label, _, _, _, value in ARTICULATIONS
                                   if label == side+'_ankle'))
        item = changes.get(side)
        for feature in ('headingDeltaRadians', 'pitchDeltaRadians'):
            mask_key = ('headingQualifiedMask' if feature == 'headingDeltaRadians'
                        else 'qualifiedMask')
            active = np.flatnonzero(item[mask_key]) if item is not None else np.array([], dtype=int)
            if not len(active):
                residuals.append(0. if bounded else -tolerance)
                selected.append([]); rows.append((side, feature)); continue
            order = active[np.argsort(item[feature][active], kind='stable')]
            position = .95*(len(order)-1)
            first, last = int(np.floor(position)), int(np.ceil(position))
            fraction = position-first
            percentile = float(np.percentile(item[feature][active], 95))
            residuals.append(max(0., percentile-tolerance) if bounded else percentile-tolerance)
            selected.append([(order[first], 1.-fraction), (order[last], fraction)]
                            if not bounded or percentile > tolerance else [])
            rows.append((side, feature))
    if not jacobian:
        return np.asarray(residuals)
    gradients = np.zeros((len(rows), *points.shape))
    required = ('pelvis', 'left_hip', 'right_hip', 'neck',
                'left_ankle', 'left_foot', 'right_ankle', 'right_foot')
    step = np.cbrt(np.finfo(float).eps)
    for name in required:
        if name not in rig.names:
            continue
        joint = rig.names.index(name)
        for component in range(3):
            plus, minus = points.copy(), points.copy()
            plus[:, joint, component] += step
            minus[:, joint, component] -= step
            positive = support_foot_direction_changes(
                reference, plus, rig.names, direction_authority, heading_authority)
            negative = support_foot_direction_changes(
                reference, minus, rig.names, direction_authority, heading_authority)
            for row, (side, feature) in enumerate(rows):
                for frame, weight in selected[row]:
                    gradients[row, frame, joint, component] += weight * (
                        positive[side][feature][frame]-negative[side][feature][frame])/(2.*step)
    return csr_matrix(gradients.reshape(len(rows), -1)) @ rig.fk_jacobian(coordinates)


def restore_supported_foot_directions(rig, coordinates, reference, evidence, deadline, *,
                                      pinned, contact_targets, alignment_reference,
                                      anatomical_reference, equipment=None, fps=30.,
                                      ankle_excursion_masks=None, ankle_evidence_masks=None,
                                      heading_authority=None):
    """Recover strict source directions inside an already physical fixed stance."""
    from time import monotonic
    from copy import deepcopy
    from scipy.sparse import csr_matrix, vstack
    from .controlled_motion import (ARTICULATIONS, TRAJECTORY_SOLVER_FTOL,
        PLAYBACK_FLOOR_LIMIT_METERS, PLAYBACK_CONTACT_LIMIT_METERS,
        supported_reference_projection_metrics, support_initialization_articulation_regressions)
    from .physical_validation import CHEST_ATTACHMENT_MAX_ANGLE_RADIANS, body_scale
    from .trajectory_restoration import (_append_active_anatomy_metrics,
        inequality_gate_restoration_step, representable_backtracking_trials)
    from .foot_geometry import validate_material_shoes
    from .temporal_quality import transport_corrected_bone_sides

    accepted = np.asarray(coordinates, dtype=float).copy()
    authority = getattr(rig, 'source_direction_authority', None)
    def source_guard(values):
        return support_initialization_articulation_regressions(reference, rig.decode(values), rig.names,
            fps=fps, direction_authority=authority, ankle_excursion_masks=ankle_excursion_masks,
            ankle_evidence_masks=ankle_evidence_masks)
    regressions = source_guard(accepted)
    if not regressions:
        return accepted, {'attempted': False, 'passed': True, 'reason': 'not_needed'}
    if any(not str(row.get('feature', '')).endswith(('_foot_heading', '_heel_pitch')) for row in regressions):
        return accepted, {'attempted': False, 'passed': False, 'reason': 'other_source_articulation_failures'}
    payload = evidence.get('_materialShoePayload')
    if not payload:
        return accepted, {'attempted': False, 'passed': False, 'reason': 'native_geometry_context_unavailable'}

    def physical(values):
        points = rig.decode(values)
        result = supported_reference_projection_metrics(points, payload=payload, names=rig.names,
            alignment_reference=alignment_reference, anatomy_reference=anatomical_reference,
            body_support=evidence, equipment=equipment or {}, pinned=pinned, contact_targets=contact_targets)
        rendered = deepcopy(payload)
        for frame, row in zip(rendered['frames'], points):
            frame['joints'] = dict(zip(rig.names, row.tolist()))
        transport_corrected_bone_sides(payload['frames'], rendered)
        native = validate_material_shoes(rendered, points, np.arange(len(points), dtype=float),
            floor_limit=PLAYBACK_FLOOR_LIMIT_METERS, contact_limit=PLAYBACK_CONTACT_LIMIT_METERS)
        result['nativeShoes'] = native
        result['passed'] = result['passed'] and native['passed']
        return result

    baseline = physical(accepted)
    if not baseline['passed']:
        return accepted, {'attempted': False, 'passed': False, 'reason': 'physical_reference_requires_polish',
                          'physical': baseline}
    limits = np.deg2rad([next(value for label, _, _, _, value in ARTICULATIONS if label == side+'_ankle')
                        for side in ('left', 'left', 'right', 'right')])
    def metrics(values):
        points = rig.decode(values)
        fk = rig.fk_jacobian(values)
        violations = list(_support_foot_p95_rows(
            rig, values, reference, authority, heading_authority, bounded=False)/limits)
        rows = [_support_foot_p95_rows(rig, values, reference, authority, heading_authority,
                    jacobian=True, bounded=False).multiply((1./limits)[:, None])]
        def append(_name, violation, gradient):
            violations.append(violation)
            rows.append(csr_matrix(gradient.reshape(1, -1))@fk)
        _append_active_anatomy_metrics(points, rig.names, append,
            chest_attachment_limit_radians=CHEST_ATTACHMENT_MAX_ANGLE_RADIANS,
            preserve_torso_bend=True, anatomy_reference=anatomical_reference)
        return np.asarray(violations), vstack(rows, format='csr')

    maximum_trust = max(.0005, min(.006, .004*body_scale(rig.decode(accepted), rig.names)))
    trust, steps = maximum_trust, []
    while monotonic() < deadline:
        violations, jacobian = metrics(accepted)
        if np.max(violations) <= 0. and not source_guard(accepted):
            break
        proposal, step = inequality_gate_restoration_step(accepted, rig, pinned, violations, jacobian,
            numerical_margin=np.sqrt(TRAJECTORY_SOLVER_FTOL), max_point_shift_meters=trust)
        if not step.get('applied'):
            steps.append({'accepted': False, 'reason': step.get('reason')}); break
        retained = False
        for alpha, trial in representable_backtracking_trials(accepted, proposal):
            if monotonic() >= deadline:
                break
            current, _ = metrics(trial)
            if (np.any(np.maximum(current, 0.) > np.maximum(violations, 0.)+1e-10)
                    or np.linalg.norm(np.maximum(current, 0.)) >= np.linalg.norm(np.maximum(violations, 0.))-1e-12):
                continue
            candidate = physical(trial)
            if (candidate['passed'] and set(candidate['anatomy']['violations'])
                    <= set(baseline['anatomy']['violations'])):
                accepted, retained = trial, True
                steps.append({'accepted': True, 'alpha': alpha, 'sourceSignedMetrics': current[:4].tolist()})
                break
        if not retained:
            steps.append({'accepted': False, 'reason': 'no_physical_feasibility_progress'}); break
        if alpha >= .999:
            trust = min(maximum_trust, trust*1.5)
        elif alpha < .25:
            trust = max(.00025, trust*.5)
    remaining = source_guard(accepted)
    final_physical = physical(accepted)
    return accepted, {'attempted': True, 'passed': not remaining and final_physical['passed'],
                      'regressions': remaining, 'steps': steps, 'physical': final_physical}


def initialize_supported_motion(rig, original, evidence, pose, calibration, deadline, fps=30., alignment_reference=None,
                                *, pinned=None, contact_targets=None, equipment=None, max_evaluations=40,
                                articulation_reference=None, frame_positions=None, anatomy_span_targets=None,
                                canonical_execution=None, angular_reference=None):
    """Project observed articulation onto contacts without locking ancestors."""
    from time import monotonic
    from scipy.sparse import eye, kron, csr_matrix, vstack
    from .controlled_motion import (joint_dependencies, solve_trajectory, ANATOMY_FIT_MARGIN,
                                    SUPPORT_HEAD_ARTICULATION_FIT_WEIGHT, PLAYBACK_FLOOR_LIMIT_METERS)
    from .physical_validation import SOCKET_ALIGNMENT_MAX_LATERAL_RATIO
    from .physical_validation import collision_clearances, collision_specs, body_scale

    stationary = evidence['stationaryJoints']
    indices = [rig.names.index(n) for n in stationary]
    source_coordinates = rig.initial.copy()
    source_points = rig.decode(source_coordinates)
    head_reference = original if articulation_reference is None else articulation_reference
    from .anatomical_repair import repair_residuals, repair_residual_dependencies
    from .physical_validation import span_rigidity_violations
    if anatomy_span_targets is None:
        anatomy_span_targets = {label: target for label, (_, target) in
                                span_rigidity_violations(original, rig.names).items()}
    count = len(original)
    from .controlled_motion import (hinge_coordinates, source_hinge_reliability,
                                    reliable_knee_hinge_residuals, reliable_knee_hinge_dependencies)
    hinge_reference = None
    if angular_reference is not None:
        parent, bend, sine = hinge_coordinates(angular_reference, rig.names)
        reliable = source_hinge_reliability(parent, bend, sine, fps)
        positions = (np.arange(count) if frame_positions is None else
                     np.asarray(frame_positions, dtype=int))
        hinge_reference = parent[positions], bend[positions], reliable[positions]

    def hinge_rows(candidate):
        return (reliable_knee_hinge_residuals(candidate, rig.names, *hinge_reference)
                if hinge_reference is not None else np.empty((count, 0)))
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
    placement_shift = (np.mean(pose[indices]-source_points[:, indices], axis=1)
                       if indices else np.zeros((count, 3)))
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
    from .support_alignment import (alignment_features, alignment_constraint_errors, alignment_dependencies,
                                    policy_alignment_errors, policy_alignment_dependencies, POLICY_ALIGNMENT_FIT_WEIGHT)
    source_alignment = alignment_features(original if alignment_reference is None else alignment_reference, rig.names, evidence)
    def check_budget():
        from .fit_runtime import fit_should_yield_for_priority
        if fit_should_yield_for_priority() or monotonic() > deadline:
            raise TimeoutError
    from .material_floor import MaterialFloorConstraint
    material_cursors = (np.arange(len(evidence['_materialReferencePoints']), dtype=float)
                        if frame_positions is not None and evidence.get('_floorMaterialContacts') else None)
    material = (MaterialFloorConstraint(rig, evidence, frame_positions=frame_positions, cursors=material_cursors,
                                       check_budget=check_budget)
                if evidence.get('_floorMaterialContacts') else None)
    from .shoe_floor import ShoeFloorConstraint
    shoe_payload = evidence.get('_materialShoePayload')
    shoes = (ShoeFloorConstraint(rig, shoe_payload, frame_positions=frame_positions,
                                context=evidence.get('_materialReferencePoints'), check_budget=check_budget)
             if shoe_payload else None)
    entry_shoe_floor = (np.minimum(shoes.heights(source_coordinates.ravel(), check=False),
                                  -PLAYBACK_FLOOR_LIMIT_METERS) if shoes is not None else None)
    from .controlled_motion import SUPPORT_ARTICULATION_FIT_WEIGHT, support_articulation_guard_required
    foot_indices = [index for index, name in enumerate(rig.names) if name.endswith(('_ankle', '_foot'))]
    foot_contact_owned = bool(foot_indices and np.any(contact_active[:, foot_indices]))
    guard_reference = (angular_reference if frame_positions is None and angular_reference is not None
                       and len(angular_reference) == count
                       and support_articulation_guard_required(foot_contact_owned, evidence) else None)
    local_geometry = {**evidence, '_floorMaterialContacts': []} if material is not None else evidence
    best_coordinates = rig.initial.copy()
    best_cost = float('inf')
    safe_coordinates = source_coordinates.copy()
    safe_cost = float('inf')

    def local_residual(values):
        check_budget()
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
            2000.*geometry_constraint_errors(
                candidate, rig.names, local_geometry, frame_positions=frame_positions,
                native_side_axes=_native_side_axes_for_coordinates(
                    rig, coordinates, local_geometry, frame_positions)),
            # Alignment was under-weighted vs plant/contact (10 vs 2000), so
            # support init planted feet by introducing ~12 mm spine lateral
            # offset and failed support_correction_introduced_torso_deformation.
            200.*alignment_constraint_errors(candidate, source_alignment, rig.names, evidence),
            POLICY_ALIGNMENT_FIT_WEIGHT*policy_alignment_errors(candidate, rig.names, canonical_execution),
            1000.*repair_residuals(
                candidate, rig.names, anatomy_span_targets, reference=head_reference)[0],
            hinge_rows(candidate),
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
        return errors

    def residual(values):
        nonlocal best_coordinates, best_cost, safe_coordinates, safe_cost
        errors = local_residual(values)
        if material is not None:
            errors = np.r_[errors, 2000. * material.residual(values)]
        if shoes is not None:
            shoe_heights = shoes.heights(values)
            errors = np.r_[errors, 2000. * shoes.residual(values)]
        if guard_reference is not None:
            errors = np.r_[errors, SUPPORT_ARTICULATION_FIT_WEIGHT*_support_foot_p95_rows(
                rig, values.reshape(count, rig.width), guard_reference,
                getattr(rig, 'source_direction_authority', None))]
        cost = float(errors @ errors)
        if cost < best_cost:
            best_coordinates, best_cost = values.reshape(count, rig.width).copy(), cost
        if (shoes is not None and cost < safe_cost
                and np.all(shoe_heights >= entry_shoe_floor-1e-9)):
            safe_coordinates, safe_cost = values.reshape(count, rig.width).copy(), cost
        return errors

    contact_rows = [j*3+k for j in contact_indices for k in range(3)]
    grip_rows = (np.asarray([joint_dependencies(rig, equipment['endpointPair'])])
                 if equipment.get('handRelationship') == 'rigid_pair' and equipment.get('available')
                 else np.empty((0, rig.width)))
    collision_rows = [joint_dependencies(rig, [*a, *b]) for _, a, b, _, _ in collision_specs(rig.names)]
    direction_rows = np.repeat(np.asarray([joint_dependencies(rig, [rig.names[j], rig.names[parent]])
                                         for j, parent in zip(direction_children, direction_parents)]), 3, axis=0)
    frame_pattern = np.vstack([rig.dependencies, direction_rows, rig.dependencies[contact_rows], grip_rows,
        geometry_dependencies(rig, local_geometry), alignment_dependencies(rig, evidence),
        policy_alignment_dependencies(rig, canonical_execution), repair_residual_dependencies(
            rig, original, span_targets=anatomy_span_targets, reference=head_reference),
        (reliable_knee_hinge_dependencies(rig) if hinge_reference is not None else np.empty((0, rig.width))),
        _head_articulation_dependencies(rig, original), collision_rows, np.eye(rig.width)])
    pattern = kron(eye(count), csr_matrix(frame_pattern), format='csr')
    d2 = csr_matrix(abs(np.diff(np.eye(count), n=2, axis=0)))
    pattern = vstack([pattern, kron(d2, csr_matrix(rig.dependencies))], format='csr')
    solver_options = {}
    tails = [tail for tail in (material, shoes) if tail is not None]
    if tails or guard_reference is not None:
        tail_patterns = [csr_matrix(tail.shape) for tail in tails]
        if guard_reference is not None:
            tail_patterns.append(csr_matrix((4, rig.initial.size)))
        pattern = vstack([pattern, *tail_patterns], format='csr')
        def tail_jacobian(values):
            rows = [2000.*tail.jacobian(values) for tail in tails]
            if guard_reference is not None:
                rows.append(SUPPORT_ARTICULATION_FIT_WEIGHT*_support_foot_p95_rows(
                    rig, values.reshape(count, rig.width), guard_reference,
                    getattr(rig, 'source_direction_authority', None), jacobian=True))
            return vstack(rows, format='csr')
        solver_options['tail_jacobian'] = tail_jacobian
        solver_options['local_residual'] = local_residual
    if pattern.shape != (residual(rig.initial.ravel()).size, rig.initial.size):
        raise ValueError('Support projection residual and dependency shapes differ')
    try:
        solved = solve_trajectory(residual, rig.initial.ravel(), pattern, max(1, int(max_evaluations)),
                                  **solver_options)
    except TimeoutError:
        # Preserve evaluated progress for the caller's independent support gates.
        rig.initial[:] = safe_coordinates if shoes is not None else best_coordinates
        if shoes is not None:
            calibration['shoeFloorNonRegressionGuard'] = True
        raise
    calibration['projectionEvaluations'] = solved.nfev
    calibration['projectionEvaluationBudget'] = int(max_evaluations)
    rig.initial[:] = solved.x.reshape(count, rig.width)
    rig.project_neck_attachment(maximum_lateral_ratio=SOCKET_ALIGNMENT_MAX_LATERAL_RATIO-ANATOMY_FIT_MARGIN)
    if shoes is not None and np.any(
            shoes.heights(rig.initial.ravel(), check=False) < entry_shoe_floor-1e-9):
        rig.initial[:] = safe_coordinates
        calibration['shoeFloorNonRegressionGuard'] = True
    return rig.decode(rig.initial)


def repair_supported_motion_anatomy(rig, observed, evidence, pose, calibration, deadline, *,
                                    pinned, contact_targets, fps=30., alignment_reference=None,
                                    articulation_reference=None, equipment=None, canonical_execution=None,
                                    angular_reference=None):
    """Polish failing anatomy frames while retaining the same coupled support constraints."""
    from copy import copy
    from time import monotonic
    from .anatomical_repair import repair_residuals
    from .physical_validation import span_rigidity_violations
    reference = observed if articulation_reference is None else articulation_reference
    span_targets = {label: target for label, (_, target) in
                    span_rigidity_violations(observed, rig.names).items()}
    errors, labels = repair_residuals(observed, rig.names, span_targets, reference=reference)
    from .physical_validation import hinge_direction_events
    hinge_events = (hinge_direction_events(observed, rig.names, angular_reference, fps=fps)
                    if angular_reference is not None else [])
    bad = np.union1d(np.flatnonzero(np.any(errors > 1e-6, axis=1)),
                     [event['frameIndex'] for event in hinge_events]).astype(int)
    active_labels = [labels[index] for index in np.flatnonzero(errors.max(axis=0) > 1e-6)]
    if (not hinge_events and active_labels == ['repair_head_articulation_distortion:head']
            and 'head' not in evidence.get('stationaryJoints', [])
            and not np.any(pinned[:, rig.names.index('head')])):
        # A free head leaf cannot move the support frame or its contacts.
        from .anatomical_repair import repair_rig_anatomy
        return repair_rig_anatomy(rig, observed, deadline=deadline, reference=reference)
    repaired = 0
    attempted = 0
    timed_out = 0
    working_evidence = candidate_material_evidence(observed.copy(), rig.names, evidence)
    for frame in bad:
        if monotonic() >= deadline:
            break
        local = copy(rig)
        local.initial = rig.initial[frame:frame + 1].copy()
        attempted += 1
        # These are actual indices in the retained source material tracks, not a new clock.
        try:
            initialize_supported_motion(
                local, observed[frame:frame + 1], working_evidence, pose, {}, deadline, fps=fps,
                alignment_reference=(None if alignment_reference is None else
                                     alignment_reference[frame:frame + 1]),
                pinned=pinned[frame:frame + 1], contact_targets=contact_targets[frame:frame + 1],
                equipment=equipment,
                articulation_reference=reference[frame:frame + 1],
                angular_reference=angular_reference,
                frame_positions=np.array([frame], dtype=float), anatomy_span_targets=span_targets,
                canonical_execution=canonical_execution)
        except TimeoutError:
            # An interrupted soft solve can trade valid anatomy for contact cost.
            timed_out += 1
            continue
        changed = not np.array_equal(rig.initial[frame], local.initial[0])
        rig.initial[frame] = local.initial[0]
        if working_evidence.get('_floorMaterialContacts'):
            working_evidence['_materialReferencePoints'][frame] = local.decode(local.initial)[0]
        repaired += int(changed)
    result = rig.decode(rig.initial)
    remaining, _ = repair_residuals(result, rig.names, span_targets, reference=reference)
    remaining_hinges = (hinge_direction_events(result, rig.names, angular_reference, fps=fps)
                        if angular_reference is not None else [])
    return result, {'strategy': 'coupled_supported_anatomy_projection',
                    'passed': not bool(np.any(remaining > 1e-6)) and not remaining_hinges,
                    'sourceHingeEvents': hinge_events, 'remainingHingeEvents': remaining_hinges,
                    'projectedFrameCount': repaired,
                    'attemptedFrameCount': attempted,
                    'timedOutFrameCount': timed_out,
                    'sourceViolations': [labels[i] for i in np.flatnonzero(errors.max(axis=0) > 1e-6)],
                    'remainingViolations': [labels[i] for i in np.flatnonzero(remaining.max(axis=0) > 1e-6)],
                    'maximumCorrectionMeters': float(np.linalg.norm(result-observed, axis=2).max())}
