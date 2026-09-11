"""Default final-bake fixed-rig trajectory fit; legacy output remains available."""
from __future__ import annotations

from copy import deepcopy
from time import monotonic
from types import SimpleNamespace
import numpy as np
from scipy.ndimage import gaussian_filter1d
from scipy.optimize import least_squares
from scipy.sparse import csr_matrix, eye, kron, vstack
from scipy.spatial.transform import Rotation

from .sequence_stabilization import contact_mask, frame_basis, pose_digest, unit
from .smpl_joint_names import SMPL_JOINT_NAMES, SMPL_JOINT_PARENTS
from .physical_validation import ARTICULATIONS, angles, body_scale, collision_clearances, collision_specs, validate_physical_motion, anatomical_structure_residuals
from .temporal_quality import body_orientation_axes, body_orientation_noise, body_local_head_direction, introduced_joint_spikes, refresh_motion_bounds, transport_corrected_bone_sides
from .motion_placement import contact_consistent_target, root_motion_quality, register_contact_placement, align_registered_contacts_above_floor

CONTROLLED_MOTION_STRATEGY = 'fixed_rig_controlled_motion_v20_preserve_torso_lean'
# Leave clearance in the proposal; do not optimize against the validator's
# permitted penetration boundary at interpolated frames.
COLLISION_FIT_MARGIN_RATIO = .0025
REQUIRED_FIT_CHECKS = ('anatomy', 'contacts', 'sourceArticulation', 'trajectoryFit',
                       'rootTravel', 'jointRange', 'jointShake', 'settling', 'jerk',
                       'fixedRig', 'playback', 'relativeJointShake', 'bodyRotation', 'rootContinuity')


def controlled_fit_processing_incomplete(report):
    """A deadline is missing processing evidence, not a failed geometry check."""
    if not isinstance(report, dict) or report.get('applied'):
        return False
    return report.get('reason') == 'fit_timeout' or any(
        controlled_fit_processing_incomplete(attempt.get('fitReport', attempt))
        for attempt in report.get('cycleSelectionAttempts', [])
    )


def can_reuse_controlled_motion(payload):
    report = payload.get('controlledMotionFit') or {}
    checks = report.get('checks') or {}
    return bool(payload.get('fixedRig') and report.get('applied')
                and report.get('strategy') == CONTROLLED_MOTION_STRATEGY
                and all(checks.get(key) is True for key in REQUIRED_FIT_CHECKS)
                and all(value is True for value in checks.values())
                and (not (payload.get('loop') or {}).get('enabled') or checks.get('loopSeam') is True)
                and report.get('outputPoseDigest') == pose_digest(payload))


def align_vectors(first, last):
    first, last = unit(first), unit(last)
    cross = np.cross(first, last)
    sine = np.linalg.norm(cross, axis=-1)
    cosine = np.clip(np.sum(first*last, axis=-1), -1., 1.)
    axis = cross / np.maximum(sine[:, None], 1e-12)
    opposite = (sine < 1e-8) & (cosine < 0.)
    if opposite.any():
        basis = np.eye(3)[np.argmin(abs(first[opposite]), axis=-1)]
        axis[opposite] = unit(np.cross(first[opposite], basis))
    return axis*np.arctan2(sine, cosine)[:, None]


def transported_bone_rotations(directions):
    """Infer a continuous minimum-twist frame for position-only observations.

    Independently aligning body-up on every frame is singular for downward
    bones: minute changes can invent half-turns of unobserved axial rotation.
    Transport the previous frame by the observed change in direction instead.
    """
    directions = unit(directions)
    matrices = np.empty((len(directions), 3, 3))
    matrices[0] = Rotation.from_rotvec(align_vectors(np.array([[0., 1., 0.]]), directions[:1])).as_matrix()[0]
    changes = Rotation.from_rotvec(align_vectors(directions[:-1], directions[1:])).as_matrix()
    for frame in range(1, len(directions)):
        matrices[frame] = changes[frame-1]@matrices[frame-1]
    return Rotation.from_matrix(matrices)


class FixedRig:
    """One set of offsets; root travel and local rotations are the only variables.

    Hip and collar sockets inherit the pelvis/chest transform. Their offsets
    cannot float independently. Axial twist is not inferred from joint positions.
    """
    def __init__(self, points, names):
        self.names = names
        self.parents = [names.index(SMPL_JOINT_NAMES[SMPL_JOINT_PARENTS[SMPL_JOINT_NAMES.index(n)]] )
                        if n != 'pelvis' else -1 for n in names]
        self.order = [names.index(n) for n in SMPL_JOINT_NAMES]
        self.root = names.index('pelvis')
        self.fixed = {names.index(n) for n in ('left_hip', 'right_hip', 'left_collar', 'right_collar')}
        self.active = [j for j in self.order if j not in self.fixed]
        self.slots = {j: 3+3*i for i,j in enumerate(self.active)}
        self.width = 3+3*len(self.active)
        self.offsets = np.zeros((len(names), 3))
        self.initial = np.zeros((len(points), self.width))
        self.initial[:, :3] = points[:, self.root]
        matrices = {}
        axes = body_orientation_axes(points, names)
        matrices[self.root] = frame_basis(axes[:, 1], axes[:, 0])
        self.initial[:, self.slots[self.root]:self.slots[self.root]+3] = Rotation.from_matrix(matrices[self.root]).as_rotvec()
        for j in self.order[1:]:
            parent = self.parents[j]
            local = np.einsum('fji,fj->fi', matrices[parent], points[:, j]-points[:, parent])
            length = float(np.median(np.linalg.norm(local, axis=1)))
            if j in self.fixed:
                self.offsets[j] = unit(np.median(local, axis=0))*length
                matrices[j] = matrices[parent]
            else:
                self.offsets[j] = [0., length, 0.]
                rotation = transported_bone_rotations(local)
                self.initial[:, self.slots[j]:self.slots[j]+3] = rotation.as_rotvec()
                matrices[j] = matrices[parent]@rotation.as_matrix()
        # Calibrate anatomy, not pose symmetry. Each limb keeps its own local
        # rotations while matching bones share one length for the entire clip.
        for name in names:
            other = name.replace('left_', 'right_', 1)
            if not name.startswith('left_') or other not in names:
                continue
            left, right = names.index(name), names.index(other)
            length = (np.linalg.norm(self.offsets[left])+np.linalg.norm(self.offsets[right]))*.5
            if left in self.fixed:
                lateral = unit(self.offsets[right]-self.offsets[left])
                center = (self.offsets[left]+self.offsets[right])*.5
                center -= lateral*np.dot(center, lateral)
                half_span = np.linalg.norm(self.offsets[right]-self.offsets[left])*.5
                self.offsets[left] = center-lateral*half_span
                self.offsets[right] = center+lateral*half_span
            self.offsets[left] = unit(self.offsets[left])*length
            self.offsets[right] = unit(self.offsets[right])*length
        # Center the neck attachment in the calibrated chest socket plane.
        # Preserve the head's world direction while rebasing its parent frame.
        neck, head = names.index('neck'), names.index('head')
        lateral = unit(self.offsets[names.index('right_collar')]-self.offsets[names.index('left_collar')])
        neck_slot, head_slot = self.slots[neck], self.slots[head]
        old_neck = Rotation.from_rotvec(self.initial[:, neck_slot:neck_slot+3])
        direction = old_neck.apply(np.tile([0., 1., 0.], (len(points), 1)))
        centered = direction-np.sum(direction*lateral, axis=-1)[:, None]*lateral
        new_neck = Rotation.from_rotvec(align_vectors(direction, centered))*old_neck
        old_head = Rotation.from_rotvec(self.initial[:, head_slot:head_slot+3])
        self.initial[:, neck_slot:neck_slot+3] = new_neck.as_rotvec()
        self.initial[:, head_slot:head_slot+3] = (new_neck.inv()*old_neck*old_head).as_rotvec()
        self.dependencies = np.zeros((len(names)*3, self.width))
        for j in self.order:
            columns = [0, 1, 2]
            ancestor = j
            while ancestor >= 0:
                if ancestor in self.slots:
                    columns.extend(range(self.slots[ancestor], self.slots[ancestor]+3))
                ancestor = self.parents[ancestor]
            self.dependencies[j*3:j*3+3, columns] = 1.

    def decode(self, values):
        points = np.empty((len(values), len(self.names), 3))
        points[:, self.root] = values[:, :3]
        matrices = {}
        rotations = Rotation.from_rotvec(values[:, 3:].reshape(-1,3)).as_matrix().reshape(len(values),len(self.active),3,3)
        identity = np.tile(np.eye(3), (len(values),1,1))
        for j in self.order:
            local = rotations[:, (self.slots[j]-3)//3] if j in self.slots else identity
            parent = self.parents[j]
            matrices[j] = local if parent < 0 else matrices[parent]@local
            if parent >= 0:
                points[:, j] = points[:, parent]+np.einsum('fij,j->fi', matrices[j], self.offsets[j])
        return points


def anatomical_structure_dependencies(rig, points, names):
    """Keep the structure residual Jacobian local to the affected chains."""
    rows = []
    for label in anatomical_structure_residuals(points, names, pose_only=True)[1]:
        reason, joint = label.split(':', 1)
        if reason == 'anatomy_degenerate_bone':
            affected = [joint, names[rig.parents[names.index(joint)]]]
        elif reason == 'anatomy_bilateral_proportions':
            affected = [joint, joint.replace('left_', 'right_', 1)]
            affected += [names[rig.parents[names.index(n)]] for n in affected.copy()]
        elif reason == 'anatomy_socket_alignment':
            suffix = 'hip' if joint == 'pelvis' else 'collar'
            affected = [joint, 'left_'+suffix, 'right_'+suffix]
        elif reason == 'anatomy_hinge_collapse':
            side, hinge = joint.split('_')
            affected = [side+'_'+n for n in (('hip','knee','ankle') if hinge == 'knee' else ('shoulder','elbow','wrist'))]
        elif reason == 'anatomy_spine_deviation':
            affected = ['pelvis', 'neck', joint]
        elif reason == 'anatomy_spine_fold':
            affected = ['pelvis', 'neck', joint, names[rig.parents[names.index(joint)]]]
        elif reason == 'anatomy_neck_fold':
            affected = ['spine3', 'neck', 'head']
        elif reason == 'anatomy_torso_bend':
            affected = ['left_hip', 'right_hip', 'spine1']
            affected += ['left_shoulder', 'right_shoulder'] if joint == 'shoulders' else ['neck']
        elif reason == 'anatomy_chest_attachment':
            affected = ['spine3', 'neck']
            affected += ['left_shoulder', 'right_shoulder'] if joint == 'shoulders' else ['left_collar', 'right_collar']
        else:
            raise ValueError('Missing anatomy residual dependencies: '+reason)
        dependency = joint_dependencies(rig, affected)
        dependency[:3] = 0.
        dependency[rig.slots[rig.root]:rig.slots[rig.root]+3] = 0.
        rows.append(dependency)
    return np.stack(rows)


def body_relative_points(points, names):
    axes = body_orientation_axes(points,names)
    basis = frame_basis(axes[:,1],axes[:,0])
    relative = points-points[:,names.index('pelvis'):names.index('pelvis')+1]
    return np.einsum('fji,fkj->fki',basis,relative)


def relative_motion_quality(points, reference, names, fps):
    """Global translation noise must not hide newly introduced limb jitter."""
    root = names.index('pelvis')
    def acceleration(values):
        relative = values-values[:, root:root+1]
        return np.sqrt(np.mean(np.diff(relative, n=2, axis=0)**2, axis=(0, 2)))
    before, after = acceleration(reference), acceleration(points)
    limits = np.maximum(before*1.2, .003*(30./fps)**2)
    payload = {'fps': fps, 'frames': [
        {'timeSec': i/fps, 'joints': dict(zip(names, current.tolist())),
         'sourceJoints': dict(zip(names, source.tolist()))}
        for i, (current, source) in enumerate(zip(points, reference))]}
    spikes = introduced_joint_spikes(payload)
    rotation = body_orientation_noise(points, names, reference, fps)
    return {'relativeJointShake': bool(np.all(after <= limits) and not spikes['severe']),
            'bodyRotation': not rotation['severe'],
            'jointAccelerationBefore': dict(zip(names, before.tolist())),
            'jointAccelerationAfter': dict(zip(names, after.tolist())),
            'introducedSpikes': spikes, 'rotation': rotation}


def controlled_target(points, names, fps):
    """Positive-kernel smoothing plus bounded local deviation attenuation.

    Local PCA acts after removing linear travel, in a fixed body basis. It
    never locks a world axis, mirrors limbs, or uses an exercise label.
    """
    scale = body_scale(points, names)
    root = names.index('pelvis')
    basis = body_orientation_axes(points, names)
    rotation = frame_basis(basis[:1, 1], basis[:1, 0])[0]
    local = (points-points[:, root:root+1])@rotation
    tracks = np.concatenate([points[:, root:root+1]@rotation, local], axis=1)
    smooth = gaussian_filter1d(tracks, max(.5, fps*.08), axis=0, mode='nearest')
    radius = max(3, round(fps*.6))
    target = smooth.copy()
    corrections = []
    for frame in range(len(points)):
        start, end = max(0, frame-radius), min(len(points), frame+radius+1)
        time = np.arange(start, end, dtype=float)-frame
        design = np.column_stack([np.ones(len(time)), time])
        for joint in range(tracks.shape[1]):
            values = smooth[start:end, joint]
            linear = design@np.linalg.lstsq(design, values, rcond=None)[0]
            residual = values-linear
            _, singular, axes = np.linalg.svd(residual, full_matrices=False)
            if singular[0] < 1e-9:
                continue
            amplitudes = singular/np.sqrt(len(time))
            # Only small components subordinate to a clear main trajectory.
            weights = np.clip(1.-amplitudes/(.015*scale), 0., .8)
            weights[singular > singular[0]*.25] = 0.
            correction = ((residual[frame-start]@axes.T)*weights)@axes
            target[frame, joint] -= correction
            corrections.append(np.linalg.norm(correction))
    target = target[:, 1:]+target[:, :1]
    target = target@rotation.T
    # Quiet intervals encourage settling, without pinning contacts inferred
    # from low speed. Their velocity is a soft objective in the unified fit.
    relative = body_relative_points(points,names)
    hold_radius = max(2, round(fps*.2))
    holds = np.zeros(points.shape[:2])
    for frame in range(len(points)):
        values = relative[max(0,frame-hold_radius):min(len(points),frame+hold_radius+1)]
        span = np.linalg.norm(np.ptp(values, axis=0), axis=-1)
        path = np.sum(np.linalg.norm(np.diff(values,axis=0),axis=-1),axis=0)
        progress = np.linalg.norm(values[-1]-values[0],axis=-1)/np.maximum(path,1e-12)
        # Even very small monotonic motion is movement, not a quiet hold.
        holds[frame] = np.clip(1.-span/(.02*scale),0.,1.)*(1.-np.clip((progress-.4)/.4,0.,1.))
    holds[:, root] = 0.
    return target, holds, {'maximumMinorDeviationCorrectionMeters': float(max(corrections, default=0.)),
                            'smoothingSeconds': .08, 'localWindowSeconds': 1.2}


def excursion_constraints(target, root, scale):
    """Preserve substantial observed excursions while allowing quiet settling.

    Directions follow each joint's actual trajectory, not world axes. Only its
    outer excursion receives a lower bound; small motions remain unconstrained.
    """
    relative = target-target[:, root:root+1]
    center = relative.mean(axis=0)
    centered = relative-center
    radius = np.linalg.norm(centered, axis=-1)
    moving = np.linalg.norm(np.ptp(relative, axis=0), axis=-1) > .1*scale
    active = moving[None, :] & (radius >= .8*radius.max(axis=0))
    return center, np.where(active[:,:,None],unit(centered),0.), .9*radius, active


def hinge_coordinates(points, names):
    """Vectorized version of the final validator's body-local hinge frame."""
    right = unit(points[:,names.index('right_shoulder')]-points[:,names.index('left_shoulder')])
    forward = unit(np.cross(points[:,names.index('neck')]-points[:,names.index('pelvis')],right))
    up = unit(np.cross(right,forward))
    basis = np.stack([right,up,forward],axis=1)
    specs = [spec for spec in ARTICULATIONS if spec[0].endswith(('_knee','_elbow'))]
    parent = np.stack([unit(points[:,names.index(a)]-points[:,names.index(h)]) for _,a,h,_,_ in specs],axis=1)
    child = np.stack([unit(points[:,names.index(b)]-points[:,names.index(h)]) for _,_,h,b,_ in specs],axis=1)
    perpendicular = child-parent*np.sum(child*parent,axis=-1,keepdims=True)
    bend = unit(perpendicular)
    return (np.einsum('fai,fhi->fha',basis,parent),
            np.einsum('fai,fhi->fha',basis,bend),np.linalg.norm(perpendicular,axis=-1))


def transported_hinge_dots(source_parent, source_bend, current_parent, current_bend):
    shape = source_parent.shape
    rotation = Rotation.from_rotvec(align_vectors(source_parent.reshape(-1,3),current_parent.reshape(-1,3)))
    transported = rotation.apply(source_bend.reshape(-1,3)).reshape(shape)
    opposite = np.sum(source_parent*current_parent,axis=-1) < -1.+1e-9
    transported[opposite] = source_bend[opposite]
    return np.sum(transported*current_bend,axis=-1)


def fit_time_budget(payload, timeout_seconds=None):
    """Bound runtime by problem size; an explicit caller deadline takes priority."""
    return float(timeout_seconds) if timeout_seconds is not None else max(150., min(300., 1.5*len(payload.get('frames') or [])))


def solve_trajectory(residual, initial, pattern, max_evaluations):
    # Keep SciPy's absolute step floor near zero. A custom relative diff_step
    # turned tiny but nonzero rotations into falsely unobservable controls.
    return least_squares(residual,initial,jac_sparsity=pattern,
                         max_nfev=max_evaluations,ftol=1e-5,xtol=1e-6,gtol=1e-6,
                         x_scale='jac',tr_options={'maxiter':200})


def joint_dependencies(rig, names):
    return np.max(rig.dependencies[[rig.names.index(name)*3 for name in names]],axis=0)


def rotation_prior_dependencies(width):
    # SO(3) logarithm components couple the three coordinates of each rotation.
    pattern=np.zeros((width-3,width))
    for start in range(3,width,3):
        pattern[start-3:start,start:start+3]=1.
    return pattern


def fit_controlled_motion(payload, *, max_evaluations=25, timeout_seconds=None):
    """Select observed loop boundaries, then fit within one shared time budget."""
    timeout_seconds = fit_time_budget(payload, timeout_seconds)
    if (not (payload.get('loop') or {}).get('enabled') or payload.get('fixedRig')
            or payload.get('loopCycleSelection') or timeout_seconds <= 0):
        return _fit_controlled_motion(payload, max_evaluations=max_evaluations,
                                      timeout_seconds=timeout_seconds)
    from .loop_cycles import rank_loop_cycles, slice_loop_cycle
    started = monotonic()
    choices = rank_loop_cycles(payload, max_candidates=3)
    if not choices:
        return _fit_controlled_motion(payload, max_evaluations=max_evaluations,
                                      timeout_seconds=max(0., timeout_seconds-(monotonic()-started)))
    attempts = []
    for choice in choices:
        remaining = timeout_seconds-(monotonic()-started)
        if remaining <= 0:
            break
        candidate, report = _fit_controlled_motion(slice_loop_cycle(payload, choice),
                                                   max_evaluations=max_evaluations,
                                                   timeout_seconds=remaining)
        attempts.append({'selection': choice, 'reason': report['reason'],
                         'checks': report.get('checks', {}),
                         'elapsedSeconds': report.get('elapsedSeconds', 0.),
                         'fitReport': deepcopy(report)})
        if report['applied']:
            report['cycleSelectionAttempts'] = attempts
            report['elapsedSeconds'] = monotonic()-started
            return candidate, report
    return payload, {'applied': False, 'strategy': CONTROLLED_MOTION_STRATEGY,
                     'reason': 'no_validated_loop_cycle', 'cycleSelectionAttempts': attempts,
                     'elapsedSeconds': monotonic()-started}


def _fit_controlled_motion(payload, *, max_evaluations=25, timeout_seconds=None):
    """Return only a validated fit; otherwise retain the input with a report."""
    started = monotonic()
    timeout_seconds = fit_time_budget(payload, timeout_seconds)
    report = {'applied': False, 'strategy': CONTROLLED_MOTION_STRATEGY, 'timeBudgetSeconds':timeout_seconds}
    if can_reuse_controlled_motion(payload):
        from .scene_placement import normalize_scene_placement
        payload = normalize_scene_placement(payload)
        return payload, {**payload['controlledMotionFit'], 'reused': True}
    frames = payload.get('frames') or []
    names = payload.get('jointNames') or []
    fps = float(payload.get('fps', 0.))
    if len(frames)<7 or len(names)!=len(SMPL_JOINT_NAMES) or set(names)!=set(SMPL_JOINT_NAMES):
        return payload, {**report, 'reason': 'requires_contiguous_smpl_skeleton'}
    times = np.array([f.get('timeSec', np.nan) for f in frames])
    if not np.isfinite(fps) or fps<=0 or not np.isfinite(times).all() or np.max(abs(np.diff(times)-1/fps))>.05/fps:
        return payload, {**report, 'reason': 'irregular_sampling'}
    if any(f.get('syntheticLoopBridge') for f in frames):
        return payload, {**report, 'reason': 'synthetic_bridge_requires_separate_loop_fit'}
    if any(any(n not in f.get('joints',{}) for n in names) for f in frames):
        return payload, {**report, 'reason': 'incomplete_joint_tracks'}
    points = np.array([[f['joints'][n] for n in names] for f in frames], dtype=float)
    if not np.isfinite(points).all():
        return payload, {**report, 'reason': 'nonfinite_input'}
    reference = np.asarray([[f.get('controlledArticulationReferenceJoints',f['joints'])[n] for n in names] for f in frames],dtype=float)
    if not np.isfinite(reference).all():
        return payload, {**report, 'reason': 'nonfinite_articulation_reference'}
    pinned = contact_mask(payload, names, len(frames))
    if pinned is None:
        return payload, {**report, 'reason': 'unrepresented_heel_contact'}
    if (payload.get('postBakeForefootContactConstraint') or {}).get('requiresReconstruction'):
        return payload, {**report, 'reason': 'upstream_contacts_unresolved'}
    root_index = names.index('pelvis')
    if all('controlledArticulationReferenceJoints' in frame for frame in frames):
        source_axes = body_orientation_axes(reference[:1], names)
        baked_axes = body_orientation_axes(points[:1], names)
        rotation = frame_basis(baked_axes[:, 1], baked_axes[:, 0])[0]@frame_basis(source_axes[:, 1], source_axes[:, 0])[0].T
        root_reference = (reference[:, root_index]-reference[0, root_index])@rotation.T+points[0, root_index]
        placement_reference = 'original_source_root_in_baked_frame'
    else:
        root_reference = points[:, root_index].copy()
        placement_reference = 'continuous_input_root'
        if not root_motion_quality(root_reference, fps, body_scale(points, names))['passed']:
            root_reference = gaussian_filter1d(root_reference, max(.5, fps*.08), axis=0, mode='nearest')
            placement_reference = 'smoothed_discontinuous_input_root'
    points, registration = register_contact_placement(points, pinned, root_index, fps, root_reference)
    registration['reference'] = placement_reference
    if registration.get('reason') == 'placement_registration_did_not_converge':
        return payload, {**report, 'reason': registration['reason'], 'placementRegistration': registration}
    points, height_shift = align_registered_contacts_above_floor(
        points, pinned, [names.index(n) for n in ('left_foot', 'right_foot')], payload.get('renderFloorY'))
    registration['floorHeightGaugeCorrectionMeters'] = height_shift
    rig = FixedRig(points, names)
    from .anatomical_repair import repair_residuals, repair_rig_anatomy
    repaired_reference = None
    try:
        initialized_points, anatomy_initialization = repair_rig_anatomy(rig, points, deadline=started+timeout_seconds)
        source_violations, _ = repair_residuals(reference, names)
        if np.any(source_violations > 1e-6):
            if np.array_equal(reference, points):
                repaired_reference, source_anatomy = initialized_points.copy(), dict(anatomy_initialization)
            else:
                reference_rig = FixedRig(reference, names)
                repaired_reference, source_anatomy = repair_rig_anatomy(
                    reference_rig, reference, deadline=started+timeout_seconds)
            report['anatomicalSourceRepair'] = source_anatomy
            if not source_anatomy['passed']:
                return payload, {**report, 'reason': 'anatomical_source_projection_incomplete'}
            reference = repaired_reference
    except TimeoutError:
        return payload, {**report, 'reason': 'fit_timeout', 'elapsedSeconds': monotonic()-started}
    report['anatomicalInitialization'] = anatomy_initialization
    from .rig_playback import rig_contact_targets
    contact_targets, ankle_anchor_calibration = rig_contact_targets(points,names,pinned,rig.offsets)
    target, holds, evidence = controlled_target(rig.decode(rig.initial), names, fps)
    target, _, placement_report = contact_consistent_target(target, pinned, contact_targets)
    evidence['placement'] = placement_report
    evidence['placementRegistration'] = registration
    # Initialize placement from the same contact evidence, retaining all local
    # rotations and the immutable original source used for articulation checks.
    _, initial_shift, _ = contact_consistent_target(initialized_points, pinned, contact_targets)
    rig.initial[:, :3] += initial_shift
    scale = body_scale(points, names)
    excursion_center, excursion_direction, excursion_minimum, excursion_active = excursion_constraints(target, rig.root, scale)
    count, joints, _ = points.shape
    cyclic = bool((payload.get("loop") or {}).get("enabled"))
    specs = [(label, [names.index(n) for n in (a,b,c)], tolerance)
             for label,a,b,c,tolerance in ARTICULATIONS]
    reference_angles = np.stack([angles(*(reference[:,i] for i in cols)) for _,cols,_ in specs], axis=1)
    source_parent, source_bend, source_hinge_sine = hinge_coordinates(reference,names)
    from .structural_refinement import _source_branch_is_temporally_supported
    branch_supported = np.ones(source_hinge_sine.shape,dtype=bool)
    for hinge in range(source_parent.shape[1]):
        track = list(zip(source_parent[:,hinge],source_bend[:,hinge]))
        branch_supported[:,hinge] = [_source_branch_is_temporally_supported(track,frame,max(1,round(fps*.1)))
                                    for frame in range(count)]
    branch_supported &= source_hinge_sine > np.sin(np.deg2rad(15.))
    tolerance = np.deg2rad([min(t, 10.)-.5 for _,_,t in specs])
    low, high = reference_angles-tolerance, reference_angles+tolerance
    for column,(label,_,_) in enumerate(specs):
        if label.endswith('_ankle'):
            low[:,column] = np.maximum(low[:,column], np.deg2rad(35.1))
            high[:,column] = np.minimum(high[:,column], np.deg2rad(164.9))
    # Every residual frame depends only on that frame's rig; temporal blocks
    # share those dependencies across adjacent frames, not the full sequence.
    angle_pattern = np.stack([np.max(rig.dependencies[np.ravel([[j*3+k for k in range(3)] for j in cols])],axis=0)
                              for _,cols,_ in specs])
    collision_pattern = np.stack([np.max(rig.dependencies[np.ravel([[names.index(n)*3+k for k in range(3)] for n in (*a,*b)])],axis=0)
                                  for _,a,b,_,_ in collision_specs(names)])
    body_dependencies = joint_dependencies(rig,('pelvis','left_hip','right_hip','neck'))
    head_pattern = joint_dependencies(rig,('pelvis','left_hip','right_hip','neck','head'))[None,:]
    branch_basis = joint_dependencies(rig,('pelvis','neck','left_shoulder','right_shoulder'))
    branch_pattern = np.stack([np.maximum(branch_basis,joint_dependencies(rig,(a,h,b)))
                               for label,a,h,b,_ in ARTICULATIONS if label.endswith(('_knee','_elbow'))])
    settling_pattern = np.maximum(rig.dependencies,body_dependencies[None,:])
    frame_pattern = np.vstack([rig.dependencies,rig.dependencies,
                               angle_pattern,rig.dependencies[1::3],head_pattern,rotation_prior_dependencies(rig.width),collision_pattern,
                               rig.dependencies[::3],branch_pattern])
    structure_pattern = anatomical_structure_dependencies(rig, points, names)
    frame_pattern = np.vstack([frame_pattern, structure_pattern])
    temporal_pattern = csr_matrix(rig.dependencies)
    root_pattern = csr_matrix(rig.dependencies[rig.root*3:rig.root*3+3])
    d2 = csr_matrix(np.diff(np.eye(count), n=2, axis=0))
    d3 = csr_matrix(np.diff(np.eye(count), n=3, axis=0))
    d1 = csr_matrix(np.diff(np.eye(count), axis=0))
    if cyclic:
        cyclic_first = csr_matrix(np.roll(np.eye(count),-1,axis=0)-np.eye(count))
        d2 = cyclic_first@cyclic_first
        d3 = d2@cyclic_first
    pattern = vstack([kron(eye(count),csr_matrix(frame_pattern)),
                     kron(abs(d2),temporal_pattern), kron(abs(d3),temporal_pattern),
                     kron(abs(d1),csr_matrix(settling_pattern)),
                     kron(abs(d2),root_pattern),
                     kron(abs(d3),root_pattern),
                     kron(abs(d2),csr_matrix(np.tile(body_dependencies, (6, 1))))], format='csr')
    from .rig_playback import sample_rig
    playback_rig = {'jointNames':names,'parents':rig.parents,'order':rig.order,'offsets':rig.offsets,
                    'rotationJointNames':[names[j] for j in rig.active]}
    # Constrain the same quarter-frame locations used by independent playback
    # validation. A subframe alone can miss the maximum of a nonlinear FK arc.
    interval_count = count if cyclic else count-1
    subframe_cursors = (np.arange(interval_count)[:,None]+np.array([.25,.5,.75])).ravel()
    subframe_count = len(subframe_cursors)
    subframe_first = np.floor(subframe_cursors).astype(int)
    subframe_last = (subframe_first+1)%count
    subframe_pinned = pinned[subframe_first]&pinned[subframe_last]
    subframe_targets = contact_targets[subframe_first]
    subframe_pattern = np.vstack([rig.dependencies,rig.dependencies[1::3],collision_pattern,structure_pattern])
    pair_pattern = csr_matrix((np.ones(2*subframe_count),
                               (np.repeat(np.arange(subframe_count),2),
                                np.column_stack([subframe_first,subframe_last]).ravel())),
                              shape=(subframe_count,count))
    pattern = vstack([pattern,kron(pair_pattern,csr_matrix(subframe_pattern))],format='csr')
    if cyclic:
        seam_pattern = np.zeros((2,count));seam_pattern[0,[0,-1,-2]]=1.;seam_pattern[1,[0,1,-1]]=1.
        pattern = vstack([pattern,kron(csr_matrix(seam_pattern),csr_matrix(rig.dependencies))],format='csr')
    initial_rotations = Rotation.from_rotvec(rig.initial[:,3:].reshape(-1,3))
    floor = payload.get('renderFloorY')
    source_head = body_local_head_direction(reference,names)
    def residual(values):
        if monotonic()-started > timeout_seconds:
            raise TimeoutError
        coordinates = values.reshape(count,rig.width)
        candidate = rig.decode(coordinates)
        rotation_prior = .01*(initial_rotations.inv()*Rotation.from_rotvec(coordinates[:,3:].reshape(-1,3))).as_rotvec().reshape(count,-1)
        current_angles = np.stack([angles(*(candidate[:,i] for i in cols)) for _,cols,_ in specs],axis=1)
        articulation = 100.*(np.minimum(current_angles-low,0.)+np.maximum(current_angles-high,0.))
        floor_error = np.zeros((count,joints)) if floor is None else 100.*np.minimum(candidate[:,:,1]-float(floor),0.)/scale
        current_head = body_local_head_direction(candidate,names)
        head_angle = np.arccos(np.clip(np.sum(source_head*current_head,axis=1),-1.,1.))
        head_penalty = 20.*np.maximum(head_angle-np.deg2rad(14.),0.)[:,None]
        excursion_projection = np.sum((candidate-candidate[:,rig.root:rig.root+1]-excursion_center)*excursion_direction,axis=-1)
        excursion_penalty = 20.*np.minimum(excursion_projection-excursion_minimum,0.)*excursion_active/scale
        current_parent, current_bend, current_sine = hinge_coordinates(candidate,names)
        branch_dot = transported_hinge_dots(source_parent,source_bend,current_parent,current_bend)
        branch_penalty = 20.*np.minimum(branch_dot-.2,0.)*branch_supported*np.clip(current_sine/np.sin(np.deg2rad(15.)),0.,1.)
        per_frame = np.concatenate([(2.*(candidate-target)/scale).reshape(count,-1),
                                    (2000.*(candidate-contact_targets)*pinned[:,:,None]/scale).reshape(count,-1),
                                    articulation, floor_error, head_penalty, rotation_prior,
                                    100.*np.minimum(collision_clearances(candidate,names,scale)[0]/scale-COLLISION_FIT_MARGIN_RATIO,0.),
                                    excursion_penalty,branch_penalty,
                                    100.*anatomical_structure_residuals(candidate,names,pose_only=True)[0]],axis=1)
        # Penalize output acceleration and jerk, rather than preserving the
        # input noise through a correction-relative temporal objective.
        root_relative = (candidate-candidate[:,rig.root:rig.root+1])/scale
        acceleration = (d2@root_relative.reshape(count,-1))*(fps*.15)**2
        jerk = (d3@root_relative.reshape(count,-1))*(fps*.10)**3
        relative = body_relative_points(candidate,names)
        settling = np.diff(relative/scale,axis=0)*np.minimum(holds[1:],holds[:-1])[:,:,None]*(fps*2.4)
        # Root-relative coordinates remove translation noise without coupling
        # every limb's temporal derivatives to the moving neck basis. Body-axis
        # acceleration below constrains torso rotation independently.
        root_acceleration = (d2@(candidate[:,rig.root]/scale))*(fps*.10)**2*np.sqrt(joints)
        root_jerk = (d3@(candidate[:,rig.root]/scale))*(fps*.07)**3*np.sqrt(joints)
        orientation_acceleration = (d2@body_orientation_axes(candidate,names).reshape(count,-1))*(fps*.15)**2
        subframe = sample_rig({**playback_rig,'coordinates':coordinates},subframe_cursors,wrap=cyclic)
        subframe_contacts = 2000.*(subframe-subframe_targets)*subframe_pinned[:,:,None]/scale
        subframe_floor = np.zeros((subframe_count,joints)) if floor is None else 100.*np.minimum(subframe[:,:,1]-float(floor),0.)/scale
        subframe_rows = np.concatenate([subframe_contacts.reshape(subframe_count,-1),subframe_floor,
                                        100.*np.minimum(collision_clearances(subframe,names,scale)[0]/scale-COLLISION_FIT_MARGIN_RATIO,0.),
                                        100.*anatomical_structure_residuals(subframe,names,pose_only=True)[0]],axis=1)
        # The final sample precedes the first by one frame. Equal endpoint
        # positions would impose a stop; match the incoming/outgoing increments.
        seam_step = candidate[0]-candidate[-1]
        closure = 100.*np.stack([seam_step-(candidate[-1]-candidate[-2]),
                                (candidate[1]-candidate[0])-seam_step])/scale if cyclic else np.empty(0)
        return np.r_[per_frame.ravel(),acceleration.ravel(),jerk.ravel(),settling.ravel(),
                     root_acceleration.ravel(),root_jerk.ravel(),orientation_acceleration.ravel(),
                     subframe_rows.ravel(),closure.ravel()]
    try:
        if monotonic()-started > timeout_seconds:
            raise TimeoutError
        initial_points = rig.decode(rig.initial)
        already_rigid = np.max(abs(initial_points-target)) < 1e-7
        already_smooth = np.max(np.linalg.norm(np.diff(initial_points,n=3,axis=0),axis=-1))*(fps/30.)**3 < .00003*scale
        anchored = np.max(np.linalg.norm((initial_points-contact_targets)[pinned],axis=-1),initial=0.) < .0005
        already_valid = (not cyclic and already_rigid and already_smooth and anchored
                         and validate_physical_motion(initial_points,names,fps=fps)['passed'])
        if already_valid:
            # Avoid introducing solver noise into an already controlled rig.
            # The same independent acceptance checks still run below.
            solved = SimpleNamespace(x=rig.initial.ravel(),nfev=0)
        else:
            solved = solve_trajectory(residual,rig.initial.ravel(),pattern,max_evaluations)
    except TimeoutError:
        return payload,{**report,'reason':'fit_timeout','elapsedSeconds':monotonic()-started}
    result = rig.decode(solved.x.reshape(count,rig.width))
    bilateral_support = np.all(pinned[:,[names.index(n) for n in ('left_ankle','left_foot','right_ankle','right_foot')]],axis=1)
    physical = validate_physical_motion(result,names,reference=reference,fps=fps,support_mask=bilateral_support)
    # Fixed-rig lengths are checked directly below; source per-frame length
    # fidelity is intentionally superseded, not anatomical/branch checks.
    source_events = physical['events']
    physical['events'] = [e for e in source_events if e['reason'] != 'repair_bone_length_distortion']
    physical['reasons'] = sorted({e['reason'] for e in physical['events']})
    physical['passed'] = not physical['events']
    lengths = np.array([np.linalg.norm(result[:,j]-result[:,rig.parents[j]],axis=1)
                        for j in rig.order[1:]])
    contact_error = float(np.max(np.linalg.norm((result-contact_targets)[pinned],axis=-1),initial=0.))
    change = np.max(abs(np.stack([angles(*(result[:,i] for i in cols)) for _,cols,_ in specs],axis=1)-reference_angles))
    travel_before = np.linalg.norm(np.ptp(target[:,rig.root],axis=0))
    travel_after = np.linalg.norm(np.ptp(result[:,rig.root],axis=0))
    fit_error = float(np.sqrt(np.mean((result-target)**2)))
    jerk_before = float(np.sqrt(np.mean(np.diff(points,n=3,axis=0)**2)))
    jerk_after = float(np.sqrt(np.mean(np.diff(result,n=3,axis=0)**2)))
    target_span = np.linalg.norm(np.ptp(target-target[:,rig.root:rig.root+1],axis=0),axis=-1)
    result_span = np.linalg.norm(np.ptp(result-result[:,rig.root:rig.root+1],axis=0),axis=-1)
    moving = target_span > .1*scale
    range_preserved = bool(np.all(result_span[moving] >= .85*target_span[moving]))
    acceleration_before = np.sqrt(np.mean(np.diff(points,n=2,axis=0)**2,axis=(0,2)))
    acceleration_after = np.sqrt(np.mean(np.diff(result,n=2,axis=0)**2,axis=(0,2)))
    no_new_shake = bool(np.all(acceleration_after <= np.maximum(acceleration_before*1.2,.003*(30./fps)**2)))
    hold_weights = np.minimum(holds[1:],holds[:-1])[:,:,None]
    def settling_speed(values):
        relative = body_relative_points(values,names)
        return float(np.sqrt(np.sum((np.diff(relative,axis=0)*fps*hold_weights)**2)/max(np.sum(hold_weights)*3,1.)))
    settling_before, settling_after = settling_speed(points), settling_speed(result)
    settling_preserved = settling_after <= max(settling_before*1.1,.003)
    relative_quality = relative_motion_quality(result, reference, names, fps)
    root_quality = root_motion_quality(result[:,rig.root], fps, scale)
    checks = {'anatomy':physical['passed'], 'contacts':contact_error<.0005,
              'sourceArticulation':bool(change<np.deg2rad(20.)), 'trajectoryFit':fit_error<.025*scale,
              'rootTravel':bool(travel_before<.05*scale or travel_after>=.9*travel_before),
              'jointRange':range_preserved, 'jointShake':no_new_shake, 'settling':settling_preserved,
              'jerk':jerk_after<=jerk_before*1.05+1e-7,
              'fixedRig':bool(np.max(np.ptp(lengths,axis=1))<1e-9),
              'relativeJointShake':relative_quality['relativeJointShake'],
              'bodyRotation':relative_quality['bodyRotation'],
              'rootContinuity':root_quality['passed']}
    accepted = all(checks.values())
    report.update(evidence=evidence,checks=checks,reason='validated_controlled_motion' if accepted else 'fit_validation_failed',
                  applied=bool(accepted),evaluations=solved.nfev,elapsedSeconds=monotonic()-started,
                  maximumBoneLengthVariationMeters=float(np.max(np.ptp(lengths,axis=1))),
                  maximumContactErrorMeters=contact_error,maximumArticulationChangeDegrees=float(np.rad2deg(change)),
                  targetRmsMeters=fit_error,
                  jointTargetRmsMeters={n:float(np.sqrt(np.mean((result[:,j]-target[:,j])**2))) for j,n in enumerate(names)},
                  jerkBefore=jerk_before,jerkAfter=jerk_after,
                  rangePreserved=range_preserved,noNewJointShake=no_new_shake,
                  jointRangeRatios={names[j]:float(result_span[j]/target_span[j]) for j in np.flatnonzero(moving)},
                  settlingSpeedBefore=settling_before,settlingSpeedAfter=settling_after,settlingPreserved=settling_preserved,
                  relativeMotionQuality=relative_quality,
                  rootMotionQuality=root_quality,
                  physicalReasons=physical['reasons'],physicalEvents=physical['events'][:12],
                  balance=physical['balance'],balancePolicy='advisory_only',
                  maximumAnkleAnchorCalibrationMeters=ankle_anchor_calibration)
    if not accepted:
        return payload,report
    candidate = deepcopy(payload)
    if repaired_reference is not None:
        candidate['anatomicalSourceRepair'] = report['anatomicalSourceRepair']
        for frame, corrected in zip(candidate['frames'], repaired_reference):
            frame['correctedAnatomicalReferenceJoints'] = dict(zip(names, corrected.tolist()))
    # New fitted anchors belong to the current frame, not an older placement.
    candidate.pop('scenePlacement', None)
    for frame,values,registered_source in zip(candidate['frames'],result,points):
        frame['controlledSourceJoints']={n:v.tolist() for n,v in zip(names,registered_source)}
        frame['joints']={n:v.tolist() for n,v in zip(names,values)}
    candidate['fixedRig']={'version':1,'jointNames':names,'parents':rig.parents,'order':rig.order,'offsets':rig.offsets.tolist(),
                           'rotationJointNames':[names[j] for j in rig.active],
                           'coordinates':solved.x.reshape(count,rig.width).tolist()}
    transport_corrected_bone_sides(frames,candidate)
    refresh_motion_bounds(candidate)
    from .scene_placement import normalize_scene_placement
    candidate = normalize_scene_placement(candidate)
    candidate.setdefault('loop',{'enabled':False})
    from .rig_playback import validate_rig_playback
    playback = validate_rig_playback(candidate)
    report['playback'] = playback
    report['checks']['playback'] = playback['passed']
    if cyclic:
        report['checks']['loopSeam'] = playback['seamContinuous']
    if cyclic and not playback['seamContinuous']:
        report.update(applied=False,reason='loop_requires_cycle_repair')
        report['checks']['loopSeam']=False
        return payload,report
    if not playback['passed']:
        report.update(applied=False,reason='playback_validation_failed')
        return payload,report
    if candidate.get('loop',{}).get('enabled'):
        candidate['loop'] = {**candidate['loop'],'transition':'continuous',
                             'restartFadeMillis':0}
    candidate.pop('sequenceStabilization', None)
    report['outputPoseDigest']=pose_digest(candidate)
    return candidate,report

def main():
    """Run an isolated comparison without replacing a library artifact."""
    import argparse
    import json
    from pathlib import Path
    from .preview import write_baked_preview_html
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('output_directory', type=Path)
    parser.add_argument('--max-evaluations', type=int, default=25)
    parser.add_argument('--timeout-seconds', type=float, help='Override the frame-count-based 150-300 second solve budget.')
    args = parser.parse_args()
    if args.max_evaluations < 1 or (args.timeout_seconds is not None and args.timeout_seconds <= 0):
        parser.error('Solver bounds must be positive.')
    output = args.output_directory.resolve()
    if args.input.resolve() == output/'motion.json':
        parser.error('Comparison output must not overwrite the input.')
    payload = json.loads(args.input.read_text(encoding='utf-8'))
    candidate, report = fit_controlled_motion(payload, max_evaluations=args.max_evaluations,
                                             timeout_seconds=args.timeout_seconds)
    candidate = deepcopy(candidate)
    candidate['controlledMotionFit'] = report
    output.mkdir(parents=True, exist_ok=True)
    (output/'motion.json').write_text(json.dumps(candidate), encoding='utf-8')
    (output/'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    write_baked_preview_html(output/'preview.html', candidate)
    print(json.dumps(report, indent=2))
    return 0 if report['applied'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
