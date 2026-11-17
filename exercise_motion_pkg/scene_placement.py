"""Constant presentation placement of a finished rig, without changing articulation."""
from copy import deepcopy

import numpy as np
from scipy.spatial.transform import Rotation

from .physical_validation import angles
from .sequence_stabilization import contact_mask, pose_digest
from .temporal_quality import refresh_motion_bounds


def normalize_scene_placement(payload, *, placement_override=None):
    """Center once; infer a modest upright offset only from quiet extended stances.

    A standing reference is a presentation convention, not a gravity estimate.
    An explicit floor or elevated support takes precedence over that convention.
    Never use a per-frame upright constraint: bends, jumps and travel must survive.
    """
    if (placement_override is None
            and payload.get('scenePlacement', {}).get('version') == 1):
        return payload
    if not payload.get('fixedRig') or not payload.get('frames'):
        return payload
    names = payload['jointNames']
    points = np.array([[f['joints'][n] for n in names] for f in payload['frames']])
    def joint(name):
        return points[:, names.index(name)]
    if placement_override is None:
        rotation = Rotation.identity()
        reference_count = 0
        reason = 'existing_floor_orientation_preserved'
        required = ['neck', 'pelvis'] + [s+'_'+j for s in ('left', 'right')
                                       for j in ('hip', 'knee', 'ankle', 'foot')]
        if (payload.get('renderFloorY') is None and not payload.get('elevatedSupportSurfaces')
                and all(n in names for n in required)):
            pinned = contact_mask(payload, names, len(points))
            if pinned is None:
                return payload
            from .contact_constraints import fit_frame_full_sole_masks, motion_space_support_evidence
            full_sole_state = fit_frame_full_sole_masks(
                motion_space_support_evidence(payload),
                [frame.get('sourceTimeSec') for frame in payload.get('frames') or []],
                len(points),
            )
            eligible = np.ones(len(points), dtype=bool)
            for side in ('left', 'right'):
                ankle = names.index(side + '_ankle')
                foot = names.index(side + '_foot')
                # A full-sole foot pin owns the physical sole state; the ankle need
                # not be an exact XYZ pin for this presentation-only stance check.
                eligible &= ((pinned[:, ankle] & pinned[:, foot])
                             | (pinned[:, foot] & full_sole_state.get(
                                 side, np.zeros(len(points), dtype=bool))))
                eligible &= angles(joint(side+'_hip'), joint(side+'_knee'), joint(side+'_ankle')) > np.deg2rad(160)
            support = (joint('left_ankle') + joint('right_ankle')) / 2
            eligible &= angles(joint('neck'), joint('pelvis'), support) > np.deg2rad(165)
            up = joint('neck') - support
            up /= np.maximum(np.linalg.norm(up, axis=1, keepdims=True), 1e-12)
            reference_count = int(eligible.sum())
            reason = 'no_consistent_extended_stance'
            if reference_count >= max(8, int(float(payload['fps']) * .25)):
                normal = np.median(up[eligible], axis=0)
                normal /= np.linalg.norm(normal)
                spread = np.rad2deg(np.arccos(np.clip(up[eligible] @ normal, -1, 1)))
                tilt = np.arccos(np.clip(normal[1], -1, 1))
                if np.percentile(spread, 90) <= 3 and tilt <= np.deg2rad(12):
                    axis = np.cross(normal, [0., 1., 0.])
                    if np.linalg.norm(axis) > 1e-10:
                        rotation = Rotation.from_rotvec(axis / np.linalg.norm(axis) * tilt)
                    reason = 'consistent_extended_supported_stance'
        rotated = rotation.apply(points.reshape(-1, 3)).reshape(points.shape)
    else:
        if not isinstance(placement_override, dict) or placement_override.get('version') != 1:
            raise ValueError('placement override must be a version-1 scene placement')
        rotation_vector = np.asarray(placement_override.get('rotationVector'), dtype=float)
        origin = np.asarray(placement_override.get('originAfterRotation'), dtype=float)
        if (rotation_vector.shape != (3,) or origin.shape != (3,)
                or not np.isfinite(rotation_vector).all() or not np.isfinite(origin).all()):
            raise ValueError('placement override rotation and origin must be finite 3-vectors')
        rotation = Rotation.from_rotvec(rotation_vector)
        reference_count = int(placement_override.get('referenceFrames') or 0)
        reason = str(placement_override.get('orientationReason') or 'retained_scene_placement')
        rotated = rotation.apply(points.reshape(-1, 3)).reshape(points.shape)
    low, high = rotated.min(axis=(0, 1)), rotated.max(axis=(0, 1))
    floor = payload.get('renderFloorY')
    inferred_floor = floor is None and payload.get('groundContactMode') == 'continuous'
    if placement_override is None:
        origin = (low + high) / 2
        origin[1] = float(floor) if floor is not None else (low[1] if inferred_floor else 0.)
    else:
        inferred_floor = bool(placement_override.get('floorInferred', inferred_floor))
    result = deepcopy(payload)
    body_support = (result.get('sourceFootSupportEvidence') or {}).get('bodySupport') or {}
    for contact in body_support.get('materialRegionContacts', []):
        contact['planeOffsetMeters'] -= float(origin[1])
        x0, x1, z0, z1 = contact['boundsXZ']
        contact['boundsXZ'] = [x0-origin[0], x1-origin[0], z0-origin[2], z1-origin[2]]
    for group in body_support.get('coplanarGroups', []) + body_support.get('nonPenetrationChains', []) + body_support.get('soleContacts', []):
        group['normal'] = rotation.apply(group['normal']).tolist()
        if 'planeOffsetMeters' in group:
            normal = np.asarray(group['normal'], dtype=float)
            group['planeOffsetMeters'] -= float(np.dot(normal/np.linalg.norm(normal), origin))
    for frame in result['frames']:
        for key in ('joints', 'sourceJoints', 'cameraPlacementReferenceJoints', 'controlledSourceJoints', 'controlledArticulationReferenceJoints', 'correctedAnatomicalReferenceJoints', 'supportCorrectedReferenceJoints', 'supportContactReferenceJoints', 'supportAlignmentReferenceJoints'):
            for name, value in frame.get(key, {}).items():
                frame[key][name] = (rotation.apply(value) - origin).tolist()
        for name, value in frame.get('boneSides', {}).items():
            frame['boneSides'][name] = rotation.apply(value).tolist()
        for orientation in frame.get('shoeOrientation', {}).values():
            if not isinstance(orientation, dict):
                continue
            forward_values = np.asarray(orientation.get('forward'), dtype=float)
            side_values = np.asarray(orientation.get('side'), dtype=float)
            if (forward_values.shape != (3,) or side_values.shape != (3,)
                    or not np.all(np.isfinite(forward_values))
                    or not np.all(np.isfinite(side_values))):
                continue
            forward = rotation.apply(forward_values)
            side = rotation.apply(side_values)
            forward_length = float(np.linalg.norm(forward))
            if forward_length <= 1e-12:
                continue
            forward /= forward_length
            side -= forward * float(np.dot(side, forward))
            side_length = float(np.linalg.norm(side))
            if side_length <= 1e-12:
                continue
            orientation['forward'] = forward.tolist()
            orientation['side'] = (side / side_length).tolist()
    rig = result['fixedRig']
    contact_tracks = rig.get('contactFootTracks') or {}
    track_version = contact_tracks.get('version', 1)
    for side in ('left', 'right'):
        track = contact_tracks.get(side)
        if track is None:
            continue
        if track_version == 1:
            track['toes'] = (rotation.apply(track['toes']) - origin).tolist()
            track['directions'] = rotation.apply(track['directions']).tolist()
        elif track_version == 2:
            track['directions'] = rotation.apply(track['directions']).tolist()
            track['sideAxes'] = rotation.apply(track['sideAxes']).tolist()
            for episode in track.get('episodes') or []:
                if 'targetWorld' in episode:
                    episode['targetWorld'] = (
                        rotation.apply(episode['targetWorld']) - origin).tolist()
                if 'surfaceNormal' in episode:
                    normal = rotation.apply(episode['surfaceNormal'])
                    episode['surfaceNormal'] = normal.tolist()
                    if 'planeOffsetMeters' in episode:
                        episode['planeOffsetMeters'] = (
                            float(episode['planeOffsetMeters'])
                            - float(np.dot(normal, origin)))
    from .native_material_frames import place_material_frames
    place_material_frames(rig, rotation, origin)
    coordinates = np.asarray(rig['coordinates'])
    coordinates[:, :3] = rotation.apply(coordinates[:, :3]) - origin
    root = rig['jointNames'][rig['parents'].index(-1)]
    slot = 3 + 3 * rig['rotationJointNames'].index(root)
    coordinates[:, slot:slot+3] = (rotation * Rotation.from_rotvec(coordinates[:, slot:slot+3])).as_rotvec()
    rig['coordinates'] = coordinates.tolist()
    if floor is not None or inferred_floor:
        result['renderFloorY'] = 0.
    # Elevated surfaces retain world-up; only translation is applied in this case.
    for surface in result.get('elevatedSupportSurfaces', []):
        if isinstance(surface.get('orientationPoint'), list) and len(surface['orientationPoint']) == 3:
            surface['orientationPoint'] = (np.asarray(surface['orientationPoint']) - origin).tolist()
        if isinstance(surface.get('center'), list) and len(surface['center']) == 3:
            surface['center'] = (np.asarray(surface['center']) - origin).tolist()
        if isinstance(surface.get('topY'), (float, int)):
            surface['topY'] -= float(origin[1])
    refresh_motion_bounds(result)
    result['scenePlacement'] = (deepcopy(placement_override)
        if placement_override is not None else {
            'version': 1, 'orientationReason': reason,
            'referenceFrames': reference_count,
            'rotationVector': rotation.as_rotvec().tolist(),
            'rotationDegrees': float(np.rad2deg(rotation.magnitude())),
            'originAfterRotation': origin.tolist(),
            'floorInferred': inferred_floor,
        })
    from .rig_playback import validate_rig_playback
    playback = validate_rig_playback(result)
    if not playback['passed']:
        return payload
    if result.get('controlledMotionFit'):
        result['controlledMotionFit']['playback'] = playback
        result['controlledMotionFit']['outputPoseDigest'] = pose_digest(result)
    return result
