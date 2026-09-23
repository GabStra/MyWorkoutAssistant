"""Independent checks of the poses produced between exported rig samples."""
from __future__ import annotations

import numpy as np
from scipy.spatial.transform import Rotation

from .physical_validation import angles, body_scale, validate_physical_motion
from .sequence_stabilization import contact_mask
from .contact_constraints import (stationary_target_track, stationary_contact_anchor_ids,
                                  observed_ground_contact_mask, calibrate_shared_contact_pair,
                                  InfeasibleContactCorrection)

# Mid-sample contact tolerance for hermite-interpolated samples. The fit's
# keyframe anchor standard stays at 0.5mm (a solver-precision demand the
# optimizer satisfies); the spline overshoots between keyframes, so this
# limit is calibrated to the rendering-perception scale instead — 3mm is
# sub-pixel at wear-preview resolution and ~100x below visible skating.
PLAYBACK_CONTACT_LIMIT_METERS = .003
PLAYBACK_FLOOR_LIMIT_METERS = .002


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
        # Calibrating each toe episode separately must not split an ankle that
        # the source explicitly identifies as the same stationary anchor.
        shared_groups = {value for value in anchor_ids[active, ankle] if value is not None}
        if any(len(np.unique(anchors[active & (anchor_ids[:, ankle] == group), foot], axis=0)) > 1
               for group in shared_groups):
            pair = [ankle, foot]
            calibrated = calibrate_shared_contact_pair(
                anchors[:, pair], pinned[:, pair], anchor_ids[:, pair],
                distance=np.linalg.norm(offsets[foot]), ground_mask=ground[:, pair], floor=floor)
            maximum_calibration = max(maximum_calibration, float(np.max(
                np.linalg.norm(calibrated[:, 0] - anchors[:, ankle], axis=1))))
            anchors[:, pair] = calibrated
            continue
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


def sample_rig_coordinates(rig, cursors, *, wrap=False):
    """Interpolate stored coordinates before enforcing the playback socket guard."""
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
        roots = hermite_samples(values[:, :3], first, last, alpha, wrap=wrap, smooth_limiter=smooth_limiter)
    else:
        left, right = quaternions[first], quaternions[last]
        dot = np.sum(left*right, axis=-1, keepdims=True)
        right = np.where(dot < 0., -right, right)
        theta = np.arccos(np.clip(abs(dot), 0., 1.)) / np.pi
        amount = alpha[:,None,None]
        interpolated = (left*(1.-amount)*np.sinc((1.-amount)*theta)
                        + right*amount*np.sinc(amount*theta)) / np.sinc(theta)
        roots = values[first,:3]*(1.-alpha[:,None])+values[last,:3]*alpha[:,None]
    rotvecs = Rotation.from_quat(interpolated.reshape(-1, 4)).as_rotvec().reshape(len(cursors), -1)
    return np.concatenate([roots, rotvecs], axis=1)


def sample_rig(rig, cursors, *, wrap=False):
    coordinates = sample_rig_coordinates(rig, cursors, wrap=wrap)
    # Keyframe socket projection does not preserve the collar plane under
    # rotation interpolation. Re-apply the same analytic clamp on samples so
    # residual, export, and playback validate one consistent neck attachment.
    from .controlled_motion import ANATOMY_FIT_MARGIN, project_neck_attachment_values
    from .physical_validation import SOCKET_ALIGNMENT_MAX_LATERAL_RATIO
    names = list(rig['jointNames'])
    active = [names.index(name) for name in rig['rotationJointNames']]
    coordinates = project_neck_attachment_values(
        coordinates, np.asarray(rig['offsets'], dtype=float), names, active,
        SOCKET_ALIGNMENT_MAX_LATERAL_RATIO - ANATOMY_FIT_MARGIN)
    return decode_rig(rig, coordinates)


def unanchored_floor_clearance_lift(rig, floor, pinned, *, cyclic, subdivisions=4):
    """A constant placement correction cannot change motion or break a loop seam."""
    if floor is None or np.any(pinned):
        return 0.0
    count = len(rig['coordinates'])
    cursors = np.arange(count * subdivisions if cyclic else (count - 1) * subdivisions + 1) / subdivisions
    points = sample_rig(rig, cursors, wrap=cyclic)
    return max(0.0, float(floor) - float(points[:, :, 1].min()))


def free_joint_floor_clearance_lift(rig, floor, pinned, *, cyclic, subdivisions=4):
    """Raise only the unsupported interpolated path above the floor.

    Planted contacts keep their anchors; a constant root lift is recovered by
    a later freeze-root plant projection so stance does not float away.
    """
    if floor is None:
        return 0.0
    if not np.any(pinned):
        return unanchored_floor_clearance_lift(rig, floor, pinned, cyclic=cyclic, subdivisions=subdivisions)
    count = len(rig['coordinates'])
    cursors = np.arange(count * subdivisions if cyclic else (count - 1) * subdivisions + 1) / subdivisions
    points = sample_rig(rig, cursors, wrap=cyclic)
    first = np.floor(cursors).astype(int)
    last = np.ceil(cursors).astype(int) % count
    planted = pinned[first] & pinned[last]
    heights = np.asarray(points[:, :, 1], dtype=float)
    heights[planted] = np.inf
    lowest = float(np.min(heights))
    if not np.isfinite(lowest):
        return 0.0
    return max(0.0, float(floor) - lowest)


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
    unplaced, fitting_floor = source, payload.get('renderFloorY')
    if placement.get('version') == 1:
        # Component medians are not rotation-equivariant. Reconstruct the
        # immutable stance anchors in the fitting frame, then place them with
        # the rig; do not choose new anchors after a presentation rotation.
        rotation = Rotation.from_rotvec(placement['rotationVector'])
        origin = np.asarray(placement['originAfterRotation'])
        unplaced = rotation.inv().apply((source + origin).reshape(-1, 3)).reshape(source.shape)
        fitting_floor = None if (payload.get('renderFloorY') is None or placement.get('floorInferred')) else float(payload['renderFloorY'])+float(origin[1])
    try:
        anchors,_=rig_contact_targets(unplaced,names,pinned,rig['offsets'], evidence=payload.get('sourceFootSupportEvidence'), floor=fitting_floor)
    except InfeasibleContactCorrection as error:
        return {'passed': False, 'reason': 'incompatible_stationary_contact_anchors',
                'physicalReasons': ['incompatible_stationary_contact_anchors'],
                'contactConstraintError': str(error)}
    if placement.get('version') == 1:
        anchors = rotation.apply(anchors.reshape(-1, 3)).reshape(source.shape) - origin
    first=np.floor(cursors).astype(int);last=np.ceil(cursors).astype(int)%count
    active=pinned[first]&pinned[last]
    contact_error=float(np.max(np.linalg.norm((points-anchors[first])[active],axis=-1),initial=0.))
    frame_contact_error=float(np.max(np.linalg.norm((originals-anchors)[pinned],axis=-1),initial=0.))
    from .heel_contacts import heel_contact_tracks
    heel_contacts = heel_contact_tracks(
        unplaced, names, payload.get('sourceFootSupportEvidence'), floor=fitting_floor, fps=fps)
    if placement.get('version') == 1 and heel_contacts.pairs:
        shape = heel_contacts.targets.shape
        heel_contacts.targets = rotation.apply(heel_contacts.targets.reshape(-1, 3)).reshape(shape) - origin
    heel_error = float(np.max(np.linalg.norm(
        heel_contacts.residual(points, first, last), axis=-1), initial=0.))
    heel_frame_error = float(np.max(np.linalg.norm(heel_contacts.residual(originals), axis=-1), initial=0.))
    contact_error = max(contact_error, heel_error)
    frame_contact_error = max(frame_contact_error, heel_frame_error)
    floor=payload.get('renderFloorY')
    floor_error=0. if floor is None else max(0.,float(floor)-float(points[:,:,1].min()))
    # Match keyframe anatomy authority: torso-bend floors follow the observed
    # articulation reference. For mid-samples, use the more flexed enclosing
    # keyframe so hermite interpolation of a legal hinge is not rejected.
    articulation = np.asarray([
        [f.get('controlledArticulationReferenceJoints',
               f.get('correctedAnatomicalReferenceJoints',
                     f.get('controlledSourceJoints', f['joints'])))[n]
         for n in names]
        for f in payload['frames']], dtype=float)
    if (articulation.shape == (count, len(names), 3)
            and np.isfinite(articulation).all()):
        from .physical_validation import angles
        index = {name: i for i, name in enumerate(names)}
        reference_samples = articulation[first].copy()
        if all(name in index for name in ('left_hip', 'right_hip', 'spine1', 'neck')):
            def _torso_angles(pts):
                hips = 0.5 * (pts[:, index['left_hip']] + pts[:, index['right_hip']])
                return angles(
                    hips, pts[:, index['spine1']], pts[:, index['neck']])

            ang_first = _torso_angles(articulation[first])
            ang_last = _torso_angles(articulation[last])
            use_last = ang_last < ang_first
            reference_samples = np.where(
                use_last[:, None, None], articulation[last], articulation[first])
        sample_pin = pinned[first] & pinned[last]
        foot_names = ('left_ankle', 'left_foot', 'right_ankle', 'right_foot')
        if all(name in index for name in foot_names):
            foot_idx = [index[name] for name in foot_names]
            support_mask = np.all(sample_pin[:, foot_idx], axis=1)
        else:
            support_mask = None
        physical = validate_physical_motion(
            points, names, reference=reference_samples, fps=fps * subdivisions,
            support_mask=support_mask)
    else:
        physical = validate_physical_motion(points, names, fps=fps * subdivisions)
    # Fixed-rig bone lengths are checked via maximumBoneLengthVariationMeters.
    # repair_* distortion events assume frame-aligned reference vs result; on
    # hermite mid-samples that comparison is not meaningful — keep structure
    # anatomy (torso/spine) only, matching keyframe supersession of length noise.
    _playback_ignore = {
        'repair_bone_length_distortion',
        'repair_articulation_distortion',
        'repair_head_articulation_distortion',
        'repair_hinge_branch_flip',
    }
    # Keyframe anatomy is already gated on the exported joints. Hermite can
    # overshoot torso/spine residuals between accepted knots; reject structure
    # only when it also appears on the knot samples themselves.
    _structure_mid_only = {
        'anatomy_spine_deviation',
        'anatomy_torso_bend',
        'anatomy_spine_fold',
        'anatomy_chest_attachment',
        'anatomy_neck_fold',
    }
    knot_frames = set(range(0, len(points), subdivisions))
    physical = dict(physical)
    physical['events'] = [
        event for event in physical.get('events') or []
        if event.get('reason') not in _playback_ignore
        and not (
            event.get('reason') in _structure_mid_only
            and int(event.get('frameIndex', -1)) not in knot_frames
        )]
    physical['reasons'] = sorted({event['reason'] for event in physical['events']})
    physical['passed'] = not physical['events']
    variation=max(float(np.ptp(np.linalg.norm(points[:,j]-points[:,parent],axis=-1)))
                  for j,parent in enumerate(rig['parents']) if parent>=0)
    from .loop_seam import seam_quality_metrics
    seam_metrics = seam_quality_metrics(originals, fps=fps, scale=scale)
    seam_safe = seam_metrics['seamContinuous']
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
    passed=sample_error<1e-7 and physical['passed'] and contact_error<=PLAYBACK_CONTACT_LIMIT_METERS and floor_error<=PLAYBACK_FLOOR_LIMIT_METERS and variation<1e-9 and equipment['passed'] and body_support['passed'] and shoe_orientation['passed'] and alignment['passed'] and velocity_continuous
    return {'passed':bool(passed),'sampleCount':len(points),'subdivisions':subdivisions,
            'maximumSamplePoseMismatchMeters':sample_error,'maximumContactErrorMeters':contact_error,
            'maximumHeelContactErrorMeters':heel_error,
            'equipment': equipment,
            'bodySupport': body_support,
            'shoeOrientation': shoe_orientation,
            'supportAlignment': alignment,
            'interpolation': rig.get('interpolation', 'linear_slerp'),
            'maximumFrameBoundaryVelocityJumpMetersPerSecond': velocity_jump,
            'velocityContinuous': bool(velocity_continuous),
            'maximumStoredFrameContactErrorMeters':frame_contact_error,'maximumFloorPenetrationMeters':floor_error,
            'maximumBoneLengthVariationMeters':variation,'physicalReasons':physical['reasons'],
            'physicalEvents':physical['events'][:8], **seam_metrics,
            'loopTransition':'continuous' if seam_safe else 'requires_cycle_repair'}
