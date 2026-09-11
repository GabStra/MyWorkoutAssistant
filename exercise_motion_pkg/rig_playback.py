"""Independent checks of the poses produced between exported rig samples."""
from __future__ import annotations

import numpy as np
from scipy.spatial.transform import Rotation

from .physical_validation import body_scale, validate_physical_motion
from .sequence_stabilization import contact_mask
from .contact_constraints import stationary_target_track


def rig_contact_targets(points, names, pinned, offsets):
    """Immutable source stance anchors, calibrated to the fixed foot geometry."""
    anchors = points.copy()
    for joint in range(len(names)):
        anchors[:,joint],_ = stationary_target_track(points[:,joint],pinned[:,joint])
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
    source=np.asarray([[f.get('controlledSourceJoints',f['joints'])[n] for n in names] for f in payload['frames']],dtype=float)
    placement = payload.get('scenePlacement', {})
    if placement.get('version') == 1:
        # Component medians are not rotation-equivariant. Reconstruct the
        # immutable stance anchors in the fitting frame, then place them with
        # the rig; do not choose new anchors after a presentation rotation.
        rotation = Rotation.from_rotvec(placement['rotationVector'])
        origin = np.asarray(placement['originAfterRotation'])
        unplaced = rotation.inv().apply((source + origin).reshape(-1, 3)).reshape(source.shape)
        anchors,_=rig_contact_targets(unplaced,names,pinned,rig['offsets'])
        anchors = rotation.apply(anchors.reshape(-1, 3)).reshape(source.shape) - origin
    else:
        anchors,_=rig_contact_targets(source,names,pinned,rig['offsets'])
    first=np.floor(cursors).astype(int);last=np.ceil(cursors).astype(int)%count
    active=pinned[first]&pinned[last]
    contact_error=float(np.max(np.linalg.norm((points-anchors[first])[active],axis=-1),initial=0.))
    frame_contact_error=float(np.max(np.linalg.norm((originals-anchors)[pinned],axis=-1),initial=0.))
    floor=payload.get('renderFloorY')
    floor_error=0. if floor is None else max(0.,float(floor)-float(points[:,:,1].min()))
    physical=validate_physical_motion(points,names,fps=fps*subdivisions)
    variation=max(float(np.ptp(np.linalg.norm(points[:,j]-points[:,parent],axis=-1)))
                  for j,parent in enumerate(rig['parents']) if parent>=0)
    seam=originals[0]-originals[-1]
    seam_jump=float(np.max(np.linalg.norm(seam,axis=-1)))
    mismatch=max(float(np.max(np.linalg.norm(seam-(originals[-1]-originals[-2]),axis=-1))),
                 float(np.max(np.linalg.norm((originals[1]-originals[0])-seam,axis=-1))))*fps
    # Last and first are consecutive samples, not coincident endpoints.
    # A fixed displacement cutoff incorrectly rejects smooth fast motion.
    neighbor_steps=np.maximum(np.linalg.norm(originals[-1]-originals[-2],axis=-1),
                              np.linalg.norm(originals[1]-originals[0],axis=-1))
    seam_step_excess=float(np.max(np.maximum(np.linalg.norm(seam,axis=-1)-neighbor_steps*1.25,0.)))
    seam_safe=seam_step_excess<.001*scale and mismatch<.15*scale
    passed=sample_error<1e-7 and physical['passed'] and contact_error<=.0005 and floor_error<=.002 and variation<1e-9
    return {'passed':bool(passed),'sampleCount':len(points),'subdivisions':subdivisions,
            'maximumSamplePoseMismatchMeters':sample_error,'maximumContactErrorMeters':contact_error,
            'maximumStoredFrameContactErrorMeters':frame_contact_error,'maximumFloorPenetrationMeters':floor_error,
            'maximumBoneLengthVariationMeters':variation,'physicalReasons':physical['reasons'],
            'physicalEvents':physical['events'][:8], 'seamPositionJumpMeters':seam_jump,
            'seamStepExcessMeters':seam_step_excess,'seamVelocityMismatchMetersPerSecond':mismatch,'seamContinuous':bool(seam_safe),
            'loopTransition':'continuous' if seam_safe else 'requires_cycle_repair'}
