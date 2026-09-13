"""Independent checks of the poses produced between exported rig samples."""
from __future__ import annotations

import numpy as np
from scipy.spatial.transform import Rotation

from .physical_validation import body_scale, validate_physical_motion
from .sequence_stabilization import contact_mask
from .contact_constraints import stationary_target_track, stationary_contact_anchor_ids, observed_ground_contact_mask


def rig_contact_targets(points, names, pinned, offsets, *, stationary_positions=None, evidence=None, floor=None):
    """Immutable source stance anchors, calibrated to the fixed foot geometry."""
    reference = points.copy()
    for name, position in (stationary_positions or {}).items():
        reference[:, names.index(name)] = position
    anchors = reference.copy()
    anchor_ids = stationary_contact_anchor_ids(evidence, names, len(points))
    for joint in range(len(names)):
        anchors[:,joint],_ = stationary_target_track(reference[:,joint],pinned[:,joint],
                                                    anchor_ids=anchor_ids[:, joint])
    ground = observed_ground_contact_mask(evidence, names, len(points)) & pinned
    if floor is not None:
        for side in ('left', 'right'):
            ankle, foot = names.index(side+'_ankle'), names.index(side+'_foot')
            active = ground[:, foot]
            shift = float(floor)-anchors[active, foot, 1]
            anchors[active, foot, 1] = float(floor)
            anchors[active, ankle, 1] += shift
    maximum_calibration = 0.
    for side in ('left', 'right'):
        ankle, foot = names.index(side+'_ankle'), names.index(side+'_foot')
        active = pinned[:,ankle]&pinned[:,foot]
        direction = anchors[:,ankle]-anchors[:,foot]
        direction /= np.maximum(np.linalg.norm(direction,axis=-1,keepdims=True),1e-12)
        proposed = anchors[:,foot]+direction*np.linalg.norm(offsets[foot])
        maximum_calibration = max(maximum_calibration, float(np.max(
            np.linalg.norm((proposed-anchors[:,ankle])[active],axis=-1),initial=0.)))
        anchors[active,ankle] = proposed[active]
    return anchors, maximum_calibration


def decode_rig(rig, coordinates):
    values = np.asarray(coordinates,dtype=float)
    rotations = Rotation.from_rotvec(values[:,3:].reshape(-1,3)).as_matrix().reshape(
        len(values), len(rig['rotationJointNames']), 3, 3)
    return _decode_rig_matrices(rig, values[:, :3], rotations)


def _decode_rig_matrices(rig, roots, rotations):
    """Share forward kinematics without round-tripping interpolated rotations."""
    names, parents = rig['jointNames'], rig['parents']
    slots = {names.index(n):i for i,n in enumerate(rig['rotationJointNames'])}
    points=np.empty((len(roots),len(names),3));matrices={}
    identity = np.broadcast_to(np.eye(3), (len(roots), 3, 3))
    for joint in rig['order']:
        parent=parents[joint]
        local=rotations[:,slots[joint]] if joint in slots else identity
        matrices[joint]=local if parent<0 else matrices[parent]@local
        points[:,joint]=roots if parent<0 else points[:,parent]+np.einsum('fij,j->fi',matrices[joint],rig['offsets'][joint])
    return points


def sample_rig(rig, cursors, *, wrap=False):
    values=np.asarray(rig['coordinates'],dtype=float)
    cursors=np.asarray(cursors,dtype=float)
    cursors=np.mod(cursors,len(values)) if wrap else np.clip(cursors,0,len(values)-1)
    first=np.floor(cursors).astype(int);last=(first+1)%len(values) if wrap else np.minimum(first+1,len(values)-1)
    alpha=cursors-first
    # Convert each stored rotation once, rather than once per subframe endpoint.
    # Quaternion SLERP follows the same shortest rotation arc as the rotvec
    # composition; sinc keeps the identical/near-identical case differentiable.
    joint_count = (values.shape[1]-3)//3
    quaternions = Rotation.from_rotvec(values[:,3:].reshape(-1,3)).as_quat().reshape(len(values),joint_count,4)
    from .rig_interpolation import INTERPOLATION, LEGACY_INTERPOLATION, hermite_samples
    if rig.get('interpolation') in (INTERPOLATION, LEGACY_INTERPOLATION):
        smooth_limiter = rig.get('interpolation') == INTERPOLATION
        interpolated = hermite_samples(quaternions, first, last, alpha, wrap=wrap, quaternion=True, smooth_limiter=smooth_limiter)
        rotations = Rotation.from_quat(interpolated.reshape(-1,4)).as_matrix().reshape(len(cursors),joint_count,3,3)
        roots = hermite_samples(values[:, :3], first, last, alpha, wrap=wrap, smooth_limiter=smooth_limiter)
        return _decode_rig_matrices(rig, roots, rotations)
    left, right = quaternions[first], quaternions[last]
    dot = np.sum(left*right, axis=-1, keepdims=True)
    right = np.where(dot < 0., -right, right)
    theta = np.arccos(np.clip(abs(dot), 0., 1.)) / np.pi
    amount = alpha[:,None,None]
    interpolated = (left*(1.-amount)*np.sinc((1.-amount)*theta)
                    + right*amount*np.sinc(amount*theta)) / np.sinc(theta)
    rotations = Rotation.from_quat(interpolated.reshape(-1,4)).as_matrix().reshape(len(cursors),joint_count,3,3)
    roots = values[first,:3]*(1.-alpha[:,None])+values[last,:3]*alpha[:,None]
    return _decode_rig_matrices(rig, roots, rotations)


def unanchored_floor_clearance_lift(rig, floor, pinned, *, cyclic, subdivisions=4):
    """A constant placement correction cannot change motion or break a loop seam."""
    if floor is None or np.any(pinned):
        return 0.0
    count = len(rig['coordinates'])
    cursors = np.arange(count * subdivisions if cyclic else (count - 1) * subdivisions + 1) / subdivisions
    points = sample_rig(rig, cursors, wrap=cyclic)
    return max(0.0, float(floor) - float(points[:, :, 1].min()))


def validate_rig_playback(payload, *, subdivisions=4):
    rig=payload['fixedRig'];names=rig['jointNames'];count=len(rig['coordinates']);fps=float(payload['fps'])
    cyclic=bool((payload.get("loop") or {}).get("enabled"))
    cursors=np.arange(count*subdivisions if cyclic else (count-1)*subdivisions+1)/subdivisions
    points=sample_rig(rig,cursors,wrap=cyclic);scale=body_scale(points,names)
    originals=np.asarray([[f['joints'][n] for n in names] for f in payload['frames']],dtype=float)
    sample_error=float(np.max(abs(points[::subdivisions]-originals)))
    pinned=contact_mask(payload,names,count)
    if pinned is None:
        return {'passed':False,'reason':'unrepresented_heel_contact'}
    source=np.asarray([[f.get('supportContactReferenceJoints', f.get('controlledSourceJoints',f['joints']))[n] for n in names] for f in payload['frames']],dtype=float)
    placement = payload.get('scenePlacement', {})
    if placement.get('version') == 1:
        # Component medians are not rotation-equivariant. Reconstruct the
        # immutable stance anchors in the fitting frame, then place them with
        # the rig; do not choose new anchors after a presentation rotation.
        rotation = Rotation.from_rotvec(placement['rotationVector'])
        origin = np.asarray(placement['originAfterRotation'])
        unplaced = rotation.inv().apply((source + origin).reshape(-1, 3)).reshape(source.shape)
        fitting_floor = None if (payload.get('renderFloorY') is None or placement.get('floorInferred')) else float(payload['renderFloorY'])+float(origin[1])
        anchors,_=rig_contact_targets(unplaced,names,pinned,rig['offsets'], evidence=payload.get('sourceFootSupportEvidence'), floor=fitting_floor)
        anchors = rotation.apply(anchors.reshape(-1, 3)).reshape(source.shape) - origin
    else:
        anchors,_=rig_contact_targets(source,names,pinned,rig['offsets'], evidence=payload.get('sourceFootSupportEvidence'), floor=payload.get('renderFloorY'))
    first=np.floor(cursors).astype(int);last=np.ceil(cursors).astype(int)%count
    active=pinned[first]&pinned[last]
    contact_error=float(np.max(np.linalg.norm((points-anchors[first])[active],axis=-1),initial=0.))
    frame_contact_error=float(np.max(np.linalg.norm((originals-anchors)[pinned],axis=-1),initial=0.))
    floor=payload.get('renderFloorY')
    floor_error=0. if floor is None else max(0.,float(floor)-float(points[:,:,1].min()))
    physical=validate_physical_motion(points,names,fps=fps*subdivisions)
    variation=max(float(np.ptp(np.linalg.norm(points[:,j]-points[:,parent],axis=-1)))
                  for j,parent in enumerate(rig['parents']) if parent>=0)
    from .loop_seam import seam_errors, MAX_STEP_EXCESS_BODY_RATIO, MAX_VELOCITY_MISMATCH_BODY_RATIO
    seam, step_excess, velocity_errors = seam_errors(originals)
    seam_jump=float(np.max(np.linalg.norm(seam,axis=-1)))
    mismatch=float(np.max(np.linalg.norm(velocity_errors,axis=-1)))*fps
    # Last and first are consecutive samples, not coincident endpoints.
    # A fixed displacement cutoff incorrectly rejects smooth fast motion.
    seam_step_excess=float(np.max(step_excess))
    seam_safe=(seam_step_excess<MAX_STEP_EXCESS_BODY_RATIO*scale
               and mismatch<MAX_VELOCITY_MISMATCH_BODY_RATIO*scale)
    from .equipment_constraints import validate_grip
    equipment = validate_grip(points, names, payload.get('equipmentConstraints') or {})
    from .support_geometry import validate_support_geometry, validate_supported_shoe_orientation
    body_support = validate_support_geometry(payload, points, names)
    shoe_orientation = validate_supported_shoe_orientation(payload)
    from .support_alignment import validate_payload_alignment
    alignment = validate_payload_alignment(payload, points, cursors)
    from .rig_interpolation import INTERPOLATION, LEGACY_INTERPOLATION
    velocity_jump = None
    velocity_continuous = True
    if rig.get('interpolation') in (INTERPOLATION, LEGACY_INTERPOLATION):
        knots = np.arange(count) if cyclic else np.arange(1, count-1)
        if len(knots):
            from .rig_interpolation import frame_boundary_velocity_jump
            velocity_jump = frame_boundary_velocity_jump(
                lambda cursors: sample_rig(rig, cursors, wrap=cyclic), knots, fps)
            velocity_continuous = velocity_jump < .001*scale
    passed=sample_error<1e-7 and physical['passed'] and contact_error<=.0005 and floor_error<=.002 and variation<1e-9 and equipment['passed'] and body_support['passed'] and shoe_orientation['passed'] and alignment['passed'] and velocity_continuous
    return {'passed':bool(passed),'sampleCount':len(points),'subdivisions':subdivisions,
            'maximumSamplePoseMismatchMeters':sample_error,'maximumContactErrorMeters':contact_error,
            'equipment': equipment,
            'bodySupport': body_support,
            'shoeOrientation': shoe_orientation,
            'supportAlignment': alignment,
            'interpolation': rig.get('interpolation', 'linear_slerp'),
            'maximumFrameBoundaryVelocityJumpMetersPerSecond': velocity_jump,
            'velocityContinuous': bool(velocity_continuous),
            'maximumStoredFrameContactErrorMeters':frame_contact_error,'maximumFloorPenetrationMeters':floor_error,
            'maximumBoneLengthVariationMeters':variation,'physicalReasons':physical['reasons'],
            'physicalEvents':physical['events'][:8], 'seamPositionJumpMeters':seam_jump,
            'seamStepExcessMeters':seam_step_excess,'seamVelocityMismatchMetersPerSecond':mismatch,'seamContinuous':bool(seam_safe),
            'loopTransition':'continuous' if seam_safe else 'requires_cycle_repair'}
