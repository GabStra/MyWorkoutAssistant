"""Constant presentation placement of a finished rig, without changing articulation."""
from copy import deepcopy

import numpy as np
from scipy.spatial.transform import Rotation

from .physical_validation import angles
from .sequence_stabilization import contact_mask, pose_digest
from .temporal_quality import refresh_motion_bounds


def normalize_scene_placement(payload):
    """Center once; infer a modest upright offset only from quiet extended stances.

    A standing reference is a presentation convention, not a gravity estimate.
    An explicit floor or elevated support takes precedence over that convention.
    Never use a per-frame upright constraint: bends, jumps and travel must survive.
    """
    if payload.get('scenePlacement', {}).get('version') == 1:
        return payload
    if not payload.get('fixedRig') or not payload.get('frames'):
        return payload
    names = payload['jointNames']
    points = np.array([[f['joints'][n] for n in names] for f in payload['frames']])
    def joint(name):
        return points[:, names.index(name)]
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
        eligible = np.ones(len(points), dtype=bool)
        for side in ('left', 'right'):
            eligible &= pinned[:, names.index(side+'_ankle')] & pinned[:, names.index(side+'_foot')]
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
    low, high = rotated.min(axis=(0, 1)), rotated.max(axis=(0, 1))
    floor = payload.get('renderFloorY')
    inferred_floor = floor is None and payload.get('groundContactMode') == 'continuous'
    origin = (low + high) / 2
    origin[1] = float(floor) if floor is not None else (low[1] if inferred_floor else 0.)
    result = deepcopy(payload)
    body_support = (result.get('sourceFootSupportEvidence') or {}).get('bodySupport') or {}
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
    rig = result['fixedRig']
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
        if isinstance(surface.get('center'), list) and len(surface['center']) == 3:
            surface['center'] = (np.asarray(surface['center']) - origin).tolist()
        if isinstance(surface.get('topY'), (float, int)):
            surface['topY'] -= float(origin[1])
    refresh_motion_bounds(result)
    result['scenePlacement'] = {'version': 1, 'orientationReason': reason,
                              'referenceFrames': reference_count,
                              'rotationVector': rotation.as_rotvec().tolist(),
                              'rotationDegrees': float(np.rad2deg(rotation.magnitude())),
                              'originAfterRotation': origin.tolist(),
                              'floorInferred': inferred_floor}
    from .rig_playback import validate_rig_playback
    playback = validate_rig_playback(result)
    if not playback['passed']:
        return payload
    if result.get('controlledMotionFit'):
        result['controlledMotionFit']['playback'] = playback
        result['controlledMotionFit']['outputPoseDigest'] = pose_digest(result)
    return result
