"""Default final-bake fixed-rig trajectory fit; legacy output remains available."""
from __future__ import annotations

from copy import deepcopy
from time import monotonic
from types import SimpleNamespace
import numpy as np
from scipy.ndimage import gaussian_filter1d
from scipy.optimize import least_squares
from scipy.optimize._numdiff import approx_derivative, group_columns
from scipy.sparse import csr_matrix, eye, kron, vstack
from scipy.spatial.transform import Rotation

from .sequence_stabilization import contact_mask, frame_basis, pose_digest, unit
from .smpl_joint_names import SMPL_JOINT_NAMES, SMPL_JOINT_PARENTS
from .physical_validation import ARTICULATIONS, angles, body_scale, collision_clearances, collision_specs, validate_physical_motion, anatomical_structure_residuals
from .temporal_quality import body_orientation_axes, body_orientation_noise, body_local_head_direction, introduced_joint_spikes, refresh_motion_bounds, transport_corrected_bone_sides
from .motion_placement import contact_consistent_target, root_motion_quality, register_contact_placement, align_registered_contacts_above_floor
from .rig_interpolation import INTERPOLATION

CONTROLLED_MOTION_STRATEGY = 'fixed_rig_controlled_motion_v50_observed_surface_authority'
# Soft temporal penalties compete with pose/contact fitting. Target below the
# acceptance boundary so a finite solver budget does not settle just outside it.
TEMPORAL_FIT_TARGET_RATIO = .8
CONTACT_FIT_WEIGHT = 10. / (.8 * .0005)
# Leave clearance in the proposal; do not optimize against the validator's
# permitted penetration boundary at interpolated frames.
COLLISION_FIT_MARGIN_RATIO = .0025
ANATOMY_FIT_MARGIN = .0001
ANATOMY_FIT_WEIGHT = 10000.
# Keep pre-solve stages from consuming the whole candidate fit budget, while
# still allowing hard anatomy/support repairs enough wall-clock to finish well.
ANATOMY_REPAIR_TIME_FRACTION = .35
ANATOMY_REPAIR_MIN_SECONDS = 75.
SUPPORT_INIT_TIME_FRACTION = .3
SUPPORT_INIT_MIN_SECONDS = 60.
SUPPORT_INIT_WARM_START_EVALUATIONS = 20
SUPPORT_INIT_COLD_EVALUATIONS = 40
HEAD_ARTICULATION_FIT_WEIGHT = 1000.
REQUIRED_FIT_CHECKS = ('anatomy', 'contacts', 'sourceArticulation', 'trajectoryFit',
                       'rootTravel', 'jointRange', 'jointShake', 'settling', 'jerk',
                       'fixedRig', 'playback', 'relativeJointShake', 'bodyRotation', 'rootContinuity', 'equipment', 'motionDiscontinuity', 'bodySupport', 'supportAlignment')


def controlled_fit_processing_incomplete(report):
    """A deadline is missing processing evidence, not a failed geometry check."""
    if not isinstance(report, dict) or report.get('applied'):
        return False
    return (report.get('reason') in {'fit_timeout', 'fit_evaluation_limit'}
            or report.get('optimizerTermination') in {'time_budget', 'evaluation_limit'}) or any(
        controlled_fit_processing_incomplete(attempt.get('fitReport', attempt))
        for attempt in report.get('cycleSelectionAttempts', [])
    )


def hard_trajectory_and_root_failure(checks):
    """True when both hard geometric acceptance checks already failed."""
    if not isinstance(checks, dict) or not checks:
        return False
    return checks.get('trajectoryFit') is False and checks.get('rootTravel') is False


def seam_or_playback_only_failure(report):
    """True when the body fit is otherwise OK and only loop closure failed.

    Another observed slice is low-EV after a full near-miss: soft refinement
    rarely invents seam continuity, and a cold second cycle often burns the
    remaining budget without a keep. Prefer stopping this pass and resuming.
    """
    if not isinstance(report, dict) or report.get('applied'):
        return False
    if report.get('reason') not in {
        'loop_requires_cycle_repair',
        'playback_validation_failed',
    }:
        return False
    checks = report.get('checks')
    if not isinstance(checks, dict) or not checks:
        return True
    failed = {name for name, passed in checks.items() if passed is False}
    return bool(failed) and failed <= {'loopSeam', 'playback'}


def controlled_fit_unusable_for_more_preview_work(report):
    """Stop sibling preview loops/variants when more fitting cannot produce a selectable clip."""
    if not isinstance(report, dict) or report.get('applied'):
        return False
    if controlled_fit_processing_incomplete(report):
        return True
    if report.get('reason') in {
        'fit_validation_failed',
        'no_validated_loop_cycle',
        'source_cycle_preflight_rejected',
        'pre_fit_source_articulation_fidelity_failed',
        'loop_requires_cycle_repair',
        'playback_validation_failed',
    }:
        return True
    if seam_or_playback_only_failure(report):
        return True
    return hard_trajectory_and_root_failure(report.get('checks'))


def can_reuse_controlled_motion(payload):
    from .support_geometry import validate_support_geometry, validate_supported_shoe_orientation
    from .support_alignment import validate_payload_alignment
    report = payload.get('controlledMotionFit') or {}
    checks = report.get('checks') or {}
    return bool(payload.get('fixedRig') and report.get('applied')
                and report.get('strategy') == CONTROLLED_MOTION_STRATEGY
                and all(checks.get(key) is True for key in REQUIRED_FIT_CHECKS)
                and all(value is True for value in checks.values())
                and validate_support_geometry(payload)['passed']
                and validate_payload_alignment(payload)['passed']
                and validate_supported_shoe_orientation(payload)['passed']
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
        self.project_neck_attachment(maximum_lateral_ratio=0.)
        self.dependencies = np.zeros((len(names)*3, self.width))
        for j in self.order:
            columns = [0, 1, 2]
            ancestor = j
            while ancestor >= 0:
                if ancestor in self.slots:
                    columns.extend(range(self.slots[ancestor], self.slots[ancestor]+3))
                ancestor = self.parents[ancestor]
            self.dependencies[j*3:j*3+3, columns] = 1.

    def project_neck_attachment(self, *, maximum_lateral_ratio):
        """Clamp socket offset analytically, retaining length and head direction."""
        neck, head = self.names.index('neck'), self.names.index('head')
        left, right = (self.offsets[self.names.index(n)] for n in ('left_collar', 'right_collar'))
        span = right-left
        width = np.linalg.norm(span)
        lateral = unit(span)
        center = np.dot((left+right)*.5, lateral)
        neck_slot, head_slot = self.slots[neck], self.slots[head]
        old_neck = Rotation.from_rotvec(self.initial[:, neck_slot:neck_slot+3])
        vectors = old_neck.apply(np.tile(self.offsets[neck], (len(self.initial), 1)))
        component = vectors @ lateral
        limit = maximum_lateral_ratio*width
        length = np.linalg.norm(self.offsets[neck])
        corrected = np.clip(center+np.clip(component-center, -limit, limit), -length, length)
        orthogonal = vectors-component[:, None]*lateral
        magnitude = np.linalg.norm(orthogonal, axis=1, keepdims=True)
        fallback = unit(np.cross(lateral, np.eye(3)[np.argmin(abs(lateral))]))
        direction = np.where(magnitude > 1e-12, orthogonal/np.maximum(magnitude, 1e-12), fallback)
        target = direction*np.sqrt(np.maximum(length**2-corrected**2, 0.))[:, None]+corrected[:, None]*lateral
        new_neck = Rotation.from_rotvec(align_vectors(vectors, target))*old_neck
        old_head = Rotation.from_rotvec(self.initial[:, head_slot:head_slot+3])
        self.initial[:, neck_slot:neck_slot+3] = new_neck.as_rotvec()
        self.initial[:, head_slot:head_slot+3] = (new_neck.inv()*old_neck*old_head).as_rotvec()

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


def weighted_settling_speed(points, names, fps, weights):
    relative = body_relative_points(points, names)
    return float(np.sqrt(np.sum((np.diff(relative, axis=0)*fps*weights)**2)
                         / max(np.sum(weights)*3, 1.)))


def root_relative_acceleration(points, names):
    root = names.index('pelvis')
    relative = points-points[:, root:root+1]
    return np.sqrt(np.mean(np.diff(relative, n=2, axis=0)**2, axis=(0, 2)))


def relative_motion_quality(points, reference, names, fps):
    """Global translation noise must not hide newly introduced limb jitter."""
    before = root_relative_acceleration(reference, names)
    after = root_relative_acceleration(points, names)
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


def temporal_fit_scales(reference, names, fps):
    """Normalize temporal residuals by the independent acceptance budgets."""
    acceleration = root_relative_acceleration(reference, names)
    acceleration_limit = np.maximum(acceleration*1.2, .003*(30./fps)**2)
    rotation = body_orientation_noise(reference, names, reference, fps)
    rotation_limit = np.deg2rad(rotation['limitDegreesAt30Hz'])*(30./fps)**2
    count = len(reference)-2
    return (TEMPORAL_FIT_TARGET_RATIO*acceleration_limit*np.sqrt(count*3),
            TEMPORAL_FIT_TARGET_RATIO*rotation_limit*np.sqrt(count*2))


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
    if timeout_seconds is not None:
        return float(timeout_seconds)
    frames = len(payload.get('frames') or [])
    # One bounded bump so multi-cycle observed fits can finish without per-exercise overrides.
    return max(180., min(360., 2.5 * frames))


def _stage_deadline(fit_started, timeout_seconds, *, fraction, minimum_seconds):
    """Bound a pre-solve stage so the main trajectory still gets wall-clock."""
    stage_budget = max(float(minimum_seconds), float(fraction) * float(timeout_seconds))
    fit_deadline = float(fit_started) + float(timeout_seconds)
    return min(fit_deadline, monotonic() + stage_budget)


def _support_cache_key(evidence, points, names):
    stationary = tuple(evidence.get('stationaryJoints') or [])
    if not stationary:
        return None
    indices = [names.index(name) for name in stationary if name in names]
    if not indices:
        return None
    median = np.median(points[:, indices], axis=0)
    digest = np.round(median, 3).tobytes()
    groups = tuple(
        (tuple(group.get('joints') or []), tuple(np.round(group.get('normal') or [0., 1., 0.], 4)))
        for group in (evidence.get('coplanarGroups') or [])
    )
    return (stationary, groups, digest)


def _resample_rig_coordinates(coordinates, new_count):
    coords = np.asarray(coordinates, dtype=float)
    if coords.ndim != 2 or new_count < 1:
        return None
    if len(coords) == new_count:
        return coords.copy()
    t_old = np.linspace(0., 1., len(coords))
    t_new = np.linspace(0., 1., new_count)
    out = np.empty((new_count, coords.shape[1]), dtype=float)
    for column in range(coords.shape[1]):
        out[:, column] = np.interp(t_new, t_old, coords[:, column])
    return out


def solve_trajectory(residual, initial, pattern, max_evaluations):
    # Use an absolute perturbation throughout the solve. Relative steps shrink
    # toward cancellation at tiny rotations, especially under stiff penalties.
    # Reuse the coloring; one-sided grouped differences avoid doubling all FK
    # and interpolated-frame evaluations as central differences would.
    groups = group_columns(pattern)
    def jacobian(values):
        return approx_derivative(residual, values, method='2-point',
            abs_step=np.sqrt(np.finfo(float).eps), sparsity=(pattern, groups))
    return least_squares(residual,initial,jac=jacobian,
                         max_nfev=max_evaluations,ftol=1e-6,xtol=None,gtol=1e-6,
                         x_scale='jac',tr_options={'maxiter':600})


def joint_dependencies(rig, names):
    return np.max(rig.dependencies[[rig.names.index(name)*3 for name in names]],axis=0)


def rotation_prior_dependencies(width):
    # SO(3) logarithm components couple the three coordinates of each rotation.
    pattern=np.zeros((width-3,width))
    for start in range(3,width,3):
        pattern[start-3:start,start:start+3]=1.
    return pattern


def fit_controlled_motion(payload, *, max_evaluations=None, timeout_seconds=None):
    """Schedule numerical fitting separately from concurrent browser/review work."""
    from .fit_runtime import cpu_fit_slot
    with cpu_fit_slot() as waited:
        result, report = _fit_candidate_motion(
            payload, max_evaluations=max_evaluations, timeout_seconds=timeout_seconds)
    report['cpuFitQueueWaitSeconds'] = waited
    return result, report


def _fit_candidate_motion(payload, *, max_evaluations=None, timeout_seconds=None):
    """Reuse equivalent fits and share one deadline across candidate variants."""
    from .fit_runtime import current_fit_session, fit_input_key
    session = current_fit_session()
    if session is None:
        return _fit_observed_cycles(payload, max_evaluations=max_evaluations, timeout_seconds=timeout_seconds)
    key = fit_input_key({'payload': payload, 'maxEvaluations': max_evaluations,
                         'timeoutSeconds': timeout_seconds})
    if key in session.results:
        session.reused_fits += 1
        result, report = deepcopy(session.results[key])
        report['reusedCandidateFit'] = True
        return result, report
    remaining = session.remaining()
    if remaining <= 0:
        return payload, {'applied': False, 'strategy': CONTROLLED_MOTION_STRATEGY,
                         'reason': 'fit_timeout', 'budgetOwner': 'candidate', 'elapsedSeconds': 0.}
    session.fit_calls += 1
    try:
        # Cycle attempts share one deadline. When using the frame-scaled default,
        # allow up to 2x that base if the candidate session still has time so a
        # short single-fit floor cannot leave usable budget stranded mid-cycle.
        # Explicit caller deadlines stay hard caps.
        base = fit_time_budget(payload, timeout_seconds)
        if timeout_seconds is None:
            allocated = min(remaining, max(base, min(remaining, 2.0 * base)))
        else:
            allocated = min(remaining, base)
        result, report = _fit_observed_cycles(payload, max_evaluations=max_evaluations,
            timeout_seconds=allocated)
    finally:
        session.save()
    report['candidateFitBudget'] = {'seconds': session.budget_seconds,
        'remainingSeconds': session.remaining(), 'fitCalls': session.fit_calls,
        'reusedFits': session.reused_fits, 'reusedAnatomyFrames': session.reused_frames}
    session.results[key] = deepcopy((result, report))
    return result, report


def _fit_observed_cycles(payload, *, max_evaluations=None, timeout_seconds=None):
    """Select observed loop boundaries, then fit within one shared time budget."""
    timeout_seconds = fit_time_budget(payload, timeout_seconds)
    if (not (payload.get('loop') or {}).get('enabled') or payload.get('fixedRig')
            or payload.get('loopCycleSelection') or timeout_seconds <= 0):
        return _fit_controlled_motion(payload, max_evaluations=max_evaluations,
                                      timeout_seconds=timeout_seconds)
    from .loop_cycles import rank_loop_cycles, slice_loop_cycle
    started = monotonic()
    choices = (payload['observedCycleProposals'] if 'observedCycleProposals' in payload
               else rank_loop_cycles(payload, max_candidates=3))
    if not choices:
        if 'observedCycleProposals' in payload:
            return payload, {'applied': False, 'strategy': CONTROLLED_MOTION_STRATEGY,
                             'reason': 'source_cycle_preflight_rejected',
                             'sourceCyclePreflight': payload.get('sourceCyclePreflight', []),
                             'elapsedSeconds': monotonic() - started}
        return _fit_controlled_motion(payload, max_evaluations=max_evaluations,
                                      timeout_seconds=max(0., timeout_seconds-(monotonic()-started)))
    attempts = []
    shared_support = {}
    for index, choice in enumerate(choices):
        remaining = timeout_seconds-(monotonic()-started)
        sliced = slice_loop_cycle(payload, choice)
        # Give the current ranked cycle all remaining time. Even-splitting left
        # ~120s slices that were consumed by support init alone. Only start a
        # later proposal when leftover still covers a real frame-scaled fit.
        if remaining <= 0:
            break
        if index > 0 and remaining < fit_time_budget(sliced):
            break
        attempt_timeout = remaining
        candidate, report = _fit_controlled_motion(
            sliced,
            max_evaluations=max_evaluations,
            timeout_seconds=attempt_timeout,
            shared_support=shared_support,
        )
        attempts.append({'selection': choice, 'reason': report['reason'],
                         'checks': report.get('checks', {}),
                         'elapsedSeconds': report.get('elapsedSeconds', 0.),
                         'fitReport': deepcopy(report)})
        if report['applied']:
            report['cycleSelectionAttempts'] = attempts
            report['elapsedSeconds'] = monotonic()-started
            return candidate, report
        # Another observed slice will not repair a collapsed root track or a
        # trajectory that already missed both hard geometric checks.
        if hard_trajectory_and_root_failure(report.get('checks')):
            break
        # Seam/playback-only near-miss: stop this pass instead of a cold second
        # ranked window that rarely converts. Resume can retry later.
        if seam_or_playback_only_failure(report):
            break
    return payload, {'applied': False, 'strategy': CONTROLLED_MOTION_STRATEGY,
                     'reason': 'no_validated_loop_cycle', 'cycleSelectionAttempts': attempts,
                     'elapsedSeconds': monotonic()-started}


def _fit_controlled_motion(payload, *, max_evaluations=None, timeout_seconds=None, shared_support=None):
    """Return only a validated fit; otherwise retain the input with a report."""
    allow_refinement = max_evaluations is None
    if max_evaluations is None:
        frames = len(payload.get('frames') or [])
        max_evaluations = max(25, min(40, (frames // 3) or 25))
    started = monotonic()
    timeout_seconds = fit_time_budget(payload, timeout_seconds)
    report = {'applied': False, 'strategy': CONTROLLED_MOTION_STRATEGY, 'timeBudgetSeconds':timeout_seconds}
    optimization_deadline = started+timeout_seconds-min(5., max(0., timeout_seconds)*.05)
    from .body_support_observation import materialize_stationary_sole_support
    materialize_stationary_sole_support(payload)
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
    # Keep temporal evidence immutable across camera/contact/anatomy variants.
    temporal_reference = reference.copy()
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
    from .contact_constraints import observed_ground_contact_mask
    ground_contacts = observed_ground_contact_mask(payload.get('sourceFootSupportEvidence'), names, len(frames))
    points, registration = register_contact_placement(points, pinned, root_index, fps, root_reference,
                                                     ground_contacts=ground_contacts, floor=payload.get('renderFloorY'))
    registration['reference'] = placement_reference
    if registration.get('reason') == 'placement_registration_did_not_converge':
        return payload, {**report, 'reason': registration['reason'], 'placementRegistration': registration}
    height_shift = 0.
    if not registration.get('observedGroundEpisodes'):
        points, height_shift = align_registered_contacts_above_floor(
            points, pinned, [names.index(n) for n in ('left_foot', 'right_foot')], payload.get('renderFloorY'))
    registration['floorHeightGaugeCorrectionMeters'] = height_shift
    report['placementRegistration'] = registration
    rig = FixedRig(points, names)
    from .anatomical_repair import repair_residuals, repair_rig_anatomy, transport_equivalent_anatomical_repair
    repaired_reference = None
    try:
        anatomy_deadline = _stage_deadline(
            started, timeout_seconds,
            fraction=ANATOMY_REPAIR_TIME_FRACTION,
            minimum_seconds=ANATOMY_REPAIR_MIN_SECONDS,
        )
        initialized_points, anatomy_initialization = repair_rig_anatomy(
            rig, points, deadline=anatomy_deadline)
        source_violations, _ = repair_residuals(reference, names)
        if np.any(source_violations > 1e-6):
            repaired_reference = transport_equivalent_anatomical_repair(points, initialized_points, reference, names)
            if repaired_reference is not None:
                # Repositioning the source does not require solving its same
                # malformed frames twice. Articulation changes cannot reuse it.
                source_anatomy = {**anatomy_initialization, 'reusedInitialization': True,
                                  'evaluations': 0, 'residualBatchCount': 0, 'residualPointCount': 0,
                                  'warmStartedFrameCount': 0}
            else:
                reference_rig = FixedRig(reference, names)
                repaired_reference, source_anatomy = repair_rig_anatomy(
                    reference_rig, reference, deadline=anatomy_deadline)
            report['anatomicalSourceRepair'] = source_anatomy
            if not source_anatomy['passed']:
                return payload, {**report, 'reason': 'anatomical_source_projection_incomplete'}
            reference = repaired_reference
    except TimeoutError:
        return payload, {**report, 'reason': 'fit_timeout', 'elapsedSeconds': monotonic()-started}
    report['anatomicalInitialization'] = anatomy_initialization
    from .rig_playback import rig_contact_targets
    contact_targets, ankle_anchor_calibration = rig_contact_targets(
        points,names,pinned,rig.offsets,evidence=payload.get('sourceFootSupportEvidence'), floor=payload.get('renderFloorY'))
    from .equipment_constraints import calibrated_grip_constraint, grip_residual, validate_grip
    equipment = calibrated_grip_constraint(payload, points, names)
    from .support_geometry import support_evidence, calibrate_support_pose, validate_support_geometry, geometry_errors, geometry_dependencies
    body_support = support_evidence(payload)
    from .support_alignment import (alignment_features, alignment_constraint_errors, alignment_dependencies,
                                    validate_alignment, payload_alignment_reference)
    alignment_source = payload_alignment_reference(payload)
    if alignment_source is None:
        # Preserve valid source structure, not a malformed relationship that
        # the preceding anatomical projection has already had to repair.
        alignment_source = (initialized_points if anatomy_initialization.get('sourceViolations') else points).copy()
    source_alignment = alignment_features(alignment_source, names, body_support)
    support_range_reference = initialized_points.copy()
    if body_support.get('required'):
        support_started = monotonic()
        support_key = _support_cache_key(body_support, points, names)
        reused_pose = (
            isinstance(shared_support, dict)
            and support_key is not None
            and shared_support.get('supportKey') == support_key
            and shared_support.get('supportPose') is not None
        )
        if reused_pose:
            support_pose = np.asarray(shared_support['supportPose'], dtype=float)
            support_calibration = {
                **deepcopy(shared_support.get('supportCalibration') or {}),
                'reusedAcrossCycles': True,
                'elapsedSeconds': 0.,
            }
        else:
            support_pose, support_calibration = calibrate_support_pose(
                rig, points, body_support, alignment_reference=alignment_source)
            support_calibration['elapsedSeconds'] = monotonic()-support_started
        report['supportCalibration'] = support_calibration
        if support_pose is None:
            return payload, {**report, 'reason': 'supported_body_evidence_or_geometry_unresolved'}
        for name in body_support.get('stationaryJoints', []):
            index = names.index(name)
            pinned[:, index] = True
        # Apply observed anchors before calibrating linked toe/ankle targets.
        # Replacing a toe afterward leaves an overlapping ankle stance pinned
        # to a different, physically incompatible foot segment.
        contact_targets, ankle_anchor_calibration = rig_contact_targets(
            points, names, pinned, rig.offsets,
            stationary_positions={name: support_pose[names.index(name)]
                                  for name in body_support.get('stationaryJoints', [])},
            evidence=payload.get('sourceFootSupportEvidence'), floor=payload.get('renderFloorY'))
        from .support_geometry import initialize_supported_motion
        warm_started = False
        if isinstance(shared_support, dict) and shared_support.get('supportInitializedCoordinates') is not None:
            warm = _resample_rig_coordinates(
                shared_support['supportInitializedCoordinates'], len(points))
            if warm is not None and warm.shape == rig.initial.shape and np.isfinite(warm).all():
                rig.initial[:] = warm
                warm_started = True
                support_calibration['warmStartedFromPriorCycle'] = True
        support_deadline = _stage_deadline(
            started, timeout_seconds,
            fraction=SUPPORT_INIT_TIME_FRACTION,
            minimum_seconds=SUPPORT_INIT_MIN_SECONDS,
        )
        projection_evals = (
            SUPPORT_INIT_WARM_START_EVALUATIONS if warm_started else SUPPORT_INIT_COLD_EVALUATIONS
        )
        try:
            initialized_points = initialize_supported_motion(
                rig, points, body_support, support_pose, support_calibration,
                support_deadline, fps=fps, alignment_reference=alignment_source,
                pinned=pinned, contact_targets=contact_targets, equipment=equipment,
                max_evaluations=projection_evals)
            report['supportInitializationSeconds'] = monotonic()-support_started
        except TimeoutError:
            return payload, {**report, 'reason': 'fit_timeout', 'elapsedSeconds': monotonic()-started}
        if isinstance(shared_support, dict) and support_key is not None:
            shared_support['supportKey'] = support_key
            shared_support['supportPose'] = np.asarray(support_pose, dtype=float).copy()
            shared_support['supportCalibration'] = deepcopy(support_calibration)
            shared_support['supportInitializedCoordinates'] = rig.initial.copy()
        report['supportReferenceGeometry'] = validate_support_geometry(payload, initialized_points, names)
        report['supportReferenceAlignment'] = validate_alignment(initialized_points, alignment_source, names, body_support)
        report['supportReferenceEquipment'] = validate_grip(initialized_points, names, equipment)
        reference_contact_error = float(np.max(
            np.linalg.norm((initialized_points-contact_targets)[pinned], axis=-1), initial=0.))
        report['supportReferenceContacts'] = {'passed': reference_contact_error < .0005,
                                             'maximumErrorMeters': reference_contact_error}
        reference_errors, reference_labels = repair_residuals(initialized_points, names)
        failed_reference_features = np.max(reference_errors, axis=0) > 1e-6
        report['supportReferenceAnatomy'] = {
            'passed': not bool(np.any(failed_reference_features)),
            'violations': [reference_labels[j] for j in np.flatnonzero(failed_reference_features)],
            'residualByViolation': {reference_labels[j]: float(np.max(reference_errors[:, j]))
                                    for j in np.flatnonzero(failed_reference_features)}}
        if not all(report[key]['passed'] for key in (
                'supportReferenceGeometry', 'supportReferenceAlignment', 'supportReferenceAnatomy',
                'supportReferenceEquipment', 'supportReferenceContacts')):
            return payload, {**report, 'reason': 'support_reference_projection_incomplete'}
        # Explicit support owns these corrections. Keep the original temporal
        # evidence unchanged, but compare articulation to the feasible supported
        # pose rather than requiring reproduction of the unsupported geometry.
        reference = initialized_points.copy()
        report['supportReferenceCorrection'] = {'source': body_support.get('source'),
            'maximumCorrectionMeters': float(np.max(np.linalg.norm(reference-points, axis=-1)))}
    target, holds, evidence = controlled_target(rig.decode(rig.initial), names, fps)
    _, holds, _ = controlled_target(temporal_reference, names, fps)
    jerk_before = float(np.sqrt(np.mean(np.diff(temporal_reference, n=3, axis=0)**2)))
    jerk_limit = jerk_before * 1.05 + 1e-7
    hold_weights = np.minimum(holds[1:], holds[:-1])[:, :, None]
    settling_before = weighted_settling_speed(temporal_reference, names, fps, hold_weights)
    settling_limit = max(settling_before * 1.1, .003)
    report['temporalReference'] = 'source_articulation_before_repairs'
    target, _, placement_report = contact_consistent_target(target, pinned, contact_targets)
    evidence['placement'] = placement_report
    evidence['placementRegistration'] = registration
    # Initialize placement from the same contact evidence, retaining all local
    # rotations and the immutable original source used for articulation checks.
    _, initial_shift, _ = contact_consistent_target(initialized_points, pinned, contact_targets)
    if not body_support.get('required'):
        rig.initial[:, :3] += initial_shift
    scale = body_scale(points, names)
    excursion_center, excursion_direction, excursion_minimum, excursion_active = excursion_constraints(target, rig.root, scale)
    count, joints, _ = points.shape
    cyclic = bool((payload.get("loop") or {}).get("enabled"))
    specs = [(label, [names.index(n) for n in (a,b,c)], tolerance)
             for label,a,b,c,tolerance in ARTICULATIONS]
    reference_angles = np.stack([angles(*(reference[:,i] for i in cols)) for _,cols,_ in specs], axis=1)
    acceleration_fit_scale, rotation_fit_scale = temporal_fit_scales(temporal_reference, names, fps)
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
    equipment_pattern = (joint_dependencies(rig, equipment['endpointPair'])[None, :]
                         if equipment.get('available') else np.empty((0, rig.width)))
    frame_pattern = np.vstack([frame_pattern, equipment_pattern])
    support_pattern = np.vstack([geometry_dependencies(rig, body_support), alignment_dependencies(rig, body_support)])
    frame_pattern = np.vstack([frame_pattern, support_pattern])
    temporal_pattern = csr_matrix(rig.dependencies)
    root_pattern = csr_matrix(rig.dependencies[rig.root*3:rig.root*3+3])
    d2 = csr_matrix(np.diff(np.eye(count), n=2, axis=0))
    d3 = csr_matrix(np.diff(np.eye(count), n=3, axis=0))
    # Acceptance measures world-space differences over the observed interval.
    # Cyclic seam constraints remain separate and are checked in playback.
    world_d3 = d3.copy()
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
                    'rotationJointNames':[names[j] for j in rig.active],
                    'interpolation': INTERPOLATION}
    # Constrain the same quarter-frame locations used by independent playback
    # validation. A subframe alone can miss the maximum of a nonlinear FK arc.
    interval_count = count if cyclic else count-1
    subframe_cursors = (np.arange(interval_count)[:,None]+np.array([.25,.5,.75])).ravel()
    subframe_count = len(subframe_cursors)
    subframe_first = np.floor(subframe_cursors).astype(int)
    subframe_last = (subframe_first+1)%count
    subframe_pinned = pinned[subframe_first]&pinned[subframe_last]
    subframe_targets = contact_targets[subframe_first]
    subframe_alpha = (subframe_cursors-subframe_first)[:, None, None]
    subframe_alignment = alignment_features(
        alignment_source[subframe_first]*(1.-subframe_alpha)+alignment_source[subframe_last]*subframe_alpha,
        names, body_support)
    subframe_pattern = np.vstack([rig.dependencies,rig.dependencies[1::3],collision_pattern,structure_pattern])
    subframe_pattern = np.vstack([subframe_pattern, equipment_pattern])
    subframe_pattern = np.vstack([subframe_pattern, support_pattern])
    neighbors = np.column_stack([subframe_first-1, subframe_first, subframe_last, subframe_last+1])
    neighbors = neighbors % count if cyclic else np.clip(neighbors, 0, count-1)
    pair_pattern = csr_matrix((np.ones(4*subframe_count),
                               (np.repeat(np.arange(subframe_count),4), neighbors.ravel())),
                              shape=(subframe_count,count))
    pattern = vstack([pattern,kron(pair_pattern,csr_matrix(subframe_pattern))],format='csr')
    if cyclic:
        seam_pattern = np.zeros((2,count));seam_pattern[0,[0,-1,-2]]=1.;seam_pattern[1,[0,1,-1]]=1.
        pattern = vstack([pattern,kron(csr_matrix(seam_pattern),csr_matrix(rig.dependencies))],format='csr')
        excess_pattern = np.zeros((1, count)); excess_pattern[0, [0, 1, -2, -1]] = 1.
        excess_dependencies = rig.dependencies.reshape(joints, 3, rig.width).max(axis=1)
        pattern = vstack([pattern, kron(csr_matrix(excess_pattern), csr_matrix(excess_dependencies))], format='csr')
        pattern = vstack([pattern, kron(csr_matrix(seam_pattern), csr_matrix(excess_dependencies))], format='csr')
    pattern = vstack([pattern, kron(abs(world_d3), temporal_pattern)], format='csr')
    initial_rotations = Rotation.from_rotvec(rig.initial[:,3:].reshape(-1,3))
    floor = payload.get('renderFloorY')
    source_head = body_local_head_direction(reference,names)
    from .fit_runtime import current_fit_session, fit_input_key, fit_should_yield_for_priority
    fit_session = current_fit_session()
    trajectory_key = fit_input_key(payload) if fit_session is not None else None
    best_coordinates = None
    best_cost = float('inf')
    def residual(values):
        nonlocal best_coordinates, best_cost
        if fit_should_yield_for_priority() or monotonic() > optimization_deadline:
            raise TimeoutError
        coordinates = values.reshape(count,rig.width)
        candidate = rig.decode(coordinates)
        rotation_prior = .01*(initial_rotations.inv()*Rotation.from_rotvec(coordinates[:,3:].reshape(-1,3))).as_rotvec().reshape(count,-1)
        current_angles = np.stack([angles(*(candidate[:,i] for i in cols)) for _,cols,_ in specs],axis=1)
        articulation = 100.*(np.minimum(current_angles-low,0.)+np.maximum(current_angles-high,0.))
        floor_error = np.zeros((count,joints)) if floor is None else 100.*np.minimum(candidate[:,:,1]-float(floor),0.)/scale
        current_head = body_local_head_direction(candidate,names)
        head_angle = np.arccos(np.clip(np.sum(source_head*current_head,axis=1),-1.,1.))
        head_penalty = HEAD_ARTICULATION_FIT_WEIGHT*np.maximum(head_angle-np.deg2rad(14.),0.)[:,None]
        excursion_projection = np.sum((candidate-candidate[:,rig.root:rig.root+1]-excursion_center)*excursion_direction,axis=-1)
        excursion_penalty = 20.*np.minimum(excursion_projection-excursion_minimum,0.)*excursion_active/scale
        current_parent, current_bend, current_sine = hinge_coordinates(candidate,names)
        branch_dot = transported_hinge_dots(source_parent,source_bend,current_parent,current_bend)
        branch_penalty = 20.*np.minimum(branch_dot-.2,0.)*branch_supported*np.clip(current_sine/np.sin(np.deg2rad(15.)),0.,1.)
        per_frame = np.concatenate([(2.*(candidate-target)/scale).reshape(count,-1),
                                    (CONTACT_FIT_WEIGHT*(candidate-contact_targets)*pinned[:,:,None]).reshape(count,-1),
                                    articulation, floor_error, head_penalty, rotation_prior,
                                    100.*np.minimum(collision_clearances(candidate,names,scale)[0]/scale-COLLISION_FIT_MARGIN_RATIO,0.),
                                    excursion_penalty,branch_penalty,
                                    ANATOMY_FIT_WEIGHT*anatomical_structure_residuals(
                                        candidate,names,pose_only=True,margin=ANATOMY_FIT_MARGIN)[0],
                                    2000.*grip_residual(candidate,names,equipment)/scale,
                                    2000.*geometry_errors(candidate,names,body_support)/scale,
                                    10.*alignment_constraint_errors(candidate,source_alignment,names,body_support)/scale],axis=1)
        # Penalize output acceleration and jerk, rather than preserving the
        # input noise through a correction-relative temporal objective.
        root_relative = (candidate-candidate[:,rig.root:rig.root+1])/scale
        acceleration = (d2@(candidate-candidate[:,rig.root:rig.root+1]).reshape(count,-1)).reshape(-1,joints,3)
        acceleration = (10.*acceleration/acceleration_fit_scale[None,:,None]).reshape(-1,joints*3)
        jerk = (d3@root_relative.reshape(count,-1))*(fps*.10)**3
        relative = body_relative_points(candidate,names)
        settling = (10.*np.diff(relative,axis=0)*hold_weights*fps
                    / (settling_limit*np.sqrt(max(np.sum(hold_weights)*3, 1.))))
        # Root-relative coordinates remove translation noise without coupling
        # every limb's temporal derivatives to the moving neck basis. Body-axis
        # acceleration below constrains torso rotation independently.
        root_acceleration = (d2@(candidate[:,rig.root]/scale))*(fps*.10)**2*np.sqrt(joints)
        root_jerk = (d3@(candidate[:,rig.root]/scale))*(fps*.07)**3*np.sqrt(joints)
        orientation_acceleration = 10.*(d2@body_orientation_axes(candidate,names).reshape(count,-1))/rotation_fit_scale
        subframe = sample_rig({**playback_rig,'coordinates':coordinates},subframe_cursors,wrap=cyclic)
        subframe_contacts = CONTACT_FIT_WEIGHT*(subframe-subframe_targets)*subframe_pinned[:,:,None]
        subframe_floor = np.zeros((subframe_count,joints)) if floor is None else 100.*np.minimum(subframe[:,:,1]-float(floor),0.)/scale
        subframe_rows = np.concatenate([subframe_contacts.reshape(subframe_count,-1),subframe_floor,
                                        100.*np.minimum(collision_clearances(subframe,names,scale)[0]/scale-COLLISION_FIT_MARGIN_RATIO,0.),
                                        ANATOMY_FIT_WEIGHT*anatomical_structure_residuals(
                                            subframe,names,pose_only=True,margin=ANATOMY_FIT_MARGIN)[0],
                                        2000.*grip_residual(subframe,names,equipment)/scale,
                                        2000.*geometry_errors(subframe,names,body_support)/scale,
                                        10.*alignment_constraint_errors(subframe,subframe_alignment,names,body_support)/scale],axis=1)
        # The final sample precedes the first by one frame. Equal endpoint
        # positions would impose a stop; match the incoming/outgoing increments.
        closure, seam_excess, seam_velocity_excess = np.empty(0), np.empty(0), np.empty(0)
        if cyclic:
            from .loop_seam import seam_errors, MAX_STEP_EXCESS_BODY_RATIO, MAX_VELOCITY_MISMATCH_BODY_RATIO
            _, excess, increments = seam_errors(candidate)
            closure = 100. * increments / scale
            # Optimize the actual playback step bound as well as velocity
            # matching. A small least-squares velocity error can still leave
            # a visibly oversized restart step, especially in slow movement.
            limit = MAX_STEP_EXCESS_BODY_RATIO * scale
            # Use body-normalized meters, as for contact/grip residuals.
            # Dividing by the millimeter acceptance limit makes this term
            # dominate anatomy and contact fitting by orders of magnitude.
            seam_excess = 2000. * np.maximum(excess - .8 * limit, 0.) / scale
            velocity_step_limit = MAX_VELOCITY_MISMATCH_BODY_RATIO * scale / fps
            seam_velocity_excess = 2000. * np.maximum(
                np.linalg.norm(increments, axis=-1) - .8 * velocity_step_limit, 0.) / scale
        errors = np.r_[per_frame.ravel(),acceleration.ravel(),jerk.ravel(),settling.ravel(),
                     root_acceleration.ravel(),root_jerk.ravel(),orientation_acceleration.ravel(),
                     subframe_rows.ravel(),closure.ravel(),seam_excess.ravel(),seam_velocity_excess.ravel()]
        # Normalize by the same RMS bound used at acceptance, independently of
        # clip size or the amount of noise introduced by a preview variant.
        world_jerk = world_d3 @ candidate.reshape(count, -1)
        errors = np.r_[errors, (10. * world_jerk / (
            TEMPORAL_FIT_TARGET_RATIO * jerk_limit * np.sqrt(world_jerk.size))).ravel()]
        cost = float(errors@errors)
        if np.isfinite(cost) and cost < best_cost:
            best_cost, best_coordinates = cost, values.copy()
        return errors
    try:
        if fit_should_yield_for_priority() or monotonic()-started > timeout_seconds:
            raise TimeoutError
        initial_points = rig.decode(rig.initial)
        # Rig feasibility belongs to the observed pose. Comparing against the
        # smoothed target needlessly refits already clean, small articulations
        # and can introduce solver noise larger than their original jerk.
        already_rigid = np.max(abs(initial_points-points)) < 1e-7
        already_smooth = np.max(np.linalg.norm(np.diff(initial_points,n=3,axis=0),axis=-1))*(fps/30.)**3 < .00003*scale
        anchored = np.max(np.linalg.norm((initial_points-contact_targets)[pinned],axis=-1),initial=0.) < .0005
        already_valid = (not cyclic and already_rigid and already_smooth and anchored
                         and validate_physical_motion(initial_points,names,fps=fps)['passed']
                         and validate_grip(initial_points,names,equipment)['passed'])
        if already_valid:
            # Avoid introducing solver noise into an already controlled rig.
            # The same independent acceptance checks still run below.
            solved = SimpleNamespace(x=rig.initial.ravel(),nfev=0)
        else:
            solve_start = rig.initial.ravel()
            if fit_session is not None and trajectory_key in fit_session.trajectories:
                proposal = np.asarray(fit_session.trajectories[trajectory_key], dtype=float)
                if proposal.shape == solve_start.shape and np.isfinite(proposal).all():
                    initial_error, proposed_error = residual(solve_start), residual(proposal)
                    if proposed_error@proposed_error <= initial_error@initial_error:
                        solve_start = proposal
                        report['resumedTrajectory'] = True
            solved = solve_trajectory(residual,solve_start,pattern,max_evaluations)
    except TimeoutError:
        if best_coordinates is None:
            return payload,{**report,'reason':'fit_timeout','elapsedSeconds':monotonic()-started}
        # A budget ends optimization, not validation. The saved iterate may
        # already satisfy every output requirement; subject it to the same
        # independent checks below instead of discarding usable progress.
        solved = SimpleNamespace(x=best_coordinates, nfev=None, status=0)
        report['optimizerTermination'] = 'time_budget'
    finally:
        if fit_session is not None and best_coordinates is not None:
            fit_session.trajectories[trajectory_key] = best_coordinates.tolist()
    if getattr(solved, 'status', 1) == 0:
        report.setdefault('optimizerTermination', 'evaluation_limit')
    def validate_solution(solved):
        # A finite soft-constrained solve can cross the socket boundary again after
        # initialization. Enforce its analytic attachment on the exported coordinates
        # too, then validate geometry, temporal quality and interpolated playback.
        from .physical_validation import SOCKET_ALIGNMENT_MAX_LATERAL_RATIO
        rig.initial[:] = solved.x.reshape(count, rig.width)
        unprojected = rig.decode(rig.initial)
        rig.project_neck_attachment(maximum_lateral_ratio=SOCKET_ALIGNMENT_MAX_LATERAL_RATIO-ANATOMY_FIT_MARGIN)
        # Correct only numerical anatomy leftovers within the existing fitting
        # margin. Large pose defects still require the full constrained fit.
        # Keep the caller's original deadline and validate temporal/contact
        # quality again after this tiny projection.
        numerical_errors, _ = repair_residuals(rig.decode(rig.initial), names)
        largest_error = float(np.max(numerical_errors, initial=0.))
        if 1e-6 < largest_error <= ANATOMY_FIT_MARGIN and monotonic() < started+timeout_seconds:
            previous_coordinates, previous_offsets = rig.initial.copy(), rig.offsets.copy()
            polish_started = monotonic()
            try:
                _, polish = repair_rig_anatomy(rig, rig.decode(rig.initial), deadline=started+timeout_seconds)
            except TimeoutError:
                polish = {'passed': False, 'reason': 'time_budget'}
            polish['elapsedSeconds'] = monotonic()-polish_started
            report['numericalAnatomyPolish'] = polish
            if not polish['passed']:
                rig.initial[:], rig.offsets[:] = previous_coordinates, previous_offsets
        solved.x = rig.initial.ravel().copy()
        result = rig.decode(rig.initial)
        report['finalSocketProjectionMaximumMeters'] = float(
            np.max(np.linalg.norm(result-unprojected, axis=-1)))
        fixed_rig_payload = {'version':1,'jointNames':names,'parents':rig.parents,'order':rig.order,
                             'offsets':rig.offsets.tolist(),'interpolation':INTERPOLATION,
                             'rotationJointNames':[names[j] for j in rig.active],
                             'coordinates':rig.initial.tolist()}
        from .rig_playback import unanchored_floor_clearance_lift
        floor_lift = 0.0
        if not body_support.get('required') and not payload.get('elevatedSupportSurfaces'):
            floor_lift = unanchored_floor_clearance_lift(fixed_rig_payload, floor, pinned, cyclic=cyclic)
        if floor_lift > 0.0:
            rig.initial[:, 1] += floor_lift
            solved.x = rig.initial.ravel().copy()
            fixed_rig_payload['coordinates'] = rig.initial.tolist()
            result = rig.decode(rig.initial)
        report['unanchoredFloorClearanceLiftMeters'] = floor_lift
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
        jerk_after = float(np.sqrt(np.mean(np.diff(result,n=3,axis=0)**2)))
        target_span = np.linalg.norm(np.ptp(target-target[:,rig.root:rig.root+1],axis=0),axis=-1)
        result_span = np.linalg.norm(np.ptp(result-result[:,rig.root:rig.root+1],axis=0),axis=-1)
        moving = target_span > .1*scale
        range_preserved = bool(np.all(result_span[moving] >= .85*target_span[moving]))
        if body_support.get('required'):
            # Preserve articulation excursion independently of the fitted target.
            # Positional spans also encode torso placement/orientation, which the
            # observed support is explicitly allowed to correct.
            from .support_geometry import moving_support_articulations
            ratios = {label: float(np.ptp(angles(*(result[:, j] for j in cols)))/np.ptp(track))
                      for label, cols, track in moving_support_articulations(
                          support_range_reference, names, body_support, support_corrected_points=reference,
                          constraint_endpoints=equipment.get('endpointPair', []))}
            range_preserved &= all(ratio >= .85 for ratio in ratios.values())
            report['supportArticulationRangeRatios'] = ratios
        acceleration_before = np.sqrt(np.mean(np.diff(temporal_reference,n=2,axis=0)**2,axis=(0,2)))
        acceleration_after = np.sqrt(np.mean(np.diff(result,n=2,axis=0)**2,axis=(0,2)))
        no_new_shake = bool(np.all(acceleration_after <= np.maximum(acceleration_before*1.2,.003*(30./fps)**2)))
        settling_after = weighted_settling_speed(result, names, fps, hold_weights)
        settling_preserved = settling_after <= settling_limit
        relative_quality = relative_motion_quality(result, temporal_reference, names, fps)
        root_quality = root_motion_quality(result[:,rig.root], fps, scale)
        checks = {'anatomy':physical['passed'], 'contacts':contact_error<.0005,
                  'sourceArticulation':bool(change<np.deg2rad(20.)), 'trajectoryFit':fit_error<.025*scale,
                  'rootTravel':bool(travel_before<.05*scale or travel_after>=.9*travel_before),
                  'jointRange':range_preserved, 'jointShake':no_new_shake, 'settling':settling_preserved,
                  'jerk':jerk_after<=jerk_limit,
                  'fixedRig':bool(np.max(np.ptp(lengths,axis=1))<1e-9),
                  'relativeJointShake':relative_quality['relativeJointShake'],
                  'bodyRotation':relative_quality['bodyRotation'],
                  'rootContinuity':root_quality['passed']}
        equipment_report = validate_grip(result,names,equipment)
        checks['equipment'] = equipment_report['passed']
        report['bodySupport'] = validate_support_geometry(payload, result, names)
        checks['bodySupport'] = report['bodySupport']['passed']
        report['supportAlignment'] = validate_alignment(result, alignment_source, names, body_support)
        checks['supportAlignment'] = report['supportAlignment']['passed']
        from .temporal_quality import track_discontinuity_metrics
        discontinuity = track_discontinuity_metrics({name: result[:, j].tolist() for j, name in enumerate(names)},
                                                    root_joint=names[rig.root], fps=fps,
                                                    body_height=float(np.median(np.linalg.norm(np.ptp(result, axis=1), axis=-1))))
        checks['motionDiscontinuity'] = discontinuity['available'] and not discontinuity['severe']
        report['motionDiscontinuity'] = discontinuity
        report['equipment'] = equipment_report
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
        if not accepted and getattr(solved, 'status', 1) == 0:
            report['reason'] = ('fit_timeout' if report.get('optimizerTermination') == 'time_budget'
                                else 'fit_evaluation_limit')
        if not accepted:
            return payload,report
        candidate = deepcopy(payload)
        candidate['equipmentConstraints'] = equipment
        if repaired_reference is not None:
            candidate['anatomicalSourceRepair'] = report['anatomicalSourceRepair']
            for frame, corrected in zip(candidate['frames'], repaired_reference):
                frame['correctedAnatomicalReferenceJoints'] = dict(zip(names, corrected.tolist()))
        # New fitted anchors belong to the current frame, not an older placement.
        candidate.pop('scenePlacement', None)
        for index, (frame,values,registered_source) in enumerate(zip(candidate['frames'],result,points)):
            if not (candidate.get('sourcePoseCameraReference') and frame.get('controlledSourceJoints')):
                frame['controlledSourceJoints']={n:v.tolist() for n,v in zip(names,registered_source)}
            frame['joints']={n:v.tolist() for n,v in zip(names,values)}
            if body_support.get('required'):
                frame['supportAlignmentReferenceJoints'] = dict(zip(names, alignment_source[index].tolist()))
                frame['supportCorrectedReferenceJoints'] = dict(zip(names, reference[index].tolist()))
                frame['supportContactReferenceJoints'] = dict(zip(names, registered_source.tolist()))
                for name in body_support.get('stationaryJoints', []):
                    frame['supportContactReferenceJoints'][name] = support_pose[names.index(name)].tolist()
        candidate['fixedRig'] = fixed_rig_payload
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

    candidate, report = validate_solution(solved)
    # Spend remaining time improving an initialized cycle before switching to a
    # new cycle whose support initialization may consume the entire remainder.
    # Explicit evaluation limits remain hard limits. Default continuations are
    # short, require progress, and share the original deadline.
    while (allow_refinement and not report.get('applied') and report.get('checks')
            and report.get('optimizerTermination') != 'time_budget'
            and monotonic()-started < timeout_seconds
            and not fit_should_yield_for_priority()):
        failed_checks = [key for key, passed in report['checks'].items() if not passed]
        if set(failed_checks) <= {'playback', 'loopSeam'} and failed_checks:
            # Soft LS rarely closes a seam after a full solve; further blocks
            # mostly burn budget before a low-EV second cycle.
            report.setdefault('boundedRefinement', {
                'initialFailedChecks': failed_checks, 'evaluationsPerBlock': 5, 'blocks': []
            })['stopReason'] = 'seam_playback_only'
            break
        if hard_trajectory_and_root_failure(report.get('checks')):
            remaining = max(0., started + timeout_seconds - monotonic())
            if remaining < 0.2 * timeout_seconds:
                report.setdefault('boundedRefinement', {
                    'initialFailedChecks': failed_checks, 'evaluationsPerBlock': 5, 'blocks': []
                })['stopReason'] = 'hard_trajectory_root_failure'
                break
        refinement = report.setdefault('boundedRefinement', {
            'initialFailedChecks': failed_checks, 'evaluationsPerBlock': 5, 'blocks': []})
        initial_evaluations = solved.nfev or 0
        previous_coordinates = solved.x.copy()
        cost_before = cost_after = None
        stalled = False
        try:
            errors = residual(solved.x)
            cost_before = float(errors@errors)
            solved = solve_trajectory(residual, solved.x, pattern, 5)
            solved.nfev += initial_evaluations
            errors = residual(solved.x)
            cost_after = float(errors@errors)
            stalled = cost_before-cost_after <= max(1e-12, abs(cost_before)*1e-6)
        except TimeoutError:
            report['optimizerTermination'] = 'time_budget'
            solved = SimpleNamespace(x=best_coordinates if best_coordinates is not None else previous_coordinates,
                                     nfev=None, status=0)
        if fit_session is not None and best_coordinates is not None:
            fit_session.trajectories[trajectory_key] = best_coordinates.tolist()
        candidate, report = validate_solution(solved)
        refinement['blocks'].append({'costBefore': cost_before, 'costAfter': cost_after,
            'failedChecks': [key for key, passed in report.get('checks', {}).items() if not passed]})
        hard_blocks = sum(
            1 for block in refinement['blocks']
            if 'trajectoryFit' in (block.get('failedChecks') or [])
            and 'rootTravel' in (block.get('failedChecks') or [])
        )
        remaining = max(0., started + timeout_seconds - monotonic())
        if hard_trajectory_and_root_failure(report.get('checks')) and (
                stalled or hard_blocks >= 2 or remaining < 0.2 * timeout_seconds):
            refinement['stopReason'] = 'hard_trajectory_root_failure'
            break
        if set(key for key, passed in report.get('checks', {}).items() if not passed) <= {
                'playback', 'loopSeam'} and any(
                not passed for passed in report.get('checks', {}).values()):
            refinement['stopReason'] = 'seam_playback_only'
            break
        if stalled and not report.get('applied'):
            refinement['stopReason'] = 'objective_stalled'
            break
    # One more full eval block when the hard evaluation cap stopped a still-improving
    # (or stalled-but-time-rich) solve. Face-pull-style incompletes often leave tens
    # of seconds unused after fit_evaluation_limit.
    remaining = max(0., started + timeout_seconds - monotonic())
    useful_floor = min(30., max(1., 0.15 * float(timeout_seconds)))
    if (allow_refinement and not report.get('applied')
            and report.get('reason') == 'fit_evaluation_limit'
            and remaining >= useful_floor
            and not fit_should_yield_for_priority()):
        continuation = {
            'remainingSeconds': round(remaining, 3),
            'extraEvaluations': int(max_evaluations),
        }
        previous_coordinates = solved.x.copy()
        initial_evaluations = solved.nfev or 0
        try:
            solved = solve_trajectory(residual, solved.x, pattern, max_evaluations)
            solved.nfev = (solved.nfev or 0) + initial_evaluations
        except TimeoutError:
            report['optimizerTermination'] = 'time_budget'
            solved = SimpleNamespace(
                x=best_coordinates if best_coordinates is not None else previous_coordinates,
                nfev=None, status=0)
        if fit_session is not None and best_coordinates is not None:
            fit_session.trajectories[trajectory_key] = best_coordinates.tolist()
        candidate, report = validate_solution(solved)
        continuation['applied'] = bool(report.get('applied'))
        continuation['reason'] = report.get('reason')
        report['evaluationContinuation'] = continuation
    return candidate, report


def main():
    """Run an isolated comparison without replacing a library artifact."""
    import argparse
    import json
    from pathlib import Path
    from .preview import write_baked_preview_html
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('output_directory', type=Path)
    parser.add_argument('--max-evaluations', type=int, help='Hard evaluation cap; default: 25 then short refinements while improving within the time budget.')
    parser.add_argument('--timeout-seconds', type=float, help='Override the frame-count-based 150-300 second solve budget.')
    args = parser.parse_args()
    if (args.max_evaluations is not None and args.max_evaluations < 1) or (args.timeout_seconds is not None and args.timeout_seconds <= 0):
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
