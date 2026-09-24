"""Default final-bake fixed-rig trajectory fit; legacy output remains available."""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from time import monotonic
from types import SimpleNamespace
import numpy as np
from scipy.ndimage import gaussian_filter1d
from scipy.optimize import least_squares
from scipy.optimize._numdiff import approx_derivative, group_columns
from scipy.sparse import csr_matrix, eye, kron, lil_matrix, vstack
from scipy.spatial.transform import Rotation

from .sequence_stabilization import contact_mask, frame_basis, pose_digest, unit
from .smpl_joint_names import SMPL_JOINT_NAMES, SMPL_JOINT_PARENTS
from .physical_validation import ARTICULATIONS, angles, body_scale, collision_clearances, collision_specs, validate_physical_motion, anatomical_structure_residuals
from .temporal_quality import body_orientation_axes, body_orientation_noise, body_local_head_direction, introduced_joint_spikes, refresh_motion_bounds, transport_corrected_bone_sides
from .motion_placement import contact_consistent_target, root_motion_quality, register_contact_placement, align_registered_contacts_above_floor
from .rig_interpolation import INTERPOLATION
from .rig_playback import PLAYBACK_CONTACT_LIMIT_METERS, PLAYBACK_FLOOR_LIMIT_METERS

CONTROLLED_MOTION_STRATEGY = 'fixed_rig_controlled_motion_v54_preserve_grip_during_playback_repair'
# Feasibility pre-flight threshold, calibrated from fit reports: every
# successful fit's target bones matched the rig within ~0.002m, while
# structurally conflicted fits measured 0.05-0.15m before burning their
# whole budget on an unsolvable problem.
FIT_INPUT_MAX_TARGET_BONE_MISMATCH_METERS = 0.04
# Soft temporal penalties compete with pose/contact fitting. Target below the
# acceptance boundary so a finite solver budget does not settle just outside it.
TEMPORAL_FIT_TARGET_RATIO = .8
CONTACT_FIT_WEIGHT = 10. / (.8 * PLAYBACK_CONTACT_LIMIT_METERS)
FLOOR_FIT_WEIGHT = 10. / (.8 * PLAYBACK_FLOOR_LIMIT_METERS)
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
# Support placement is calibrated per trajectory; each crop keeps its own poses.
SUPPORT_INIT_COLD_EVALUATIONS = 80
# Cold support LS on retained long cycles: ~0.015s per (frame × eval).
# 129 frames × 80 evals ≈ 146s; a flat 90s stage cap aborted finishable work.
SUPPORT_INIT_SECONDS_PER_FRAME_EVAL = .015
SUPPORT_INIT_SOLVE_RESERVE_FRACTION = .25
SUPPORT_INIT_SOLVE_RESERVE_MIN_SECONDS = 30.
HEAD_ARTICULATION_FIT_WEIGHT = 1000.
# Under required support, contact residuals are ~50× articulation at weight 500;
# raise the soft hinge/head floors so LS cannot invent repair_articulation_distortion.
SUPPORT_ARTICULATION_FIT_WEIGHT = 8000.
SUPPORT_HEAD_ARTICULATION_FIT_WEIGHT = 5000.
# End-of-budget polish window so Stage-B seam work is not starved by anatomy/support mins.
POLISH_RESERVE_FRACTION = .18
POLISH_RESERVE_MAX_SECONDS = 25.
POLISH_RESERVE_MIN_SECONDS = 12.
REQUIRED_FIT_CHECKS = ('anatomy', 'contacts', 'sourceArticulation', 'trajectoryFit',
                       'rootTravel', 'jointRange', 'jointShake', 'settling', 'jerk',
                       'fixedRig', 'playback', 'relativeJointShake', 'bodyRotation', 'rootContinuity', 'equipment', 'motionDiscontinuity', 'bodySupport', 'supportAlignment')


def controlled_fit_processing_incomplete(report):
    """A deadline is missing processing evidence, not a failed geometry check."""
    if not isinstance(report, dict) or report.get('applied'):
        return False
    if report.get('termination') in EVIDENCE_TERMINATIONS:
        return False
    if (report.get('boundedRefinement') or {}).get('stopReason') in EVIDENCE_TERMINATIONS:
        return False
    # A validated reject is decisive even when the soft LS hit its phase budget.
    if report.get('reason') == 'fit_validation_failed' and report.get('checks'):
        return False
    if report.get('reason') in {
            'loop_requires_cycle_repair', 'playback_validation_failed'} and report.get('checks'):
        return False
    if report.get('optimizerTermination') == 'objective_stalled' and report.get('checks'):
        return False
    checks = report.get('checks')
    # Finished acceptance with at least one failed check is a decisive reject.
    # Do not keep retrying just because the soft LS watchdog fired.
    if isinstance(checks, dict) and checks and any(value is False for value in checks.values()):
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


def failed_check_names(checks):
    if not isinstance(checks, dict):
        return []
    return [key for key, passed in checks.items() if not passed]


POLISH_STAGE_A = frozenset({'contacts', 'equipment', 'bodySupport', 'supportAlignment'})
POLISH_STAGE_B = frozenset({'playback', 'loopSeam'})
POLISH_STAGE_C = frozenset({
    'jerk', 'jointShake', 'relativeJointShake', 'settling',
    'rootContinuity', 'motionDiscontinuity',
})
# Stage-A soft LS otherwise loses to seam/temporal terms on supported cycles.
STAGE_A_CONTACT_POLISH_WEIGHT = 8.
# Stage A used to raise contact weight even for equipment-only failures, which
# made an already-clear plant mask dominate the grip term. Boost grip instead.
STAGE_A_EQUIPMENT_POLISH_WEIGHT = 8.
# Soft grip weight; raised when the working reference already misses rigid_pair.
GRIP_FIT_WEIGHT = 5000.
GRIP_FIT_WEIGHT_WHEN_REFERENCE_FAILS = 40000.


def polish_stage_for_failures(failed_checks):
    """Ordered polish focus: contacts → body continuity/temporal → seam."""
    failed = set(failed_checks or [])
    if failed & POLISH_STAGE_A:
        return 'A'
    if failed & POLISH_STAGE_C:
        return 'C'
    # Interpolated playback without a wrap gap is a between-frame path issue,
    # not a seam. Stage-B wrap projection cannot close it.
    if failed <= {'playback'}:
        return 'C'
    if failed & POLISH_STAGE_B:
        return 'B'
    return 'A'


def polishable_near_miss(failed_checks):
    """Failures that leftover outer time should keep polishing."""
    failed = set(failed_checks or [])
    return bool(failed) and failed <= (POLISH_STAGE_A | POLISH_STAGE_B | POLISH_STAGE_C)


EVIDENCE_TERMINATIONS = frozenset({
    'objective_stalled', 'acceptance_stalled', 'seam_playback_only',
    'seam_excess_needs_different_cycle', 'hard_trajectory_root_failure',
    'unreachable_conflict', 'polish_stalled', 'hard_polish_exhausted',
})


def unreachable_without_polish(report):
    """Conflicts that more soft LS will not repair — stop without burning budget."""
    if not isinstance(report, dict):
        return False
    checks = report.get('checks') or {}
    if hard_trajectory_and_root_failure(checks):
        return True
    failed = set(failed_check_names(checks))
    reasons = set(report.get('physicalReasons') or [])
    if {'anatomy', 'sourceArticulation'} <= failed and 'repair_articulation_distortion' in reasons:
        return True
    return False


def refinement_improved_acceptance(refinement):
    """True when a refinement block strictly cleared at least one failed check."""
    if not isinstance(refinement, dict):
        return False
    blocks = refinement.get('blocks') or []
    if not blocks:
        return False
    initial = set(refinement.get('initialFailedChecks') or [])
    final = set((blocks[-1] or {}).get('failedChecks') or [])
    return bool(initial) and final < initial


def acceptance_stalled_after_refinement(refinement):
    """Same failing checks across two refinement blocks: further LS is low-EV."""
    if not isinstance(refinement, dict):
        return False
    blocks = refinement.get('blocks') or []
    if len(blocks) < 2:
        return False
    previous = set((blocks[-2] or {}).get('failedChecks') or [])
    current = set((blocks[-1] or {}).get('failedChecks') or [])
    return bool(current) and previous == current


def seam_or_playback_only_failure(report):
    """True when the body fit is otherwise OK and only loop closure failed."""
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


# Soft Stage-B rarely invents continuity when excess is already near the limit;
# a cold second window is low-EV then. When excess is still ≫2×, another ranked
# cycle is the intended recovery (see reject-failure analysis). Keep equal to
# loop_seam.MAX_RANKED_SOURCE_WRAP_RATIO so ranking and Stage-B agree.
SEAM_NEAR_MISS_CYCLE_SKIP_MULTIPLE = 2.0


def seam_near_miss_for_cycle_skip(report):
    """True when seam/playback-only and both step/velocity are within ~2× limits."""
    if not seam_or_playback_only_failure(report):
        return False
    playback = report.get('playback') or {}
    ratios = []
    excess = playback.get('seamStepExcessMeters')
    limit = playback.get('seamStepExcessLimitMeters')
    if excess is not None and limit is not None and float(limit) > 0:
        ratios.append(float(excess) / float(limit))
    velocity = playback.get('seamVelocityMismatchMetersPerSecond')
    velocity_limit = playback.get('seamVelocityMismatchLimitMetersPerSecond')
    if velocity is not None and velocity_limit is not None and float(velocity_limit) > 0:
        ratios.append(float(velocity) / float(velocity_limit))
    if not ratios:
        # Missing magnitude: keep prior early-stop (treat as near-miss).
        return True
    return max(ratios) <= SEAM_NEAR_MISS_CYCLE_SKIP_MULTIPLE


def seam_over_limit_ratios(playback):
    """Return step/velocity over-limit ratios from a playback report dict."""
    if not isinstance(playback, dict):
        return []
    ratios = []
    excess = playback.get('seamStepExcessMeters')
    limit = playback.get('seamStepExcessLimitMeters')
    if excess is not None and limit is not None and float(limit) > 0:
        ratios.append(float(excess) / float(limit))
    velocity = playback.get('seamVelocityMismatchMetersPerSecond')
    velocity_limit = playback.get('seamVelocityMismatchLimitMetersPerSecond')
    if velocity is not None and velocity_limit is not None and float(velocity_limit) > 0:
        ratios.append(float(velocity) / float(velocity_limit))
    return ratios


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


def intentional_open_loop_seam(payload):
    """Fit kept an otherwise-valid body with an honest non-continuous wrap."""
    report = payload.get('controlledMotionFit') or {}
    return bool(
        report.get('applied')
        and (
            report.get('reason') == 'validated_controlled_motion_open_seam'
            or report.get('loopSeamOpen') is True
        )
    )


def loop_disabled_playback_passed(payload):
    """True when interpolator/contact/support checks pass without cyclic wrap."""
    from .rig_playback import validate_rig_playback
    if not payload.get('fixedRig'):
        return False
    loop_off = {**payload, 'loop': {**(payload.get('loop') or {}), 'enabled': False}}
    return bool(validate_rig_playback(loop_off).get('passed'))


def can_reuse_controlled_motion(payload):
    from .support_geometry import validate_support_geometry, validate_supported_shoe_orientation
    from .support_alignment import validate_payload_alignment
    report = payload.get('controlledMotionFit') or {}
    checks = report.get('checks') or {}
    open_seam = intentional_open_loop_seam(payload)
    # Open-seam accepts waive only wrap checks; body/contact checks still bind.
    waived = {'loopSeam'} | ({'playback'} if open_seam else set())
    required_ok = all(
        checks.get(key) is True for key in REQUIRED_FIT_CHECKS if key not in waived)
    checks_ok = all(
        value is True for key, value in checks.items() if key not in waived)
    seam_ok = open_seam or (
        not (payload.get('loop') or {}).get('enabled') or checks.get('loopSeam') is True)
    return bool(payload.get('fixedRig') and report.get('applied')
                and report.get('strategy') == CONTROLLED_MOTION_STRATEGY
                and required_ok and checks_ok and seam_ok
                and validate_support_geometry(payload)['passed']
                and validate_payload_alignment(payload)['passed']
                and validate_supported_shoe_orientation(payload)['passed']
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
        self.initial[:] = project_neck_attachment_values(
            self.initial, self.offsets, self.names, self.active, maximum_lateral_ratio)

    def decode(self, values, *, project_socket=True):
        from .physical_validation import SOCKET_ALIGNMENT_MAX_LATERAL_RATIO
        # Same analytic socket clamp as sample_rig / export projection so residual,
        # keyframe acceptance, and interpolated playback share one neck attachment.
        values = np.asarray(values, dtype=float)
        if project_socket:
            values = project_neck_attachment_values(
                values, self.offsets, self.names, self.active,
                SOCKET_ALIGNMENT_MAX_LATERAL_RATIO - ANATOMY_FIT_MARGIN)
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


def project_neck_attachment_values(coordinates, offsets, names, active, maximum_lateral_ratio):
    """Clamp neck lateral socket on rig coordinates; keep bone lengths and head direction."""
    values = np.array(coordinates, dtype=float, copy=True)
    required = ('neck', 'head', 'left_collar', 'right_collar')
    if any(name not in names for name in required):
        return values
    slots = {j: 3 + 3 * i for i, j in enumerate(active)}
    neck, head = names.index('neck'), names.index('head')
    if neck not in slots or head not in slots:
        return values
    left, right = offsets[names.index('left_collar')], offsets[names.index('right_collar')]
    span = right - left
    width = np.linalg.norm(span)
    if width < 1e-12:
        return values
    lateral = unit(span)
    center = np.dot((left + right) * .5, lateral)
    neck_slot, head_slot = slots[neck], slots[head]
    old_neck = Rotation.from_rotvec(values[:, neck_slot:neck_slot + 3])
    vectors = old_neck.apply(np.tile(offsets[neck], (len(values), 1)))
    component = vectors @ lateral
    limit = maximum_lateral_ratio * width
    length = np.linalg.norm(offsets[neck])
    corrected = np.clip(center + np.clip(component - center, -limit, limit), -length, length)
    orthogonal = vectors - component[:, None] * lateral
    magnitude = np.linalg.norm(orthogonal, axis=1, keepdims=True)
    fallback = unit(np.cross(lateral, np.eye(3)[np.argmin(abs(lateral))]))
    direction = np.where(magnitude > 1e-12, orthogonal / np.maximum(magnitude, 1e-12), fallback)
    target = direction * np.sqrt(np.maximum(length ** 2 - corrected ** 2, 0.))[:, None] + corrected[:, None] * lateral
    new_neck = Rotation.from_rotvec(align_vectors(vectors, target)) * old_neck
    old_head = Rotation.from_rotvec(values[:, head_slot:head_slot + 3])
    values[:, neck_slot:neck_slot + 3] = new_neck.as_rotvec()
    values[:, head_slot:head_slot + 3] = (new_neck.inv() * old_neck * old_head).as_rotvec()
    return values


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


def settling_hold_basis(temporal_reference, working_reference, body_support):
    """Choose the motion whose quiet holds define settling for this fit.

    Preview variants keep the immutable source articulation baseline. When
    observed support intentionally rewrites geometry, that supported reference
    is the trajectory the optimizer starts from—and the only reachable quiet
    hold baseline for acceptance.
    """
    if isinstance(body_support, dict) and body_support.get('required'):
        return working_reference
    return temporal_reference


def support_joint_range_preserved(articulation_ratios):
    """Under body support, jointRange is articulation excursion only.

    World-space spans also encode torso placement/orientation that observed
    support is allowed to correct, so they must not AND with articulation.
    """
    return (all(ratio >= .85 for ratio in articulation_ratios.values())
            if articulation_ratios else True)


def smooth_extremity_coordinates(coordinates, rig, names, *, cyclic, sigma=1.5,
                                 pinned=None, include_knees=False):
    """Temporally smooth extremity local rotations (discontinuity owners).

    Only fully stationary extremity slots are skipped. Alternating plant/swing
    feet must remain smoothable; planted-at-event spikes are repaired via plant
    continuity after free distal-chain passes.
    """
    smoothed = np.asarray(coordinates, dtype=float).copy()
    mode = 'wrap' if cyclic else 'nearest'
    always_planted = np.zeros(len(names), dtype=bool)
    if pinned is not None:
        always_planted = np.all(np.asarray(pinned, dtype=bool), axis=0)
    suffixes = ('ankle', 'foot', 'wrist', 'hand', 'elbow') + (('knee',) if include_knees else ())
    for joint, name in enumerate(names):
        if always_planted[joint]:
            continue
        if not name.endswith(suffixes):
            continue
        slot = rig.slots.get(joint)
        if slot is None:
            continue
        smoothed[:, slot:slot + 3] = gaussian_filter1d(
            smoothed[:, slot:slot + 3], sigma, axis=0, mode=mode)
    return smoothed


def repair_motion_discontinuity_coordinates(coordinates, rig, names, *, cyclic, fps,
                                            pinned=None, scale=None, contact_targets=None):
    """Clear fit-introduced extremity velocity discontinuities.

    Free distal chains escalate temporal smooth (including knees). Spikes on
    joints planted at the event are contact/root continuity: temporally filter
    those plant targets and re-project without dragging always-planted anchors
    via extremity gaussian.
    """
    from .temporal_quality import track_discontinuity_metrics

    repaired = np.asarray(coordinates, dtype=float).copy()
    root = names[rig.root]
    body_height = None if scale is None else float(scale)
    pin = None if pinned is None else np.asarray(pinned, dtype=bool)

    def metrics(coords):
        points = rig.decode(coords)
        height = body_height
        if height is None:
            height = float(np.median(np.linalg.norm(np.ptp(points, axis=1), axis=-1)))
        return track_discontinuity_metrics(
            {name: points[:, j].tolist() for j, name in enumerate(names)},
            root_joint=root, fps=fps, body_height=height)

    report = metrics(repaired)
    if not report.get('severe'):
        return repaired
    for sigma, knees in ((1.5, False), (2.5, True), (4.0, True)):
        repaired = smooth_extremity_coordinates(
            repaired, rig, names, cyclic=cyclic, sigma=sigma, pinned=pin,
            include_knees=knees)
        report = metrics(repaired)
        if not report.get('severe'):
            return repaired
    # Remaining events on currently planted contacts: smooth plant targets.
    if pin is None or contact_targets is None or not np.any(pin):
        return repaired
    targets = np.asarray(contact_targets, dtype=float).copy()
    if targets.shape != rig.decode(repaired).shape:
        return repaired
    event_joints = {
        names.index(event['joint'])
        for event in (report.get('events') or [])
        if isinstance(event, dict) and event.get('joint') in names
    }
    planted_event_joints = [
        joint for joint in event_joints
        if pin[:, joint].any() and not np.all(pin[:, joint])
    ]
    if not planted_event_joints:
        # Fully stationary plant spike: still regularize that plant trajectory.
        planted_event_joints = [
            joint for joint in event_joints if np.all(pin[:, joint])
        ]
    if not planted_event_joints:
        return repaired
    mode = 'wrap' if cyclic else 'nearest'
    for joint in planted_event_joints:
        active = pin[:, joint]
        if not np.any(active):
            continue
        filtered = gaussian_filter1d(targets[:, joint], 2.0, axis=0, mode=mode)
        targets[active, joint] = filtered[active]
    repaired = project_contact_plant_coordinates(
        repaired, rig, pin, targets, max_nfev=30, freeze_root=True)
    return repaired


def temporal_coordinate_smooth(coordinates, *, cyclic, sigma=1.0):
    """Mild temporal smooth on local rotations to cut excess post-fit jerk."""
    smoothed = np.array(coordinates, dtype=float, copy=True)
    mode = 'wrap' if cyclic else 'nearest'
    smoothed[:, 3:] = gaussian_filter1d(smoothed[:, 3:], sigma, axis=0, mode=mode)
    return smoothed


def temporal_free_coordinate_smooth(coordinates, rig, pinned, *, cyclic, sigma=1.0):
    """Smooth a rotation only at frames where its descendants are unplanted.

    Preserve held keyframes while allowing swing and approach motion to smooth.
    The caller still checks/restores interpolated contacts: neighboring free
    samples can change the tangent entering a held interval.
    """
    smoothed = np.asarray(coordinates, dtype=float).copy()
    if smoothed.ndim != 2 or smoothed.shape[1] < 6:
        return smoothed
    mode = 'wrap' if cyclic else 'nearest'
    filtered = gaussian_filter1d(smoothed, float(sigma), axis=0, mode=mode)
    locked = np.zeros((len(smoothed), len(rig.names)), dtype=bool)
    if pinned is not None:
        # A swinging limb is free even if it plants later in the clip. Global
        # plant membership prevented smoothing the approach to every touchdown.
        for joint in range(pinned.shape[1]):
            active = pinned[:, joint]
            ancestor = joint
            while ancestor >= 0:
                locked[:, ancestor] |= active
                ancestor = rig.parents[ancestor]
    for joint, start in rig.slots.items():
        free = ~locked[:, joint]
        smoothed[free, start:start + 3] = filtered[free, start:start + 3]
    return smoothed


def polish_free_temporal_preserving_anatomy(
        coordinates, rig, pinned, contact_targets, *, cyclic, sigma,
        deadline=None, floor=None, fps=30., spike_reference=None):
    """Free-DOF temporal smooth, then restore physical anatomy if it opened.

    Mild/strong free-chain smooth clears Stage-C jerk on path-repaired clips, but
    spine smoothing can trip anatomy_torso_bend. A bounded anatomical repair brings
    physical back while keeping the lower third-difference roughness.
    """
    trial = temporal_free_coordinate_smooth(
        coordinates, rig, pinned, cyclic=cyclic, sigma=sigma)
    if np.allclose(trial, coordinates):
        return np.asarray(coordinates, dtype=float).copy()
    previous_initial = rig.initial.copy()
    previous_offsets = rig.offsets.copy()
    rig.initial[:] = trial
    try:
        from .anatomical_repair import repair_rig_anatomy
        anatomy_deadline = (
            deadline if deadline is not None else monotonic() + 12.)
        _, polish = repair_rig_anatomy(
            rig, rig.decode(rig.initial), deadline=anatomy_deadline)
        if not polish.get('passed'):
            rig.initial[:] = previous_initial
            rig.offsets[:] = previous_offsets
            return np.asarray(coordinates, dtype=float).copy()
        trial = np.asarray(rig.initial, dtype=float).copy()
        if pinned is not None and np.any(pinned) and contact_targets is not None:
            play_before = _playback_contact_sample_error(
                coordinates, rig, pinned, contact_targets, cyclic=cyclic)
            play_after = _playback_contact_sample_error(
                trial, rig, pinned, contact_targets, cyclic=cyclic)
            if (play_after >= PLAYBACK_CONTACT_LIMIT_METERS
                    or play_after > play_before * 1.05 + 1e-9
                    or _playback_failing_intervals(
                        trial, rig, pinned, contact_targets, cyclic=cyclic, floor=floor)):
                plant_deadline = deadline
                trial = project_contact_plant_coordinates(
                    trial, rig, pinned, contact_targets, max_nfev=12,
                    freeze_root=True, deadline=plant_deadline)
                if _playback_failing_intervals(
                        trial, rig, pinned, contact_targets, cyclic=cyclic, floor=floor):
                    trial = project_interval_playback_plants(
                        trial, rig, pinned, contact_targets, cyclic=cyclic,
                        floor=floor, max_nfev=10, deadline=plant_deadline,
                        spike_reference=spike_reference)
                trial = repair_playback_velocity_continuity(
                    trial, rig, pinned, contact_targets, cyclic=cyclic, sigma=0.4,
                    deadline=plant_deadline, floor=floor, fps=fps,
                    spike_reference=spike_reference)
                rig.initial[:] = trial
        return trial
    except Exception:
        rig.initial[:] = previous_initial
        rig.offsets[:] = previous_offsets
        return np.asarray(coordinates, dtype=float).copy()



def polish_worsened_jerk(report, previous_jerk):
    """True when a polish block raised third-difference roughness past prior."""
    if previous_jerk is None:
        return False
    after = report.get('jerkAfter')
    if after is None:
        return False
    return float(after) > float(previous_jerk) * 1.05 + 1e-12


def polish_reserve_seconds(timeout_seconds, *, cyclic):
    """Wall-clock reserved at the end of the outer budget for Stage-B/C polish."""
    if timeout_seconds is None or timeout_seconds <= 0:
        return 0.
    base = min(POLISH_RESERVE_MAX_SECONDS, max(POLISH_RESERVE_MIN_SECONDS,
                                              POLISH_RESERVE_FRACTION * float(timeout_seconds)))
    reserve = float(base if cyclic else min(base, 15.))
    # Short diagnose budgets: keep polish, but leave anatomy/support enough room.
    if float(timeout_seconds) < 180.:
        reserve = min(reserve, 0.12 * float(timeout_seconds), 15.)
    return min(reserve, max(0., 0.4 * float(timeout_seconds)))


def supported_geometry_ready_for_skip_soft_solve(
        *, anchored, playback_anchored, floor_clear, points, names, equipment, payload,
        support_strategy=None):
    """Skip supported geometry only when any required loop seam also passes.

    Long plant-only clips were burning ~150s of soft LS after plants were under
    gate; that raised jerk and consumed the Stage-C polish window. Rigid-pair
    grip leftovers belong to Stage-A hard projection, not soft LS.
    """
    del playback_anchored, equipment
    if not (anchored and floor_clear):
        return False
    if support_strategy == 'plant_projection':
        if (payload.get('loop') or {}).get('enabled'):
            # Plants alone do not make a cyclic trajectory ready. The main
            # optimizer owns joint contact/temporal/seam correction; skipping it
            # here strands an open seam in contact-only hard refinement.
            from .loop_seam import seam_quality_metrics
            fps = float(payload.get('fps') or 0.)
            if fps <= 0 or not seam_quality_metrics(
                    points, fps=fps, scale=body_scale(points, names))['seamContinuous']:
                return False
        return True
    return False


def seam_boundary_coordinate_nudge(coordinates, rig, pinned, *, strength=0.55):
    """Cheap first/last free-DOF blend to shrink loop restart hitch before Stage-B LS.

    When any contact is planted, skip root translation — moving the pelvis would
    drag anchored feet. Close the seam on free rotation DOFs, including a
    world-tip pull so free hands/head actually move toward continuity.
    """
    coords = np.asarray(coordinates, dtype=float).copy()
    if len(coords) < 3 or strength <= 0:
        return coords
    planted = bool(np.any(pinned))
    if not planted:
        delta_t = coords[0, :3] - coords[-1, :3]
        coords[0, :3] -= 0.5 * strength * delta_t
        coords[-1, :3] += 0.5 * strength * delta_t
    free_joints = [j for j in range(pinned.shape[1]) if not bool(np.any(pinned[:, j]))]
    free_cols = []
    for joint in free_joints:
        slot = rig.slots.get(joint)
        if slot is None:
            continue
        free_cols.extend(range(slot, slot + 3))
        first = Rotation.from_rotvec(coords[0, slot:slot + 3])
        last = Rotation.from_rotvec(coords[-1, slot:slot + 3])
        delta = (first.inv() * last).as_rotvec()
        coords[0, slot:slot + 3] = (first * Rotation.from_rotvec(0.5 * strength * delta)).as_rotvec()
        coords[-1, slot:slot + 3] = (last * Rotation.from_rotvec(-0.5 * strength * delta)).as_rotvec()
    # World-space tip pull on free joints (planted or not): rotation blends alone
    # leave multi-cm hand/head hitches when the hitch is translational in FK.
    if free_joints:
        from .loop_seam import seam_errors
        rig.initial[:] = coords
        points = rig.decode(coords)
        step, _, _ = seam_errors(points)
        for joint in free_joints:
            slot = rig.slots.get(joint)
            parent = rig.parents[joint]
            if slot is None or parent < 0:
                continue
            for frame, sign in ((0, -1.), (-1, 1.)):
                parent_pos = points[frame, parent]
                current = points[frame, joint]
                target = current + sign * 0.5 * strength * step[joint]
                current_dir = current - parent_pos
                desired_dir = target - parent_pos
                if (np.linalg.norm(current_dir) < 1e-8 or np.linalg.norm(desired_dir) < 1e-8):
                    continue
                delta = align_vectors(current_dir[None], desired_dir[None])[0]
                rot = Rotation.from_rotvec(coords[frame, slot:slot + 3])
                coords[frame, slot:slot + 3] = (
                    Rotation.from_rotvec(strength * delta) * rot).as_rotvec()
        # Refresh for neighbor blend after tip pull.
        rig.initial[:] = coords
    # Neighbor frames: reduce velocity mismatch at the wrap on free DOFs only.
    if len(coords) >= 4 and free_cols:
        cols = np.asarray(free_cols, dtype=int)
        blend = (0.25 if planted else 0.45) * strength
        coords[1, cols] = (1. - blend) * coords[1, cols] + blend * coords[0, cols]
        coords[-2, cols] = (1. - blend) * coords[-2, cols] + blend * coords[-1, cols]
        if not planted and len(coords) >= 6:
            coords[2, cols] = (1. - 0.5 * blend) * coords[2, cols] + 0.5 * blend * coords[1, cols]
            coords[-3, cols] = (1. - 0.5 * blend) * coords[-3, cols] + 0.5 * blend * coords[-2, cols]
    return coords


def seam_velocity_neighbor_nudge(coordinates, rig, pinned, *, strength=0.55):
    """Extrapolate frames 1/-2 so wrap incoming/outgoing match the endpoint step.

    Operates in coordinate space on free DOFs (and root translation when
    unplanted). Scored by close_loop_seam_coordinates so regressions are dropped.
    """
    coords = np.asarray(coordinates, dtype=float).copy()
    if len(coords) < 4 or strength <= 0:
        return coords
    planted = bool(np.any(pinned))
    if planted:
        free_cols = []
        for joint in range(pinned.shape[1]):
            if bool(np.any(pinned[:, joint])):
                continue
            slot = rig.slots.get(joint)
            if slot is not None:
                free_cols.extend(range(slot, slot + 3))
        if not free_cols:
            return coords
        cols = np.asarray(free_cols, dtype=int)
    else:
        cols = np.arange(coords.shape[1], dtype=int)
    # Continuous wrap: coords[1]-coords[0] ≈ coords[0]-coords[-1]
    # and coords[-1]-coords[-2] ≈ coords[0]-coords[-1].
    target_1 = 2. * coords[0] - coords[-1]
    target_m2 = 2. * coords[-1] - coords[0]
    coords[1, cols] = (1. - strength) * coords[1, cols] + strength * target_1[cols]
    coords[-2, cols] = (1. - strength) * coords[-2, cols] + strength * target_m2[cols]
    return coords


def seam_playback_over_limit_score(points, *, scale, fps):
    """Max of step/velocity over-limit ratios used by playback acceptance."""
    from .loop_seam import (
        seam_errors, MAX_STEP_EXCESS_BODY_RATIO, MAX_VELOCITY_MISMATCH_BODY_RATIO)
    _, excess, increments = seam_errors(points)
    step_limit = MAX_STEP_EXCESS_BODY_RATIO * float(scale)
    vel_limit = MAX_VELOCITY_MISMATCH_BODY_RATIO * float(scale)
    step_ratio = float(np.max(excess, initial=0.)) / step_limit if step_limit > 0 else 0.
    velocity = float(np.max(np.linalg.norm(increments, axis=-1), initial=0.)) * float(fps)
    vel_ratio = velocity / vel_limit if vel_limit > 0 else 0.
    return max(step_ratio, vel_ratio)


def project_contact_root_translation(coordinates, rig, pinned, contact_targets, passes=3,
                                     *, smooth_fps=None):
    """Per-frame root translation that aligns planted contacts to their targets.

    Soft LS under support often stalls a few tenths of a millimeter over the
    contact gate while burning polish. A rigid root shift clears that residual
    without inventing free-limb articulation. A few passes absorb decode
    nonlinearities from dependent rotations. Optional smooth_fps temporally
    filters the per-frame shifts so contact snap does not reintroduce root spikes.
    """
    coords = np.asarray(coordinates, dtype=float).copy()
    if coords.ndim != 2 or not np.any(pinned):
        return coords
    targets = np.asarray(contact_targets, dtype=float)
    for _ in range(max(1, int(passes))):
        points = rig.decode(coords)
        shifts = np.zeros((len(coords), 3), dtype=float)
        max_shift = 0.
        for frame in range(len(coords)):
            mask = pinned[frame]
            if not np.any(mask):
                continue
            delta = np.mean(targets[frame, mask] - points[frame, mask], axis=0)
            if np.isfinite(delta).all():
                shifts[frame] = delta
                max_shift = max(max_shift, float(np.linalg.norm(delta)))
        if smooth_fps is not None and max_shift > 0.:
            sigma = max(.5, float(smooth_fps) * .08)
            shifts = gaussian_filter1d(shifts, sigma, axis=0, mode='nearest')
        coords[:, :3] += shifts
        if max_shift < 1e-7:
            break
    return coords


def _sampling_payload(rig, coordinates):
    return {
        'jointNames': list(rig.names),
        'parents': rig.parents,
        'order': rig.order,
        'offsets': rig.offsets,
        'rotationJointNames': [rig.names[j] for j in rig.active],
        'interpolation': INTERPOLATION,
        'coordinates': np.asarray(coordinates, dtype=float),
    }


def _plant_chain_slots(rig, pinned):
    plant_joints = [j for j in range(pinned.shape[1]) if pinned[:, j].any()]
    chain = set()
    for joint in plant_joints:
        ancestor = joint
        while ancestor >= 0:
            if ancestor in rig.slots:
                chain.add(ancestor)
            ancestor = rig.parents[ancestor]
    return sorted(chain)


def _playback_contact_sample_error(coordinates, rig, pinned, contact_targets, *, cyclic=False):
    """Peak planted-contact error on the same quarter-frame samples playback uses."""
    coords = np.asarray(coordinates, dtype=float)
    targets = np.asarray(contact_targets, dtype=float)
    count = len(coords)
    if count < 2 or not np.any(pinned):
        return 0.
    from .rig_playback import sample_rig
    interval_count = count if cyclic else count - 1
    cursors = (np.arange(interval_count)[:, None] + np.array([.25, .5, .75])).ravel()
    first = np.floor(cursors).astype(int)
    last = (first + 1) % count if cyclic else np.minimum(first + 1, count - 1)
    active = pinned[first] & pinned[last]
    if not np.any(active):
        return 0.
    sampled = sample_rig(_sampling_payload(rig, coords), cursors, wrap=cyclic)
    return float(np.max(np.linalg.norm((sampled - targets[first])[active], axis=-1), initial=0.))


def _playback_floor_penetration(coordinates, rig, *, cyclic=False, floor=None):
    if floor is None or len(coordinates) < 2:
        return 0.
    from .rig_playback import sample_rig
    count = len(coordinates)
    interval_count = count if cyclic else count - 1
    cursors = (np.arange(interval_count)[:, None] + np.array([.25, .5, .75])).ravel()
    sampled = sample_rig(_sampling_payload(rig, coordinates), cursors, wrap=cyclic)
    return max(0., float(floor) - float(sampled[:, :, 1].min()))


def _playback_failing_intervals(coordinates, rig, pinned, contact_targets, *,
                                cyclic=False, floor=None):
    """One clip-wide quarter-frame sample; return planted intervals over the gate."""
    coords = np.asarray(coordinates, dtype=float)
    targets = np.asarray(contact_targets, dtype=float)
    count = len(coords)
    if count < 2 or not np.any(pinned):
        return []
    from .rig_playback import sample_rig
    interval_count = count if cyclic else count - 1
    cursors = (np.arange(interval_count)[:, None] + np.array([.25, .5, .75])).ravel()
    first = np.floor(cursors).astype(int)
    last = (first + 1) % count if cyclic else np.minimum(first + 1, count - 1)
    active = pinned[first] & pinned[last]
    if not np.any(active):
        return []
    sampled = sample_rig(_sampling_payload(rig, coords), cursors, wrap=cyclic)
    keyframe = rig.decode(coords)
    failing = []
    for start in range(interval_count):
        rows = slice(start * 3, start * 3 + 3)
        mask = active[rows]
        if not np.any(mask):
            continue
        frames = (start, (start + 1) % count)
        pair_pin = pinned[list(frames)]
        play_err = float(np.max(np.linalg.norm(
            (sampled[rows] - targets[start])[mask], axis=-1), initial=0.))
        key_err = float(np.max(np.linalg.norm(
            (keyframe[list(frames)] - targets[list(frames)])[pair_pin], axis=-1), initial=0.))
        floor_err = 0. if floor is None else max(
            0., float(floor) - float(sampled[rows, :, 1].min()))
        if (play_err >= PLAYBACK_CONTACT_LIMIT_METERS
                or key_err >= PLAYBACK_CONTACT_LIMIT_METERS
                or floor_err > PLAYBACK_FLOOR_LIMIT_METERS):
            failing.append(int(start))
    return failing


def _root_shift_failing_playback_intervals(coordinates, rig, pinned, contact_targets, *,
                                           cyclic=False, floor=None, failing, passes=6,
                                           strength=1.25):
    """Rigid endpoint root shifts for failing planted intervals — no dense Jacobian."""
    del floor  # floor failures are handled by apply_supported_floor_clearance
    coords = np.asarray(coordinates, dtype=float).copy()
    targets = np.asarray(contact_targets, dtype=float)
    count = len(coords)
    if not failing:
        return coords
    from .rig_playback import sample_rig
    sample_cursors = np.array([.25, .5, .75])
    gain = float(strength)
    for _ in range(max(1, int(passes))):
        shifts = np.zeros((count, 3), dtype=float)
        weights = np.zeros(count, dtype=float)
        for start in failing:
            frames = (start, (start + 1) % count)
            pair = coords[list(frames)]
            pair_pin = pinned[list(frames)]
            active = pair_pin[0] & pair_pin[1]
            if not np.any(active):
                continue
            sampled = sample_rig(_sampling_payload(rig, pair), sample_cursors, wrap=False)
            delta = targets[start] - sampled
            mean = np.mean(delta[:, active], axis=(0, 1))
            if not np.isfinite(mean).all():
                continue
            shifts[frames[0]] += mean
            shifts[frames[1]] += mean
            weights[frames[0]] += 1.
            weights[frames[1]] += 1.
        if not np.any(weights):
            break
        max_shift = float(np.max(np.linalg.norm(
            shifts / np.maximum(weights, 1.)[:, None], axis=-1)))
        coords[:, :3] += gain * shifts / np.maximum(weights, 1.)[:, None]
        if max_shift < 1e-5:
            break
    return coords


def _distal_plant_chain_slots(rig, pinned, *, depth=2):
    """Plant joints plus movable ancestors; fixed sockets do not consume a DOF."""
    plant_joints = [j for j in range(pinned.shape[1]) if pinned[:, j].any()]
    chain = set()
    for joint in plant_joints:
        cursor = joint
        remaining = int(depth) + 1
        while cursor >= 0 and remaining:
            if cursor in rig.slots:
                chain.add(cursor)
                remaining -= 1
            cursor = rig.parents[cursor]
    return sorted(chain)


def _contiguous_interval_runs(failing):
    """Group sorted failing interval indices into contiguous inclusive runs."""
    ordered = sorted({int(f) for f in failing})
    if not ordered:
        return []
    runs = []
    start = prev = ordered[0]
    for value in ordered[1:]:
        if value == prev + 1:
            prev = value
            continue
        runs.append((start, prev))
        start = prev = value
    runs.append((start, prev))
    return runs


def _hermite_stencil_frames(intervals, count, *, cyclic):
    """Keyframe indices whose DOFs affect hermite samples on the given intervals.

    limited_tangents(frame) uses neighbors frame-1 and frame+1, so mid-samples on
    [i, i+1] depend on frames {i-1, i, i+1, i+2}. Endpoint-only TRF cannot cancel
    tangent-driven plant bows.
    """
    frames = set()
    for start in intervals:
        for frame in (int(start), (int(start) + 1) % count):
            for delta in (-1, 0, 1):
                neighbor = frame + delta
                if cyclic:
                    frames.add(neighbor % count)
                elif 0 <= neighbor < count:
                    frames.add(neighbor)
    return sorted(frames)


def _trf_playback_run_coupled(
        coordinates, intervals, rig, pinned, contact_targets, chain, *,
        cyclic=False, floor=None, max_nfev=40, deadline=None, spike_reference=None):
    """Jointly refine failing planted intervals in one full-clip hermite TRF.

    Free the hermite stencil around every failing interval (not just endpoints).
    Mid samples are batched into one sample_rig call so sparse multi-seam polish
    stays deadline-friendly.
    """
    from .rig_playback import sample_rig
    coords = np.asarray(coordinates, dtype=float)
    targets = np.asarray(contact_targets, dtype=float)
    count = len(coords)
    intervals = sorted({int(start) for start in intervals})
    if not intervals:
        return coords
    frames = _hermite_stencil_frames(intervals, count, cyclic=cyclic)
    scored = [(start, 40000.) for start in intervals]
    # Soft-hold immediate neighbors so tangent edits do not spill into cleared gaps.
    interval_count = count if cyclic else count - 1
    failing_set = set(intervals)
    for start in intervals:
        for neighbor in (start - 1, start + 1):
            if cyclic:
                neighbor %= interval_count
            elif not 0 <= neighbor < interval_count:
                continue
            if neighbor not in failing_set:
                scored.append((neighbor, 5000.))
    # De-dupe while preferring the higher failing weight.
    merged = {}
    for start, weight in scored:
        merged[start] = max(merged.get(start, 0.), weight)
    scored = sorted(merged.items())
    parts = []
    for frame in frames:
        parts.append((frame, 0, 3))
        for joint in chain:
            slot = rig.slots[joint]
            parts.append((frame, slot, slot + 3))
    if not parts:
        return coords
    x0 = np.concatenate([coords[frame, begin:end] for frame, begin, end in parts])
    original = x0.copy()
    frame_index = np.asarray(frames, dtype=int)
    spike_rows = np.empty(0, dtype=int)
    if spike_reference is not None:
        from .temporal_quality import SPIKE_JOINT_NAMES, introduced_joint_spike_limit
        spike_joints = [rig.names.index(name) for name in SPIKE_JOINT_NAMES]
        spike_rows = np.asarray([i for i in range(1, count - 1)
                                 if any(frame in frames for frame in (i - 1, i, i + 1))])
        source_relative = np.asarray(spike_reference) - np.asarray(spike_reference)[:, rig.root:rig.root + 1]
        before_size = .5 * np.linalg.norm(np.diff(source_relative[:, spike_joints], n=2, axis=0), axis=-1)
        initial_points = rig.decode(coords)
        spike_scale = float(np.median(np.linalg.norm(np.ptp(initial_points, axis=1), axis=-1)))
        spike_limits = introduced_joint_spike_limit(before_size[spike_rows - 1], spike_scale)
    before_play = _playback_contact_sample_error(
        coords, rig, pinned, targets, cyclic=cyclic)
    # Near the gate, prefer mid-sample closure over keyframe tightness (still
    # rejected if key leaves the 0.5 mm playback contact limit).
    key_weight = 5000. if before_play < 0.001 else 10000.
    mid_cursors = []
    mid_meta = []  # (start, weight)
    for start, weight in scored:
        boost = 1.5 if before_play < 0.001 and weight >= 40000. else 1.
        for frac in (0.25, 0.5, 0.75):
            mid_cursors.append(start + frac)
            mid_meta.append((start, weight * boost))
    mid_cursors = np.asarray(mid_cursors, dtype=float)

    # A sample only depends on its Hermite stencil, not every free frame.
    # Dense finite differences previously decoded the whole clip once per
    # coordinate and often exhausted the polish deadline before one update.
    frame_columns = defaultdict(list)
    column = 0
    for frame, begin, end in parts:
        frame_columns[frame].extend(range(column, column + end - begin))
        column += end - begin
    blocks = [(3 * int(pinned[frame].sum()), [frame]) for frame in frames]
    for start, _weight in mid_meta:
        active = pinned[start] & pinned[(start + 1) % count]
        stencil = _hermite_stencil_frames([start], count, cyclic=cyclic)
        if np.any(active):
            blocks.append((3 * int(active.sum()), stencil))
        if floor is not None:
            blocks.append((len(rig.names), stencil))
    for frame in spike_rows:
        blocks.append((len(spike_joints), [frame - 1, frame, frame + 1]))
    row_count = sum(size for size, _ in blocks)
    pattern = lil_matrix((row_count, len(x0)), dtype=np.int8)
    row = 0
    for size, dependencies in blocks:
        columns = [col for frame in dependencies for col in frame_columns[frame]]
        if size and columns:
            pattern[row:row + size, columns] = 1
        row += size
    pattern = vstack([pattern.tocsr(), eye(len(x0), format='csr')], format='csr')
    best_values, best_cost = x0.copy(), float('inf')

    class PlaybackConstraintsSatisfied(Exception):
        pass

    def unpack(values):
        trial = coords.copy()
        offset = 0
        for frame, begin, end in parts:
            width = end - begin
            trial[frame, begin:end] = values[offset:offset + width]
            offset += width
        return trial

    def residual(values):
        nonlocal best_values, best_cost
        if deadline is not None and monotonic() >= deadline:
            raise TimeoutError
        trial = unpack(values)
        points = rig.decode(trial)
        chunks = [
            key_weight * (points[frame_index] - targets[frame_index])[pinned[frame_index]].ravel(),
        ]
        mid_error, floor_error = 0., 0.
        if mid_cursors.size:
            mid = sample_rig(_sampling_payload(rig, trial), mid_cursors, wrap=cyclic)
            for row, (start, weight) in enumerate(mid_meta):
                active = pinned[start] & pinned[(start + 1) % count]
                if np.any(active):
                    delta = (mid[row] - targets[start])[active]
                    chunks.append(float(weight) * delta.ravel())
                    mid_error = max(mid_error, float(np.max(np.linalg.norm(delta, axis=-1))))
                if floor is not None:
                    chunks.append(2000. * np.minimum(mid[row, :, 1] - float(floor), 0.).ravel())
                    floor_error = max(floor_error, float(floor) - float(mid[row, :, 1].min()))
        spikes_clear = True
        if spike_rows.size:
            relative = points - points[:, rig.root:rig.root + 1]
            sizes = .5 * np.linalg.norm(np.diff(relative[:, spike_joints], n=2, axis=0), axis=-1)[spike_rows - 1]
            chunks.append((20000. * np.maximum(sizes - .95 * spike_limits, 0.)).ravel())
            spikes_clear = bool(np.all(sizes <= spike_limits))
        chunks.append(0.001 * (values - original))
        errors = np.concatenate(chunks)
        cost = float(errors @ errors)
        if cost < best_cost:
            best_values, best_cost = values.copy(), cost
        key_error = float(np.max(np.linalg.norm((points - targets)[pinned], axis=-1), initial=0.))
        if (key_error < PLAYBACK_CONTACT_LIMIT_METERS
                and mid_error < PLAYBACK_CONTACT_LIMIT_METERS
                and floor_error <= PLAYBACK_FLOOR_LIMIT_METERS and spikes_clear):
            # This run has met its playback constraints. Continuing to minimize
            # tiny residuals starves later failing runs of the shared deadline.
            best_values = values.copy()
            raise PlaybackConstraintsSatisfied()
        return errors

    try:
        solved = least_squares(
            residual, x0, method='trf', jac_sparsity=pattern,
            max_nfev=int(max_nfev), ftol=1e-10, xtol=1e-10)
    except (TimeoutError, PlaybackConstraintsSatisfied):
        # Preserve useful work, subject to the same contact gates below.
        # Hitting the deadline must not discard a completed feasible iterate.
        solved = SimpleNamespace(x=best_values)
    except (np.linalg.LinAlgError, ValueError):
        return coords
    projected = unpack(solved.x)
    after_key = float(np.max(np.linalg.norm(
        (rig.decode(projected) - targets)[pinned], axis=-1), initial=0.))
    after_play = _playback_contact_sample_error(
        projected, rig, pinned, targets, cyclic=cyclic)
    # Key may rise within the gate to cancel hermite mid bows; only reject when
    # key leaves the gate or mid-sample error gets worse while still failing.
    if after_key >= PLAYBACK_CONTACT_LIMIT_METERS:
        return coords
    if (after_play > before_play * 1.01 + 1e-9
            and after_play >= PLAYBACK_CONTACT_LIMIT_METERS):
        return coords
    return projected


def project_introduced_spikes_coordinates(coordinates, rig, pinned, contact_targets,
                                         reference, *, fps, cyclic=False, floor=None,
                                         deadline=None):
    """Repair local processing spikes jointly with their contact transitions."""
    coords = np.asarray(coordinates, dtype=float).copy()
    deadline = monotonic() + 16. if deadline is None else deadline
    if monotonic() >= deadline:
        return coords
    points = rig.decode(coords)
    if monotonic() >= deadline:
        return coords
    events = relative_motion_quality(
        points, points, rig.names, fps, spike_reference=reference)['introducedSpikes']['events']
    if not events or monotonic() >= deadline:
        return coords
    intervals = sorted({i for event in events
                        for i in range(max(0, event['frameIndex'] - 2),
                                       min(len(coords) - 1, event['frameIndex'] + 2))})
    chain = set(_plant_chain_slots(rig, pinned))
    for event in events:
        ancestor = rig.names.index(event['joint'])
        while ancestor >= 0:
            if ancestor in rig.slots:
                chain.add(ancestor)
            ancestor = rig.parents[ancestor]
    for start, stop in _contiguous_interval_runs(intervals):
        if monotonic() >= deadline:
            break
        coords = _trf_playback_run_coupled(
            coords, range(start, stop + 1), rig, pinned, contact_targets, sorted(chain),
            cyclic=cyclic, floor=floor, max_nfev=40, deadline=deadline,
            spike_reference=reference)
    return coords


def _trf_playback_interval(pair, rig, pair_pin, pair_targets, active, chain, *,
                           floor=None, max_nfev=5, deadline=None):
    """Two-frame plant-chain TRF for one failing planted interval.

    Only valid as a coarse pass when keyframes are still off gate. Mid-sample
    scoring on an isolated pair uses degenerate hermite tangents; once endpoints
    hold, use `_trf_playback_interval_in_clip` instead.
    """
    from .rig_playback import sample_rig
    sample_cursors = np.array([.25, .5, .75])
    parts = []
    for local_i in range(2):
        if not pair_pin[local_i].any():
            continue
        parts.append((local_i, 0, 3))
        for joint in chain:
            slot = rig.slots[joint]
            parts.append((local_i, slot, slot + 3))
    if not parts:
        return pair
    x0 = np.concatenate([pair[local_i, begin:end] for local_i, begin, end in parts])
    original = x0.copy()

    def unpack(values):
        trial = pair.copy()
        offset = 0
        for local_i, begin, end in parts:
            width = end - begin
            trial[local_i, begin:end] = values[offset:offset + width]
            offset += width
        return trial

    def residual(values):
        if deadline is not None and monotonic() >= deadline:
            raise TimeoutError
        trial = unpack(values)
        points = rig.decode(trial)
        err = (points - pair_targets)[pair_pin].ravel()
        mid = sample_rig(_sampling_payload(rig, trial), sample_cursors, wrap=False)
        err = np.r_[err, (mid - pair_targets[0])[:, active].ravel()]
        if floor is not None:
            err = np.r_[err, np.minimum(mid[:, :, 1] - float(floor), 0.).ravel()]
        return np.r_[2000. * err, 0.05 * (values - original)]

    def peak(trial):
        points = rig.decode(trial)
        key = float(np.max(np.linalg.norm((points - pair_targets)[pair_pin], axis=-1), initial=0.))
        mid = sample_rig(_sampling_payload(rig, trial), sample_cursors, wrap=False)
        play = float(np.max(np.linalg.norm((mid - pair_targets[0])[:, active], axis=-1), initial=0.))
        pen = 0. if floor is None else max(0., float(floor) - float(mid[:, :, 1].min()))
        return max(key, play, max(0., pen - PLAYBACK_FLOOR_LIMIT_METERS))

    before = peak(pair)
    try:
        solved = least_squares(
            residual, x0, method='trf', max_nfev=int(max_nfev), ftol=1e-8, xtol=1e-8)
    except (TimeoutError, np.linalg.LinAlgError, ValueError):
        return pair
    projected = unpack(solved.x)
    return projected if peak(projected) <= before * 1.01 else pair


def _trf_playback_interval_in_clip(
        coordinates, start, rig, pinned, contact_targets, chain, *,
        cyclic=False, floor=None, max_nfev=16, deadline=None):
    """Refine one planted interval against full-clip hermite samples.

    Playback hermite tangents depend on neighboring keyframes. Scoring mids on an
    isolated two-frame pair therefore optimizes a different path than acceptance.
    """
    coords = np.asarray(coordinates, dtype=float)
    count = len(coords)
    frames = (int(start), (int(start) + 1) % count)
    pair_pin = pinned[list(frames)]
    active = pair_pin[0] & pair_pin[1]
    if not np.any(active):
        return coords
    return _trf_playback_run_coupled(
        coords, [int(start)], rig, pinned, contact_targets, chain,
        cyclic=cyclic, floor=floor, max_nfev=max_nfev, deadline=deadline)


def project_interval_playback_plants(coordinates, rig, pinned, contact_targets, *,
                                     cyclic=False, floor=None, max_nfev=5, deadline=None,
                                     spike_reference=None):
    """Hold planted contacts on interpolated samples.

    Large keyframe misses get a root shift then coarse two-frame TRF. When
    endpoints already hold, failing intervals are refined together in full-clip
    hermite context so neighbor tangents and sparse seams stop fighting each other.
    """
    coords = np.asarray(coordinates, dtype=float).copy()
    targets = np.asarray(contact_targets, dtype=float)
    count = len(coords)
    if count < 2 or not np.any(pinned) or (deadline is not None and monotonic() >= deadline):
        return coords
    failing = _playback_failing_intervals(
        coords, rig, pinned, targets, cyclic=cyclic, floor=floor)
    if not failing or (deadline is not None and monotonic() >= deadline):
        return coords
    key_peak = float(np.max(np.linalg.norm(
        (rig.decode(coords) - targets)[pinned], axis=-1), initial=0.))
    endpoints_hold = key_peak < PLAYBACK_CONTACT_LIMIT_METERS
    if not endpoints_hold:
        coords = _root_shift_failing_playback_intervals(
            coords, rig, pinned, targets, cyclic=cyclic, floor=floor, failing=failing,
            passes=8)
        failing = _playback_failing_intervals(
            coords, rig, pinned, targets, cyclic=cyclic, floor=floor)
        if not failing:
            return coords
        leftover_frames = sorted({f for start in failing for f in (start, (start + 1) % count)})
        frame_mask = np.zeros(count, dtype=bool)
        frame_mask[leftover_frames] = True
        endpoint_pin = pinned & frame_mask[:, None]
        if np.any(endpoint_pin):
            coords = project_contact_plant_coordinates(
                coords, rig, endpoint_pin, targets, max_nfev=20, deadline=deadline)
            coords = _root_shift_failing_playback_intervals(
                coords, rig, pinned, targets, cyclic=cyclic, floor=floor, failing=failing,
                passes=6)
            failing = _playback_failing_intervals(
                coords, rig, pinned, targets, cyclic=cyclic, floor=floor)
            if not failing:
                return coords
            key_peak = float(np.max(np.linalg.norm(
                (rig.decode(coords) - targets)[pinned], axis=-1), initial=0.))
            endpoints_hold = key_peak < PLAYBACK_CONTACT_LIMIT_METERS
        chain = _plant_chain_slots(rig, pinned)
        for start in failing:
            if deadline is not None and monotonic() >= deadline:
                break
            frames = (start, (start + 1) % count)
            pair_pin = pinned[list(frames)]
            active = pair_pin[0] & pair_pin[1]
            if not np.any(active):
                continue
            projected = _trf_playback_interval(
                coords[list(frames)].copy(), rig, pair_pin, targets[list(frames)],
                active, chain, floor=floor, max_nfev=max_nfev, deadline=deadline)
            coords[list(frames)] = projected
        failing = _playback_failing_intervals(
            coords, rig, pinned, targets, cyclic=cyclic, floor=floor)
        if not failing:
            return coords
        key_peak = float(np.max(np.linalg.norm(
            (rig.decode(coords) - targets)[pinned], axis=-1), initial=0.))
        endpoints_hold = key_peak < PLAYBACK_CONTACT_LIMIT_METERS
    if not failing:
        return coords
    # Preserve the source temporal evidence across every local contact solve.
    # Otherwise root corrections can close plants by introducing pelvis/limb
    # acceleration spikes, including during velocity-continuity repair.
    from functools import partial
    project_run = partial(_trf_playback_run_coupled,
                          spike_reference=spike_reference)
    # Endpoints hold: hermite-stencil TRF on contiguous failing runs. Sparse seams
    # must be iterated — a joint residual over all gaps often stalls, while
    # per-run distal solves accumulate to the playback gate.
    play_peak = _playback_contact_sample_error(
        coords, rig, pinned, targets, cyclic=cyclic)
    near_miss_mid = endpoints_hold and play_peak < 0.003
    # Hip sockets have no independent rotation in the fixed rig. Include their
    # movable parent so a planted-foot trajectory can adjust its proximal frame.
    # Final articulation/anatomy gates still reject destructive pose changes.
    chain = _distal_plant_chain_slots(rig, pinned, depth=3)
    nfev = max(int(max_nfev), 8 if near_miss_mid else 24)
    if near_miss_mid:
        # Cheap root pass — only when the bow is tiny (translation-dominated).
        if play_peak < 0.001 and (deadline is None or monotonic() < deadline):
            coords = project_run(
                coords, failing, rig, pinned, targets, [],
                cyclic=cyclic, floor=floor, max_nfev=max(6, int(max_nfev)),
                deadline=deadline)
            if (_playback_contact_sample_error(
                    coords, rig, pinned, targets, cyclic=cyclic)
                    < PLAYBACK_CONTACT_LIMIT_METERS):
                return coords
            failing = _playback_failing_intervals(
                coords, rig, pinned, targets, cyclic=cyclic, floor=floor)
        for _ in range(8):
            if not failing:
                return coords
            if deadline is not None and monotonic() >= deadline:
                break
            before = _playback_contact_sample_error(
                coords, rig, pinned, targets, cyclic=cyclic)
            for run_start, run_end in _contiguous_interval_runs(failing):
                if deadline is not None:
                    remaining = deadline - monotonic()
                    if remaining < 1.5:
                        break
                    run_nfev = min(nfev, max(4, int(remaining * 2)))
                else:
                    run_nfev = nfev
                coords = project_run(
                    coords, list(range(run_start, run_end + 1)), rig, pinned, targets,
                    chain, cyclic=cyclic, floor=floor, max_nfev=run_nfev,
                    deadline=deadline)
                if (_playback_contact_sample_error(
                        coords, rig, pinned, targets, cyclic=cyclic)
                        < PLAYBACK_CONTACT_LIMIT_METERS):
                    return coords
            failing = _playback_failing_intervals(
                coords, rig, pinned, targets, cyclic=cyclic, floor=floor)
            after = _playback_contact_sample_error(
                coords, rig, pinned, targets, cyclic=cyclic)
            if after < PLAYBACK_CONTACT_LIMIT_METERS:
                return coords
            if after >= before * 0.995 and after >= PLAYBACK_CONTACT_LIMIT_METERS:
                # Distal TRF often stalls ~0.05 mm over the gate; a cheap
                # root-only coupled pass on the leftover gaps closes that gap
                # without a second outer call.
                if after < 0.001 and failing and (
                        deadline is None or monotonic() < deadline):
                    coords = project_run(
                        coords, failing, rig, pinned, targets, [],
                        cyclic=cyclic, floor=floor, max_nfev=max(6, int(max_nfev)),
                        deadline=deadline)
                    if (_playback_contact_sample_error(
                            coords, rig, pinned, targets, cyclic=cyclic)
                            < PLAYBACK_CONTACT_LIMIT_METERS):
                        return coords
                    failing = _playback_failing_intervals(
                        coords, rig, pinned, targets, cyclic=cyclic, floor=floor)
                if deadline is not None and deadline - monotonic() < 2.0:
                    break
                # Stall: one joint distal solve on remaining gaps.
                coords = project_run(
                    coords, failing, rig, pinned, targets, chain,
                    cyclic=cyclic, floor=floor, max_nfev=max(nfev, 16), deadline=deadline)
                if (_playback_contact_sample_error(
                        coords, rig, pinned, targets, cyclic=cyclic)
                        < PLAYBACK_CONTACT_LIMIT_METERS):
                    return coords
                break
        # Final near-gate root pass if distal iterations left a sub-mm miss.
        after = _playback_contact_sample_error(
            coords, rig, pinned, targets, cyclic=cyclic)
        if (PLAYBACK_CONTACT_LIMIT_METERS <= after < 0.001
                and (deadline is None or monotonic() < deadline)):
            leftover = _playback_failing_intervals(
                coords, rig, pinned, targets, cyclic=cyclic, floor=floor)
            if leftover:
                coords = project_run(
                    coords, leftover, rig, pinned, targets, [],
                    cyclic=cyclic, floor=floor, max_nfev=max(6, int(max_nfev)),
                    deadline=deadline)
        return coords
    window = 6
    for run_start, run_end in _contiguous_interval_runs(failing):
        if deadline is not None and monotonic() >= deadline:
            break
        cursor = run_start
        while cursor <= run_end:
            if deadline is not None and monotonic() >= deadline:
                break
            chunk_end = min(run_end, cursor + window - 1)
            coords = project_run(
                coords, list(range(cursor, chunk_end + 1)), rig, pinned, targets, chain,
                cyclic=cyclic, floor=floor, max_nfev=nfev, deadline=deadline)
            if (_playback_contact_sample_error(
                    coords, rig, pinned, targets, cyclic=cyclic)
                    < PLAYBACK_CONTACT_LIMIT_METERS):
                return coords
            if chunk_end >= run_end:
                break
            cursor = chunk_end
    return coords


def apply_supported_floor_clearance(coordinates, rig, pinned, contact_targets, floor, *,
                                    cyclic=False):
    """Lift unsupported interpolated geometry, keeping the result only if plants still hold."""
    coords = np.asarray(coordinates, dtype=float).copy()
    from .rig_playback import unanchored_floor_clearance_lift, free_joint_floor_clearance_lift
    payload = _sampling_payload(rig, coords)
    if not np.any(pinned):
        lift = unanchored_floor_clearance_lift(payload, floor, pinned, cyclic=cyclic)
        if lift > 0:
            coords[:, 1] += lift
        return coords, float(lift)
    lift = free_joint_floor_clearance_lift(payload, floor, pinned, cyclic=cyclic)
    if lift <= 0:
        return coords, 0.0

    def plants_hold(values):
        key = float(np.max(np.linalg.norm((rig.decode(values) - contact_targets)[pinned], axis=-1), initial=0.))
        play = _playback_contact_sample_error(values, rig, pinned, contact_targets, cyclic=cyclic)
        return key < PLAYBACK_CONTACT_LIMIT_METERS and play < PLAYBACK_CONTACT_LIMIT_METERS

    for freeze_root in (True, False):
        trial = coords.copy()
        trial[:, 1] += lift
        trial = project_contact_plant_coordinates(
            trial, rig, pinned, contact_targets, max_nfev=40, freeze_root=freeze_root)
        if plants_hold(trial):
            return trial, float(lift)
    return coords, 0.0


def _batched_projection_jacobian(rig, coordinates, columns, residuals, weight, prior_weight):
    """Differentiate independent pose residuals with one batched FK traversal."""
    step = 1e-6
    trials = np.repeat(coordinates[None, :], len(columns) + 1, axis=0)
    trials[np.arange(1, len(columns) + 1), columns] += step
    errors = np.asarray(residuals(rig.decode(trials))).reshape(len(trials), -1)
    return np.vstack([weight * (errors[1:] - errors[0]).T / step,
                      prior_weight * np.eye(len(columns))])


def project_contact_plant_coordinates(coordinates, rig, pinned, contact_targets, *, max_nfev=40,
                                      freeze_root=False, deadline=None):
    """Hard-project root + planted-chain DOFs onto contact targets.

    Root translation alone cannot clear relative plant error between two feet.
    A small TRF on the planted limb slots targets the 0.5 mm contact gate.
    When freeze_root is set, only limb slots move — used after root-continuity
    projection so contact recovery cannot reintroduce pelvis spikes.

    Long clips use per-frame TRF so each solve stays tiny and a deadline can
    stop between frames. Clip-wide TRF previously burned minutes past the
    soft watchdog on ~150-frame plant-only fits.
    """
    coords = np.asarray(coordinates, dtype=float).copy()
    if coords.ndim != 2 or not np.any(pinned):
        return coords
    targets = np.asarray(contact_targets, dtype=float)
    count = len(coords)
    plant_joints = [j for j in range(pinned.shape[1]) if pinned[:, j].any()]
    chain = set()
    for joint in plant_joints:
        ancestor = joint
        while ancestor >= 0:
            if ancestor in rig.slots:
                chain.add(ancestor)
            ancestor = rig.parents[ancestor]
    chain = sorted(chain)

    def _project_frame(frame_coords, frame_pin, frame_targets, frame_max_nfev):
        if not np.any(frame_pin):
            return frame_coords
        parts = []
        if not freeze_root:
            parts.append((0, 3))
        for joint in chain:
            slot = rig.slots[joint]
            parts.append((slot, slot + 3))
        if not parts:
            return frame_coords
        x0 = np.concatenate([frame_coords[start:stop] for start, stop in parts])
        original = x0.copy()
        columns = np.array([column for start, stop in parts for column in range(start, stop)])
        best_values, best_error = x0.copy(), float('inf')

        class ContactReached(Exception):
            pass

        def unpack(values):
            trial = frame_coords.copy()
            offset = 0
            for start, stop in parts:
                width = stop - start
                trial[start:stop] = values[offset:offset + width]
                offset += width
            return trial

        def residual(values):
            nonlocal best_values, best_error
            if deadline is not None and monotonic() >= deadline:
                raise TimeoutError
            points = rig.decode(unpack(values)[None, :])[0]
            err = (points - frame_targets)[frame_pin].ravel()
            error = float(np.max(np.linalg.norm(err.reshape(-1, 3), axis=-1), initial=0.))
            if error < best_error:
                best_values, best_error = values.copy(), error
            if error < .05 * PLAYBACK_CONTACT_LIMIT_METERS:
                raise ContactReached
            return np.r_[2000. * err, 0.05 * (values - original)]

        def jacobian(values):
            if deadline is not None and monotonic() >= deadline:
                raise TimeoutError
            return _batched_projection_jacobian(
                rig, unpack(values), columns,
                lambda points: (points - frame_targets)[:, frame_pin], 2000., .05)

        before = float(np.max(np.linalg.norm(
            (rig.decode(frame_coords[None, :])[0] - frame_targets)[frame_pin], axis=-1), initial=0.))
        try:
            solved = least_squares(
                residual, x0, jac=jacobian, method='trf', max_nfev=int(frame_max_nfev),
                ftol=1e-10, xtol=1e-10)
            projected = unpack(solved.x)
        except (ContactReached, TimeoutError):
            projected = unpack(best_values)
        except (np.linalg.LinAlgError, ValueError):
            return frame_coords
        after = float(np.max(np.linalg.norm(
            (rig.decode(projected[None, :])[0] - frame_targets)[frame_pin], axis=-1), initial=0.))
        return projected if after <= before * 1.01 else frame_coords

    # Prefer per-frame whenever a deadline is set or the clip is long enough that
    # a joint TRF would dominate the budget. Multiple passes over still-failing
    # frames converge relative foot error that a single low-nfev pass leaves.
    use_per_frame = deadline is not None or count > 24
    if use_per_frame:
        frame_nfev = min(max(int(max_nfev), 25), 40)
        gate = PLAYBACK_CONTACT_LIMIT_METERS
        for _pass in range(3):
            if deadline is not None and monotonic() >= deadline:
                break
            progressed = False
            for frame in range(count):
                if deadline is not None and monotonic() >= deadline:
                    break
                if not pinned[frame].any():
                    continue
                before = float(np.max(np.linalg.norm(
                    (rig.decode(coords[frame:frame + 1])[0] - targets[frame])[pinned[frame]],
                    axis=-1), initial=0.))
                if before < gate:
                    continue
                coords[frame] = _project_frame(
                    coords[frame], pinned[frame], targets[frame], frame_nfev)
                after = float(np.max(np.linalg.norm(
                    (rig.decode(coords[frame:frame + 1])[0] - targets[frame])[pinned[frame]],
                    axis=-1), initial=0.))
                if after < before * 0.98:
                    progressed = True
            if not progressed:
                break
            peak = float(np.max(np.linalg.norm(
                (rig.decode(coords) - targets)[pinned], axis=-1), initial=0.))
            if peak < gate:
                break
        return coords

    parts = []
    for frame in range(count):
        if not pinned[frame].any():
            continue
        if not freeze_root:
            parts.append((frame, 0, 3))
        for joint in chain:
            slot = rig.slots[joint]
            parts.append((frame, slot, slot + 3))
    if not parts:
        return coords
    x0 = np.concatenate([coords[frame, start:stop] for frame, start, stop in parts])
    original = x0.copy()

    def unpack(values):
        trial = coords.copy()
        offset = 0
        for frame, start, stop in parts:
            width = stop - start
            trial[frame, start:stop] = values[offset:offset + width]
            offset += width
        return trial

    def residual(values):
        if deadline is not None and monotonic() >= deadline:
            raise TimeoutError
        points = rig.decode(unpack(values))
        err = (points - targets)[pinned].ravel()
        return np.r_[2000. * err, 0.05 * (values - original)]

    before = float(np.max(np.linalg.norm((rig.decode(coords) - targets)[pinned], axis=-1), initial=0.))
    try:
        solved = least_squares(
            residual, x0, method='trf', max_nfev=int(max_nfev), ftol=1e-10, xtol=1e-10)
    except (TimeoutError, np.linalg.LinAlgError, ValueError):
        return coords
    projected = unpack(solved.x)
    after = float(np.max(np.linalg.norm((rig.decode(projected) - targets)[pinned], axis=-1), initial=0.))
    return projected if after <= before * 1.01 else coords


def _rigid_pair_arm_slots(rig, names, equipment, pinned=None):
    """Distal arm DOFs for rigid_pair projection — never plant or torso slots."""
    pair = equipment.get('endpointPair') or []
    if len(pair) != 2 or any(name not in names for name in pair):
        return []
    endpoints = [names.index(name) for name in pair]
    plant_joints = set()
    if pinned is not None and np.any(pinned):
        for joint in range(pinned.shape[1]):
            if pinned[:, joint].any():
                ancestor = joint
                while ancestor >= 0:
                    plant_joints.add(ancestor)
                    ancestor = rig.parents[ancestor]
    torso = {
        names.index(n) for n in (
            'pelvis', 'spine', 'spine1', 'spine2', 'spine3', 'neck', 'head',
            'left_hip', 'right_hip', 'left_knee', 'right_knee',
            'left_ankle', 'right_ankle', 'left_foot', 'right_foot',
        ) if n in names
    }
    arm_joints = set()
    for joint in endpoints:
        ancestor = joint
        while ancestor >= 0:
            if (ancestor in rig.slots and ancestor not in plant_joints
                    and ancestor not in torso):
                arm_joints.add(ancestor)
            ancestor = rig.parents[ancestor]
    return sorted(rig.slots[j] for j in arm_joints)


def project_rigid_pair_grip_coordinates(coordinates, rig, names, equipment, *,
                                        pinned=None, max_nfev=15, deadline=None):
    """Hard-project arm-chain DOFs onto a rigid hand/wrist spacing.

    Soft grip weights lose to contact/anatomy on reconstruction noise with
    tens of centimeters of spacing variance. Per-frame arm TRF enforces the
    calibrated distance without touching planted limb slots.
    """
    coords = np.asarray(coordinates, dtype=float).copy()
    if (coords.ndim != 2
            or equipment.get('handRelationship') != 'rigid_pair'
            or not equipment.get('available')):
        return coords
    arm_slots = _rigid_pair_arm_slots(rig, names, equipment, pinned=pinned)
    if not arm_slots:
        return coords
    from .equipment_constraints import grip_residual

    tolerance = float(equipment.get('toleranceMeters') or 0.005)
    for _pass in range(3):
        if deadline is not None and monotonic() >= deadline:
            break
        progressed = False
        for frame in range(len(coords)):
            if deadline is not None and monotonic() >= deadline:
                break
            frame_coords = coords[frame].copy()
            before = float(abs(grip_residual(
                rig.decode(frame_coords[None, :]), names, equipment)).max(initial=0.))
            if before <= tolerance:
                continue
            x0 = np.concatenate([frame_coords[slot:slot + 3] for slot in arm_slots])
            original = x0.copy()
            columns = np.array([slot + axis for slot in arm_slots for axis in range(3)])
            best_values, best_error = x0.copy(), before

            class GripReached(Exception):
                pass

            def unpack(values, base=frame_coords):
                trial = base.copy()
                offset = 0
                for slot in arm_slots:
                    trial[slot:slot + 3] = values[offset:offset + 3]
                    offset += 3
                return trial

            def residual(values, prior=original):
                nonlocal best_values, best_error
                if deadline is not None and monotonic() >= deadline:
                    raise TimeoutError
                points = rig.decode(unpack(values)[None, :])
                grip = grip_residual(points, names, equipment).ravel()
                error = float(np.max(abs(grip), initial=0.))
                if error < best_error:
                    best_values, best_error = values.copy(), error
                if error <= .05 * tolerance:
                    raise GripReached
                return np.r_[8000. * grip, 0.02 * (values - prior)]

            def jacobian(values):
                if deadline is not None and monotonic() >= deadline:
                    raise TimeoutError
                return _batched_projection_jacobian(
                    rig, unpack(values), columns,
                    lambda points: grip_residual(points, names, equipment), 8000., .02)

            try:
                solved = least_squares(
                    residual, x0, jac=jacobian, method='trf', max_nfev=max(1, int(max_nfev)),
                    ftol=1e-10, xtol=1e-10)
                projected = unpack(solved.x)
            except (GripReached, TimeoutError):
                projected = unpack(best_values)
            except (np.linalg.LinAlgError, ValueError):
                continue
            after = float(abs(grip_residual(
                rig.decode(projected[None, :]), names, equipment)).max(initial=0.))
            if after <= before * 1.01:
                coords[frame] = projected
                if after < before * 0.98:
                    progressed = True
        peak = float(abs(grip_residual(
            rig.decode(coords), names, equipment)).max(initial=0.))
        if peak <= tolerance or not progressed:
            break
    return coords


def _playback_grip_failing_intervals(coordinates, rig, names, equipment, *,
                                     cyclic=False):
    """Intervals whose hermite mid-samples miss the rigid_pair spacing gate."""
    from .equipment_constraints import grip_residual
    from .rig_playback import sample_rig
    if (equipment.get('handRelationship') != 'rigid_pair'
            or not equipment.get('available')):
        return []
    coords = np.asarray(coordinates, dtype=float)
    count = len(coords)
    if count < 2:
        return []
    tolerance = float(equipment.get('toleranceMeters') or 0.005)
    interval_count = count if cyclic else count - 1
    cursors = (np.arange(interval_count)[:, None] + np.array([.25, .5, .75])).ravel()
    sampled = sample_rig(_sampling_payload(rig, coords), cursors, wrap=cyclic)
    failing = []
    for start in range(interval_count):
        rows = slice(start * 3, start * 3 + 3)
        err = float(abs(grip_residual(sampled[rows], names, equipment)).max(initial=0.))
        if err > tolerance:
            failing.append(int(start))
    return failing


def _playback_grip_sample_error(coordinates, rig, names, equipment, *, cyclic=False):
    from .equipment_constraints import grip_residual
    from .rig_playback import sample_rig
    if (equipment.get('handRelationship') != 'rigid_pair'
            or not equipment.get('available')):
        return 0.
    coords = np.asarray(coordinates, dtype=float)
    count = len(coords)
    if count < 2:
        return 0.
    interval_count = count if cyclic else count - 1
    cursors = (np.arange(interval_count)[:, None] + np.array([.25, .5, .75])).ravel()
    sampled = sample_rig(_sampling_payload(rig, coords), cursors, wrap=cyclic)
    return float(abs(grip_residual(sampled, names, equipment)).max(initial=0.))


def project_playback_rigid_pair_grip(coordinates, rig, names, equipment, *,
                                     pinned=None, cyclic=False, max_nfev=16,
                                     deadline=None):
    """Hold rigid_pair spacing on hermite mid-samples, not only keyframes.

    Keyframe grip can pass while interpolated hand spacing bows past tolerance —
    the same hermite-neighbor issue as planted contacts.
    """
    from .equipment_constraints import grip_residual
    from .rig_playback import sample_rig
    coords = np.asarray(coordinates, dtype=float).copy()
    if (coords.ndim != 2
            or equipment.get('handRelationship') != 'rigid_pair'
            or not equipment.get('available')):
        return coords
    arm_slots = _rigid_pair_arm_slots(rig, names, equipment, pinned=pinned)
    if not arm_slots:
        return coords
    tolerance = float(equipment.get('toleranceMeters') or 0.005)
    failing = _playback_grip_failing_intervals(
        coords, rig, names, equipment, cyclic=cyclic)
    if not failing:
        return coords
    count = len(coords)
    nfev = max(8, int(max_nfev))
    for _ in range(4):
        if not failing:
            break
        if deadline is not None and monotonic() >= deadline:
            break
        before = _playback_grip_sample_error(
            coords, rig, names, equipment, cyclic=cyclic)
        for run_start, run_end in _contiguous_interval_runs(failing):
            if deadline is not None and deadline - monotonic() < 1.0:
                break
            intervals = list(range(run_start, run_end + 1))
            frames = _hermite_stencil_frames(intervals, count, cyclic=cyclic)
            parts = [(frame, slot, slot + 3)
                     for frame in frames for slot in arm_slots]
            if not parts:
                continue
            x0 = np.concatenate([coords[frame, begin:end] for frame, begin, end in parts])
            original = x0.copy()

            def unpack(values, _parts=parts):
                trial = coords.copy()
                offset = 0
                for frame, begin, end in _parts:
                    width = end - begin
                    trial[frame, begin:end] = values[offset:offset + width]
                    offset += width
                return trial

            mid_cursors = np.asarray(
                [start + frac for start in intervals for frac in (.25, .5, .75)],
                dtype=float)
            key_frames = np.asarray(frames, dtype=int)

            def residual(values):
                if deadline is not None and monotonic() >= deadline:
                    raise TimeoutError
                trial = unpack(values)
                points = rig.decode(trial)
                key_grip = grip_residual(points[key_frames], names, equipment).ravel()
                mid = sample_rig(_sampling_payload(rig, trial), mid_cursors, wrap=cyclic)
                mid_grip = grip_residual(mid, names, equipment).ravel()
                return np.concatenate([
                    8000. * key_grip, 20000. * mid_grip, 0.02 * (values - original)])

            try:
                solved = least_squares(
                    residual, x0, method='trf', max_nfev=nfev, ftol=1e-10, xtol=1e-10)
            except (TimeoutError, np.linalg.LinAlgError, ValueError):
                continue
            projected = unpack(solved.x)
            after = _playback_grip_sample_error(
                projected, rig, names, equipment, cyclic=cyclic)
            if after <= before * 1.01 + 1e-12:
                coords = projected
                if after <= tolerance:
                    return coords
        failing = _playback_grip_failing_intervals(
            coords, rig, names, equipment, cyclic=cyclic)
        after = _playback_grip_sample_error(
            coords, rig, names, equipment, cyclic=cyclic)
        if after >= before * 0.995:
            break
    return coords


def project_playback_neck_clearance(coordinates, rig, *, cyclic=False, deadline=None):
    """Keep the interpolated neck inside its socket before the playback guard.

    Clipping stored poses exactly onto the guard leaves Hermite overshoot to be
    clipped during playback, introducing velocity corners. Reserve the measured
    overshoot inside the stored-pose limit, changing only neck/head coordinates.
    Unresolved proposals are discarded; the caller still validates the motion.
    """
    from .physical_validation import SOCKET_ALIGNMENT_MAX_LATERAL_RATIO
    from .rig_playback import sample_rig_coordinates
    original = np.asarray(coordinates, dtype=float)
    required = ('neck', 'head', 'left_collar', 'right_collar')
    if len(original) < 3 or any(name not in rig.names for name in required):
        return original.copy()
    neck, head = (rig.names.index(name) for name in required[:2])
    if neck not in rig.slots or head not in rig.slots:
        return original.copy()
    left, right = (rig.offsets[rig.names.index(name)] for name in required[2:])
    width = float(np.linalg.norm(right - left))
    if width < 1e-12:
        return original.copy()
    lateral = (right - left) / width
    center = float(np.dot((left + right) * .5, lateral))
    guard = SOCKET_ALIGNMENT_MAX_LATERAL_RATIO - ANATOMY_FIT_MARGIN
    # Inspect the whole interpolated path, not only knot derivatives. Moving a
    # clipping corner between knots would hide the symptom from that check.
    intervals = len(original) if cyclic else len(original) - 1
    cursors = np.arange(intervals * 16 + (not cyclic), dtype=float) / 16.
    candidate = original.copy()
    inset = 0.
    for attempt in range(4):
        if deadline is not None and monotonic() >= deadline:
            break
        sampled = sample_rig_coordinates(_sampling_payload(rig, candidate), cursors, wrap=cyclic)
        slot = rig.slots[neck]
        vectors = Rotation.from_rotvec(sampled[:, slot:slot + 3]).apply(rig.offsets[neck])
        maximum = float(np.max(np.abs((vectors @ lateral - center) / width)))
        if maximum <= guard - ANATOMY_FIT_MARGIN:
            return candidate
        inset += max(ANATOMY_FIT_MARGIN, maximum - guard + ANATOMY_FIT_MARGIN)
        if inset >= guard or attempt == 3:
            break
        candidate = project_neck_attachment_values(
            original, rig.offsets, rig.names, rig.active, guard - inset)
    return original.copy()


def repair_playback_velocity_continuity(coordinates, rig, pinned, contact_targets, *,
                                        cyclic=False, sigma=1.0, names=None,
                                        equipment=None, deadline=None, floor=None,
                                        spike_reference=None, fps=30.):
    """Cut hermite knot velocity jumps without abandoning held plants/grip.

    Full mild rotation smooth clears C1 knot jumps from plant/grip TRF. Skip that
    smooth when the jump already clears so held mid-sample plants are not lifted.
    After a required smooth, mid-plant (with near-gate root close) restores the
    0.5 mm playback plant gate. Grip is re-held afterward.
    """
    from .rig_interpolation import frame_boundary_velocity_jump
    from .rig_playback import sample_rig
    from .physical_validation import body_scale

    coords = np.asarray(coordinates, dtype=float)
    if len(coords) < 3 or (deadline is not None and monotonic() >= deadline):
        return coords.copy()

    def _jump(values):
        count = len(values)
        knots = np.arange(count) if cyclic else np.arange(1, count - 1)
        if not len(knots):
            return 0.
        payload = _sampling_payload(rig, values)
        return frame_boundary_velocity_jump(
            lambda cursors: sample_rig(payload, cursors, wrap=cyclic), knots, fps)

    def _limit(values):
        return 0.001 * body_scale(rig.decode(values), rig.names)

    def _replant(values, *, max_nfev=24, budget=None):
        trial = values
        if pinned is None or not np.any(pinned) or contact_targets is None:
            return trial
        if deadline is not None and monotonic() >= deadline:
            return trial
        trial = project_contact_plant_coordinates(
            trial, rig, pinned, contact_targets, max_nfev=max_nfev,
            freeze_root=True, deadline=deadline)
        for _ in range(2):
            if not _playback_failing_intervals(
                    trial, rig, pinned, contact_targets, cyclic=cyclic, floor=floor):
                break
            if deadline is not None and monotonic() >= deadline:
                break
            before_jump = _jump(trial)
            # No artificial per-call cap when the outer deadline is open — a
            # short budget aborts the near-gate root close ~0.2 mm over limit.
            if budget is not None:
                plant_deadline = monotonic() + budget
                if deadline is not None:
                    plant_deadline = min(plant_deadline, deadline)
            else:
                plant_deadline = deadline
            candidate = project_interval_playback_plants(
                trial, rig, pinned, contact_targets, cyclic=cyclic, floor=floor,
                max_nfev=max_nfev, deadline=plant_deadline, spike_reference=spike_reference)
            if _jump(candidate) <= max(_limit(candidate) * 1.25, before_jump * 1.05):
                trial = candidate
            else:
                break
        return trial

    if _jump(coords) <= _limit(coords):
        smoothed = coords.copy()
    else:
        socket_clear = project_playback_neck_clearance(
            coords, rig, cyclic=cyclic, deadline=deadline)
        from .equipment_constraints import validate_grip
        if (not np.array_equal(socket_clear, coords)
                and _jump(socket_clear) <= _limit(socket_clear)
                and validate_grip(rig.decode(socket_clear), rig.names, equipment or {})['passed']):
            # No root/limb smoothing or replanting is needed for a neck-only
            # guard corner. Existing held contacts and grip remain identical.
            return socket_clear
        smoothed = temporal_coordinate_smooth(
            coords, cyclic=cyclic, sigma=min(float(sigma), 0.85))
        plant_budget = (
            None if deadline is None
            else max(4., deadline - monotonic()))
        smoothed = _replant(smoothed, max_nfev=24, budget=plant_budget)
        # Playback-plant TRF can recreate knot jumps — damp once more, then replant.
        if (deadline is None or monotonic() < deadline) and _jump(smoothed) > _limit(smoothed):
            smoothed = temporal_coordinate_smooth(smoothed, cyclic=cyclic, sigma=0.45)
            smoothed = _replant(smoothed, max_nfev=16)

    if (names is not None and equipment is not None
            and equipment.get('handRelationship') == 'rigid_pair'
            and equipment.get('available')
            and (deadline is None or monotonic() < deadline)):
        from .equipment_constraints import validate_grip
        # Retain the constraint even if it passed before smoothing. Avoid TRF
        # only when the new stored AND interpolated poses still hold the grip.
        cursors = np.arange(0., len(smoothed) if cyclic else len(smoothed) - 1 + .125, .25)
        samples = sample_rig(_sampling_payload(rig, smoothed), cursors, wrap=cyclic)
        if validate_grip(samples, names, equipment)['passed']:
            return smoothed
        smoothed = project_rigid_pair_grip_coordinates(
            smoothed, rig, names, equipment, pinned=pinned, max_nfev=20,
            deadline=deadline)
        if deadline is None or monotonic() < deadline:
            smoothed = project_playback_rigid_pair_grip(
                smoothed, rig, names, equipment, pinned=pinned, cyclic=cyclic,
                max_nfev=12, deadline=deadline)
        smoothed = _replant(smoothed, max_nfev=16)
        if (deadline is None or monotonic() < deadline) and _jump(smoothed) > _limit(smoothed):
            smoothed = temporal_coordinate_smooth(smoothed, cyclic=cyclic, sigma=0.4)
            smoothed = _replant(smoothed, max_nfev=12)
    return smoothed


def _playback_nested_failures(playback):
    """Map nested validate_rig_playback failures onto polish actions."""
    if not playback or playback.get('passed'):
        return set()
    fails = set()
    contact = float(playback.get('maximumContactErrorMeters') or 0.)
    if contact >= PLAYBACK_CONTACT_LIMIT_METERS:
        fails.add('contact')
    equipment = playback.get('equipment') or {}
    if equipment.get('required') and not equipment.get('passed', True):
        fails.add('equipment')
    if playback.get('velocityContinuous') is False:
        fails.add('velocity')
    if playback.get('physicalReasons'):
        fails.add('physical')
    return fails


def project_root_continuity_coordinates(coordinates, fps, scale, passes=40):
    """Clamp root second differences to the rootContinuity acceptance limit.

    Gaussian smoothing alone often stalls ~1.5× over the limit on source spikes.
    This iteratively damps excess acceleration at the offending samples.
    """
    coords = np.asarray(coordinates, dtype=float).copy()
    if len(coords) < 3 or scale <= 0 or fps <= 0:
        return coords
    limit = 0.05 * float(scale) * 0.95
    rate = (float(fps) / 30.) ** 2
    root = coords[:, :3]
    for _ in range(max(1, int(passes))):
        acceleration = np.diff(root, n=2, axis=0) * rate
        norms = np.linalg.norm(acceleration, axis=-1)
        bad = norms > limit
        if not bad.any():
            break
        for index in np.flatnonzero(bad):
            mid = int(index) + 1
            # Blend toward the neighbor mean — pure acceleration damping is too
            # weak on single-frame source spikes (~3× over the limit).
            neighbor_mean = 0.5 * (root[mid - 1] + root[mid + 1])
            blend = min(1., 1. - (limit / max(float(norms[index]), 1e-12)) * 0.5)
            root[mid] = (1. - blend) * root[mid] + blend * neighbor_mean
    coords[:, :3] = root
    return coords


def smooth_root_translation_coordinates(coordinates, fps, *, scale=None, max_passes=6):
    """Gaussian-smooth root translation DOFs to clear rootContinuity spikes."""
    coords = np.asarray(coordinates, dtype=float).copy()
    if len(coords) < 3:
        return coords
    # Source-derived roots can be ~3× over the continuity limit; grow sigma
    # until the acceptance screen passes or the pass budget is exhausted.
    sigma = max(1., float(fps) * .12)
    for step in range(max(1, int(max_passes))):
        coords[:, :3] = gaussian_filter1d(
            coords[:, :3], sigma * (1. + 0.5 * step), axis=0, mode='nearest')
        if scale is not None and root_motion_quality(coords[:, :3], fps, scale)['passed']:
            break
    if scale is not None and not root_motion_quality(coords[:, :3], fps, scale)['passed']:
        coords = project_root_continuity_coordinates(coords, fps, scale)
    return coords


def close_loop_seam_coordinates(coordinates, rig, pinned, *, scale, fps=30., passes=5):
    """Iterate boundary + velocity nudges until playback seam ratios are ≤1."""
    coords = np.asarray(coordinates, dtype=float).copy()
    if len(coords) < 3:
        return coords
    planted = bool(np.any(pinned))
    strengths = ([0.45, 0.65, 0.8] if planted
                 else list(np.linspace(0.4, 0.9, max(1, int(passes)))))
    best = coords
    rig.initial[:] = best
    best_score = seam_playback_over_limit_score(rig.decode(best), scale=scale, fps=fps)

    def consider(candidate):
        nonlocal best, best_score
        rig.initial[:] = candidate
        score = seam_playback_over_limit_score(rig.decode(candidate), scale=scale, fps=fps)
        if score < best_score:
            best, best_score = np.asarray(candidate, dtype=float).copy(), score

    for strength in strengths:
        boundary = seam_boundary_coordinate_nudge(best, rig, pinned, strength=float(strength))
        consider(boundary)
        consider(seam_velocity_neighbor_nudge(
            boundary, rig, pinned, strength=min(0.7, float(strength))))
        if best_score <= 1.:
            return best
    consider(seam_velocity_neighbor_nudge(best, rig, pinned, strength=0.65))
    return best


def project_loop_seam_coordinates(coordinates, rig, pinned, *, scale, fps, max_nfev=50,
                                  deadline=None, settling_weights=None, settling_limit=None):
    """Hard-project free boundary DOFs so wrap step+velocity fall under playback limits.

    Planted positions are constrained in world space, while local rotations stay
    available to articulate around those contacts. This small TRF solve targets
    the acceptance residuals directly.
    Anatomy is constrained alongside the seam. The caller still independently
    validates the complete interpolated motion, contacts and source fidelity.
    """
    from .loop_seam import (
        seam_errors, MAX_STEP_EXCESS_BODY_RATIO, MAX_VELOCITY_MISMATCH_BODY_RATIO)
    coords = np.asarray(coordinates, dtype=float).copy()
    count = len(coords)
    if count < 4:
        return coords
    planted = bool(np.any(pinned))
    boundary = (0, 1, count - 2, count - 1)
    deadline = monotonic() + 10. if deadline is None else deadline
    original_points = rig.decode(coords[list(boundary)])
    step_limit = MAX_STEP_EXCESS_BODY_RATIO * float(scale)
    vel_limit = MAX_VELOCITY_MISMATCH_BODY_RATIO * float(scale)
    _, initial_excess, initial_increments = seam_errors(original_points)
    root_needs_repair = (
        initial_excess[rig.root] >= step_limit
        or np.max(np.linalg.norm(initial_increments[:, rig.root], axis=-1)) * fps >= vel_limit)
    free_frames = boundary
    smooth_boundary = root_needs_repair and count >= 12
    if smooth_boundary:
        # Closing supported root drift in only two samples creates an inward
        # snap next to the repaired wrap. Give that correction a short approach
        # on either side, with fixed inner samples to constrain its derivatives.
        width = min(max(2, round(.15 * fps)), count // 2 - 2)
        free_frames = tuple(range(width)) + tuple(range(count - width, count))
        boundary = tuple(range(width + 2)) + tuple(range(count - width - 2, count))
        original_points = rig.decode(coords[list(boundary)])
    elif settling_weights is not None and count >= 6:
        boundary = (0, 1, 2, count - 3, count - 2, count - 1)
        original_points = rig.decode(coords[list(boundary)])
    settling_segments = []
    if settling_weights is not None and settling_limit is not None:
        baseline_relative = body_relative_points(rig.decode(coords), rig.names)
        weighted_speed = np.diff(baseline_relative, axis=0) * fps * settling_weights
        settling_outside = float(np.sum(weighted_speed ** 2))
        settling_denominator = max(float(np.sum(settling_weights)) * 3., 1.)
        middle = len(boundary) // 2
        for segment in (slice(None, middle), slice(middle, None)):
            indices = np.asarray(boundary[segment][:-1], dtype=int)
            settling_outside -= float(np.sum(weighted_speed[indices] ** 2))
            settling_segments.append((segment, settling_weights[indices]))
    parts = []
    for frame in free_frames:
        # Planted contacts constrain world-space joints, not the root itself.
        # Free translation with the contact residual; otherwise a supported
        # loop with root drift has no variables capable of closing its seam.
        if not planted or root_needs_repair:
            parts.append((frame, 0, 3))
        for joint in range(pinned.shape[1]):
            # A positional plant does not lock this local rotation. Free it
            # while holding the world point, as in the contact projector.
            slot = rig.slots.get(joint)
            if slot is not None:
                parts.append((frame, slot, slot + 3))
    if not parts:
        return coords
    x0 = np.concatenate([coords[frame, start:stop] for frame, start, stop in parts])
    original = x0.copy()

    def unpack(values):
        trial = coords.copy()
        offset = 0
        for frame, start, stop in parts:
            width = stop - start
            trial[frame, start:stop] = values[offset:offset + width]
            offset += width
        return trial

    best_values, best_cost = x0.copy(), float('inf')

    def residual_from_points(values, points, unconstrained_points):
        _, excess, increments = seam_errors(points)
        # Continuity applies to every joint, including joints that are planted
        # elsewhere in the repetition but moving at this boundary.
        step_err = np.maximum(excess - 0.95 * step_limit, 0.) / max(float(scale), 1e-6)
        vel_raw = np.linalg.norm(increments, axis=-1) * float(fps)
        vel_err = np.maximum(vel_raw - 0.95 * vel_limit, 0.) / max(float(scale), 1e-6)
        contact_err = np.zeros(0)
        if planted:
            deltas = []
            for local_frame, frame in enumerate(boundary):
                active = pinned[frame]
                if active.any():
                    deltas.append((points[local_frame, active] - original_points[local_frame, active]).ravel())
            if deltas:
                contact_err = np.concatenate(deltas) / max(float(scale), 1e-6)
        result = np.r_[
            # Step and velocity limits are both hard playback requirements.
            # A 50x step term was dwarfed by the fps-scaled velocity residual,
            # leaving a visible displacement hitch after velocity improved.
            2000. * step_err.ravel(),
            80. * vel_err.ravel(),
            20000. * contact_err,
            ANATOMY_FIT_WEIGHT * anatomical_structure_residuals(
                unconstrained_points, rig.names, pose_only=True,
                margin=ANATOMY_FIT_MARGIN, reference=original_points)[0].ravel(),
            0.02 * (values - original),
        ]
        if smooth_boundary:
            middle = len(boundary) // 2
            for segment in (slice(None, middle), slice(middle, None)):
                before = np.linalg.norm(np.diff(original_points[segment], n=2, axis=0), axis=-1)
                after = np.linalg.norm(np.diff(points[segment], n=2, axis=0), axis=-1)
                # Bound added acceleration, not changes in acceleration: removing
                # a source endpoint spike must not be penalized as a new defect.
                # The temporal gate's 3 mm per-axis floor is in meters, not
                # body-scale units. Convert it to a vector norm at this fps.
                limit = np.maximum(1.1 * before, np.sqrt(3.) * .003 * (30. / fps) ** 2)
                result = np.r_[result, (1000. * np.maximum(after - limit, 0.) / scale).ravel()]
        if settling_segments:
            squared_speed = max(0., settling_outside)
            for segment, weights in settling_segments:
                relative = body_relative_points(points[segment], rig.names)
                squared_speed += float(np.sum((np.diff(relative, axis=0) * fps * weights) ** 2))
            settling_speed = np.sqrt(squared_speed / settling_denominator)
            result = np.r_[result, 150. * max(
                settling_speed / max(settling_limit, 1e-12) - .95, 0.)]
        return result

    def residual(values):
        nonlocal best_values, best_cost
        if monotonic() >= deadline:
            raise TimeoutError('seam_projection_budget_exhausted')
        boundary_coordinates = unpack(values)[list(boundary)]
        points = rig.decode(boundary_coordinates)
        unconstrained_points = rig.decode(boundary_coordinates, project_socket=False)
        result = residual_from_points(values, points, unconstrained_points)
        cost = float(result @ result)
        if cost < best_cost:
            best_values, best_cost = values.copy(), cost
        return result

    def jacobian(values):
        if monotonic() >= deadline:
            raise TimeoutError('seam_projection_budget_exhausted')
        # Decode all finite-difference probes together. Per-coordinate FK calls
        # otherwise spend most of this bounded solve traversing the same rig.
        steps = np.sqrt(np.finfo(float).eps) * np.maximum(1., np.abs(values))
        probes = np.tile(values, (len(values) + 1, 1))
        probes[np.arange(len(values)), np.arange(len(values))] += steps
        trials = np.asarray([unpack(probe)[list(boundary)] for probe in probes])
        points = rig.decode(trials.reshape(-1, coords.shape[1])).reshape(
            len(probes), len(boundary), len(rig.names), 3)
        unconstrained_points = rig.decode(
            trials.reshape(-1, coords.shape[1]), project_socket=False).reshape(points.shape)
        residuals = np.asarray([residual_from_points(probe, pose, raw_pose)
                                for probe, pose, raw_pose in zip(probes, points, unconstrained_points)])
        return ((residuals[:-1] - residuals[-1]) / steps[:, None]).T

    try:
        solved = least_squares(
            residual, x0, jac=jacobian, method='trf', tr_solver='lsmr', max_nfev=int(max_nfev),
            ftol=1e-10, xtol=1e-10)
        best_values = solved.x
    except TimeoutError:
        pass
    projected = unpack(best_values)
    # Keep only if the playback score improved.
    before = seam_playback_over_limit_score(rig.decode(coords), scale=scale, fps=fps)
    after = seam_playback_over_limit_score(rig.decode(projected), scale=scale, fps=fps)
    return projected if after <= before else coords


def root_relative_acceleration(points, names):
    root = names.index('pelvis')
    relative = points-points[:, root:root+1]
    return np.sqrt(np.mean(np.diff(relative, n=2, axis=0)**2, axis=(0, 2)))


def relative_motion_quality(points, reference, names, fps, *, spike_reference=None):
    """Global translation noise must not hide newly introduced limb jitter."""
    before = root_relative_acceleration(reference, names)
    after = root_relative_acceleration(points, names)
    limits = np.maximum(before*1.2, .003*(30./fps)**2)
    spike_reference = reference if spike_reference is None else spike_reference
    payload = {'fps': fps, 'frames': [
        {'timeSec': i/fps, 'joints': dict(zip(names, current.tolist())),
         'sourceJoints': dict(zip(names, source.tolist()))}
        for i, (current, source) in enumerate(zip(points, spike_reference))]}
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


def project_track_to_reference_bone_lengths(track, index, bones, reference_lengths):
    """Re-impose reference bone lengths on a joint track, parents first.

    Smoothing and deviation attenuation bend bones: the fit target must stay
    anatomically possible for the fixed rig, so each child is re-projected
    onto its bone's reference length along its current direction from the
    (already projected) parent. ``bones`` must be in topological
    (parent-before-child) order. Returns the projected track copy.
    """
    projected = np.array(track, dtype=float, copy=True)
    for child, parent in bones:
        ci, pi = index[child], index[parent]
        target_length = reference_lengths.get(f'{child}<-{parent}')
        if target_length is None:
            continue
        delta = projected[:, ci] - projected[:, pi]
        norm = np.linalg.norm(delta, axis=-1, keepdims=True)
        usable = norm > 1e-9
        projected[:, ci] = np.where(
            usable,
            projected[:, pi] + delta / np.maximum(norm, 1e-12) * target_length,
            projected[:, ci],
        )
    return projected


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
    """Safety-cap wall clock only. Accept/stall/conflict should finish earlier."""
    if timeout_seconds is not None:
        return float(timeout_seconds)
    frames = len(payload.get('frames') or [])
    # One bounded bump so multi-cycle observed fits can finish without per-exercise overrides.
    return max(180., min(360., 2.5 * frames))


def _stage_deadline(fit_started, timeout_seconds, *, fraction, minimum_seconds, reserved_seconds=0.):
    """Bound a pre-solve stage. Polish is reserved from the solve phase, not here."""
    del reserved_seconds  # reserved only for soft-LS / Stage-B carve-out
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


def support_range_jacobian(values, rig, tracks):
    """Differentiate range floors at their extrema without recoloring the clip.

    Each angular range depends locally on two frames. At tied extrema, choosing
    one extremum supplies a subgradient of the unchanged min/max objective.
    """
    coordinates = np.asarray(values).reshape(-1, rig.width)
    points = rig.decode(coordinates)
    rows, columns, derivatives = [], [], []
    step = np.sqrt(np.finfo(float).eps)
    for row, (_, joints, source) in enumerate(tracks):
        track = angles(*(points[:, joint] for joint in joints))
        if np.ptp(track) >= .92 * float(np.ptp(source)):
            continue
        dependencies = np.flatnonzero(np.max(
            rig.dependencies[[joint * 3 + axis for joint in joints for axis in range(3)]],
            axis=0))
        for frame, sign in ((int(np.argmin(track)), 1.), (int(np.argmax(track)), -1.)):
            probes = np.repeat(coordinates[frame:frame + 1], len(dependencies), axis=0)
            probes[np.arange(len(dependencies)), dependencies] += step
            moved = rig.decode(probes)
            derivative = sign * 12000. * (
                angles(*(moved[:, joint] for joint in joints)) - track[frame]) / step
            rows.extend([row] * len(dependencies))
            columns.extend(frame * rig.width + dependencies)
            derivatives.extend(derivative)
    return csr_matrix((derivatives, (rows, columns)), shape=(len(tracks), len(values)))


def solve_trajectory(residual, initial, pattern, max_evaluations, *, tail_jacobian=None):
    # Use an absolute perturbation throughout the solve. Relative steps shrink
    # toward cancellation at tiny rotations, especially under stiff penalties.
    # Reuse the coloring; one-sided grouped differences avoid doubling all FK
    # and interpolated-frame evaluations as central differences would.
    tail_rows = 0 if tail_jacobian is None else tail_jacobian(initial).shape[0]
    local_pattern = pattern[:-tail_rows] if tail_rows else pattern
    groups = group_columns(local_pattern)
    def local_residual(values):
        errors = residual(values)
        return errors[:-tail_rows] if tail_rows else errors
    def jacobian(values):
        local = approx_derivative(local_residual, values, method='2-point',
            abs_step=np.sqrt(np.finfo(float).eps), sparsity=(local_pattern, groups))
        return vstack([local, tail_jacobian(values)], format='csr') if tail_rows else local
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
    """Prefer a source-confirmed cycle, retaining the full interval as fallback."""
    timeout_seconds = fit_time_budget(payload, timeout_seconds)
    if (not (payload.get('loop') or {}).get('enabled') or payload.get('fixedRig')
            or payload.get('loopCycleSelection') or timeout_seconds <= 0):
        return _fit_controlled_motion(payload, max_evaluations=max_evaluations,
                                      timeout_seconds=timeout_seconds)
    from .loop_cycles import rank_loop_cycles, slice_loop_cycle
    started = monotonic()
    choices = (payload['observedCycleProposals'] if 'observedCycleProposals' in payload
               else rank_loop_cycles(payload, max_candidates=3))
    shared_support = {}
    attempts = []
    open_cycle_fallback = None
    source_confirmed_first = bool(choices) and any(
        entry.get('passed') is True and entry.get('selection') == choices[0]
        for entry in payload.get('sourceCyclePreflight', []) if isinstance(entry, dict))
    if source_confirmed_first and timeout_seconds >= 110.:
        choice, choices = choices[0], choices[1:]
        candidate, report = _fit_controlled_motion(
            slice_loop_cycle(payload, choice), max_evaluations=max_evaluations,
            timeout_seconds=min(120., max(55., .3 * timeout_seconds)),
            shared_support=shared_support)
        attempts.append({'selection': choice, 'reason': report.get('reason'),
                         'checks': report.get('checks', {}),
                         'elapsedSeconds': report.get('elapsedSeconds', 0.),
                         'fitReport': deepcopy(report), 'sourceConfirmedFirst': True})
        if report.get('applied'):
            if (report.get('loopSeamOpen') or report.get('checks', {}).get('loopSeam') is False
                    or report.get('reason') == 'validated_controlled_motion_open_seam'):
                open_cycle_fallback = candidate, report
            else:
                report['cycleSelectionAttempts'] = attempts
                report['elapsedSeconds'] = monotonic() - started
                report['sourceCyclePreflight'] = payload.get('sourceCyclePreflight', [])
                return candidate, report
    remaining_before_retained = max(0., timeout_seconds - (monotonic() - started))
    wrap_reserve = 0.
    if choices:
        wrap_reserve = min(90., max(55., 0.3 * float(timeout_seconds)))
        wrap_reserve = min(wrap_reserve, 0.45 * remaining_before_retained)
    retained_timeout = max(0., remaining_before_retained - wrap_reserve)
    if retained_timeout < min(55., remaining_before_retained):
        retained_timeout = remaining_before_retained
        wrap_reserve = 0.
    retained_request = payload
    defer_retained_seam = bool(choices) and wrap_reserve > 0
    if defer_retained_seam:
        # Defer closure only when a cropped wrap has an actual reserved turn.
        # With no proposals, the retained interval is the only loop candidate;
        # disabling its seam would bypass closure entirely.
        retained_request = {
            **payload,
            'loop': {**(payload.get('loop') or {}), 'enabled': False},
        }
    retained, retained_report = _fit_controlled_motion(
        retained_request,
        max_evaluations=max_evaluations,
        timeout_seconds=retained_timeout,
        shared_support=shared_support,
    )
    if retained_report.get('applied') and defer_retained_seam:
        retained = deepcopy(retained)
        retained['loop'] = {
            **(retained.get('loop') or {}),
            'enabled': True,
            'transition': 'requires_cycle_repair',
            'restartFadeMillis': 0,
        }
        retained_report = {
            **retained_report,
            'loopSeamOpen': True,
            'reason': 'validated_controlled_motion_open_seam',
        }
        retained.pop('sequenceStabilization', None)
        retained_report['outputPoseDigest'] = pose_digest(retained)
        retained['controlledMotionFit'] = retained_report
    retained_report = {
        **retained_report,
        'retainedIntervalFit': True,
        'sourceCyclePreflight': payload.get('sourceCyclePreflight', []),
    }
    if retained_report.get('applied'):
        retained['controlledMotionFit'] = retained_report
        retained_report['outputPoseDigest'] = pose_digest(retained)
        retained['controlledMotionFit'] = retained_report
    attempts.append({
        'selection': {'kind': 'retained_interval'},
        'reason': retained_report.get('reason'),
        'checks': retained_report.get('checks', {}),
        'elapsedSeconds': retained_report.get('elapsedSeconds', 0.),
        'fitReport': deepcopy(retained_report),
    })
    if retained_report.get('applied') and (not choices or wrap_reserve <= 0):
        retained_report['cycleSelectionAttempts'] = attempts
        retained_report['elapsedSeconds'] = monotonic() - started
        return retained, retained_report
    # Do not reserve time for wraps that cannot receive even the minimum turn.
    # With 95 s left and several proposals, the old allocation gave the first
    # 55 s, then skipped every later proposal and stranded the remaining 40 s.
    available_wrap_seconds = max(0., timeout_seconds - (monotonic() - started))
    choices = choices[:max(1, int(available_wrap_seconds // 55.))]
    for index, choice in enumerate(choices):
        remaining = timeout_seconds - (monotonic() - started)
        if remaining <= 0:
            break
        later = len(choices) - index - 1
        reserve = later * min(90., max(55., 0.3 * float(timeout_seconds)))
        attempt_timeout = remaining - reserve if later else remaining
        attempt_timeout = max(min(remaining, 55.), attempt_timeout) if later else remaining
        if index > 0 and remaining < 55.:
            break
        if attempt_timeout <= 0:
            break
        candidate, report = _fit_controlled_motion(
            slice_loop_cycle(payload, choice),
            max_evaluations=max_evaluations,
            timeout_seconds=attempt_timeout,
            shared_support=shared_support,
        )
        attempts.append({'selection': choice, 'reason': report['reason'],
                         'checks': report.get('checks', {}),
                         'elapsedSeconds': report.get('elapsedSeconds', 0.),
                         'fitReport': deepcopy(report)})
        if report['applied']:
            if (report.get('loopSeamOpen') or report.get('checks', {}).get('loopSeam') is False
                    or report.get('reason') == 'validated_controlled_motion_open_seam'):
                # Body-valid is not a completed loop. Keep the best-ranked
                # open crop as fallback while trying the remaining budgeted
                # proposals, especially when the fitter requests another cycle.
                if open_cycle_fallback is None:
                    open_cycle_fallback = candidate, report
                continue
            report['cycleSelectionAttempts'] = attempts
            report['elapsedSeconds'] = monotonic() - started
            report['sourceCyclePreflight'] = payload.get('sourceCyclePreflight', [])
            return candidate, report
        if hard_trajectory_and_root_failure(report.get('checks')):
            break
        if seam_near_miss_for_cycle_skip(report):
            break
    if retained_report.get('applied'):
        retained_report['cycleSelectionAttempts'] = attempts
        retained_report['elapsedSeconds'] = monotonic() - started
        return retained, retained_report
    if open_cycle_fallback is not None:
        candidate, report = open_cycle_fallback
        report['cycleSelectionAttempts'] = attempts
        report['elapsedSeconds'] = monotonic() - started
        report['sourceCyclePreflight'] = payload.get('sourceCyclePreflight', [])
        return candidate, report
    reason = (
        'no_validated_loop_cycle'
        if choices and not retained_report.get('checks') else
        (retained_report.get('reason') or 'no_validated_loop_cycle')
    )
    return payload, {
        **retained_report,
        'applied': False,
        'reason': reason,
        'retainedIntervalFit': True,
        'cycleSelectionAttempts': attempts,
        'sourceCyclePreflight': payload.get('sourceCyclePreflight', []),
        'elapsedSeconds': monotonic() - started,
    }


def _fit_controlled_motion(payload, *, max_evaluations=None, timeout_seconds=None, shared_support=None):
    """Return only a validated fit; otherwise retain the input with a report."""
    allow_refinement = max_evaluations is None
    if max_evaluations is None:
        frames = len(payload.get('frames') or [])
        max_evaluations = max(25, min(40, (frames // 3) or 25))
    started = monotonic()
    timeout_seconds = fit_time_budget(payload, timeout_seconds)
    cyclic_preview = bool((payload.get('loop') or {}).get('enabled'))
    reserved_polish = polish_reserve_seconds(timeout_seconds, cyclic=cyclic_preview)
    report = {'applied': False, 'strategy': CONTROLLED_MOTION_STRATEGY,
              'timeBudgetSeconds': timeout_seconds, 'polishReserveSeconds': reserved_polish}
    optimization_deadline = started + timeout_seconds
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
    # Match the final renderer's immutable before-processing spike evidence.
    # Support projection may change the working reference; it must not turn a
    # newly introduced touchdown spike into the accepted temporal baseline.
    spike_reference = np.asarray([
        [(frame.get('sourceJoints') or frame['joints']).get(name, frame['joints'][name])
         for name in names]
        for frame in frames], dtype=float)
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
    # Continuity screen every derived root — transformed articulation roots
    # previously bypassed smoothing and failed rootContinuity after registration.
    if not root_motion_quality(root_reference, fps, body_scale(points, names))['passed']:
        scale_for_root = body_scale(points, names)
        sigma = max(1., fps * .12)
        for step in range(6):
            root_reference = gaussian_filter1d(
                root_reference, sigma * (1. + 0.5 * step), axis=0, mode='nearest')
            if root_motion_quality(root_reference, fps, scale_for_root)['passed']:
                break
        if not root_motion_quality(root_reference, fps, scale_for_root)['passed']:
            projected = project_root_continuity_coordinates(
                np.concatenate([root_reference, np.zeros((len(root_reference), 3))], axis=1),
                fps, scale_for_root)
            root_reference = projected[:, :3]
        placement_reference = (
            'smoothed_discontinuous_source_root_in_baked_frame'
            if placement_reference == 'original_source_root_in_baked_frame'
            else 'smoothed_discontinuous_input_root'
        )
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
    from .support_geometry import plant_only_body_support
    repaired_reference = None
    initialized_points = None
    anatomy_initialization = {'passed': False, 'reason': 'not_run'}
    # Bilateral plant-only clips do not need a 75s anatomy floor before hard
    # plant projectors. One-sided / incomplete plant masks (e.g. some floor
    # presses) still need the fuller anatomy budget or soft LS returns.
    body_support_preview = (
        (payload.get('sourceFootSupportEvidence') or {}).get('bodySupport') or {})
    stationary_preview = set(body_support_preview.get('stationaryJoints') or [])
    bilateral_plant_only = (
        plant_only_body_support(body_support_preview)
        and ({'left_ankle', 'left_foot'} & stationary_preview)
        and ({'right_ankle', 'right_foot'} & stationary_preview))
    try:
        anatomy_deadline = _stage_deadline(
            started, timeout_seconds,
            fraction=(0.12 if bilateral_plant_only else ANATOMY_REPAIR_TIME_FRACTION),
            minimum_seconds=(12. if bilateral_plant_only else ANATOMY_REPAIR_MIN_SECONDS),
        )
        initialized_points, anatomy_initialization = repair_rig_anatomy(
            rig, points, deadline=anatomy_deadline)
        report['anatomicalInitialization'] = anatomy_initialization
        if bilateral_plant_only:
            report['anatomicalInitializationPlantOnlyBudget'] = True
        source_violations, _ = repair_residuals(reference, names)
        if np.any(source_violations > 1e-6):
            # When the articulation reference is the working observation, one
            # projection already owns the outcome. A second identical solve only
            # burns the anatomy budget after an incomplete first pass.
            if np.allclose(points, reference, atol=1e-10, rtol=0.):
                source_anatomy = {**anatomy_initialization, 'reusedInitialization': True,
                                  'evaluations': 0, 'residualBatchCount': 0, 'residualPointCount': 0,
                                  'warmStartedFrameCount': 0}
                repaired_reference = initialized_points if anatomy_initialization.get('passed') else None
            else:
                repaired_reference = transport_equivalent_anatomical_repair(
                    points, initialized_points, reference, names)
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
            if repaired_reference is None or not source_anatomy['passed']:
                return payload, {**report, 'reason': 'anatomical_source_projection_incomplete'}
            reference = repaired_reference
    except TimeoutError:
        report['anatomicalInitializationTimedOut'] = True
        if initialized_points is None:
            initialized_points = rig.decode(rig.initial)
        anatomy_initialization = report.get('anatomicalInitialization') or {
            'passed': False, 'reason': 'time_budget'}
    report['anatomicalInitialization'] = anatomy_initialization
    from .rig_playback import rig_contact_targets
    from .contact_constraints import InfeasibleContactCorrection
    try:
        contact_targets, ankle_anchor_calibration = rig_contact_targets(
            points,names,pinned,rig.offsets,evidence=payload.get('sourceFootSupportEvidence'), floor=payload.get('renderFloorY'))
    except InfeasibleContactCorrection as error:
        return payload, {**report, 'reason': 'incompatible_stationary_contact_anchors',
                         'contactConstraintError': str(error)}
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
        try:
            contact_targets, ankle_anchor_calibration = rig_contact_targets(
                points, names, pinned, rig.offsets,
                stationary_positions={name: support_pose[names.index(name)]
                                      for name in body_support.get('stationaryJoints', [])},
                evidence=payload.get('sourceFootSupportEvidence'), floor=payload.get('renderFloorY'))
        except InfeasibleContactCorrection as error:
            return payload, {**report, 'reason': 'incompatible_stationary_contact_anchors',
                             'contactConstraintError': str(error)}
        from .support_geometry import initialize_supported_motion, plant_only_body_support
        # Reuse compatible static support calibration, never another interval's
        # trajectory. Resizing a full-clip rig to a crop stretches its movement
        # phases and then makes those altered poses the articulation reference.
        if plant_only_body_support(body_support):
            # Standing/planted-foot clips do not need torso support LS. Apply the
            # calibrated plant placement with a cheap root snap; leave articulation
            # and interpolated plants to the main trajectory fit.
            indices = [names.index(n) for n in body_support.get('stationaryJoints', [])]
            source_points = rig.decode(rig.initial)
            placement_shift = np.mean(support_pose[indices] - source_points[:, indices], axis=1)
            rig.initial[:, :3] += placement_shift
            if np.any(pinned):
                # Root snap first, then a short per-frame plant TRF. Always run the
                # plant pass — root snap alone often leaves one-sided plants above
                # gate and forces a long soft LS that plant_projection cannot use.
                rig.initial[:] = project_contact_root_translation(
                    rig.initial, rig, pinned, contact_targets, passes=3, smooth_fps=fps)
                plant_budget = min(14., max(5., 0.09 * float(timeout_seconds)))
                plant_deadline = min(
                    started + timeout_seconds - 45.,
                    monotonic() + plant_budget)
                if plant_deadline > monotonic():
                    rig.initial[:] = project_contact_plant_coordinates(
                        rig.initial, rig, pinned, contact_targets, max_nfev=18,
                        deadline=plant_deadline)
            initialized_points = rig.decode(rig.initial)
            report['supportInitializationSeconds'] = monotonic() - support_started
            report['supportInitializationStrategy'] = 'plant_projection'
            support_calibration['strategy'] = 'plant_projection'
        else:
            # Support projection is LS-heavy and scales with frames × evals. A flat
            # 90s ceiling aborted finishable 129-frame cold inits (~146s). Scale the
            # minimum with measured cost, capped only by outer budget minus solve room.
            projection_evals = SUPPORT_INIT_COLD_EVALUATIONS
            support_cost = (SUPPORT_INIT_SECONDS_PER_FRAME_EVAL
                            * float(len(points)) * float(projection_evals))
            solve_reserve = max(
                SUPPORT_INIT_SOLVE_RESERVE_MIN_SECONDS,
                SUPPORT_INIT_SOLVE_RESERVE_FRACTION * float(timeout_seconds),
            )
            support_min = max(SUPPORT_INIT_MIN_SECONDS, support_cost)
            support_min = min(
                support_min,
                max(SUPPORT_INIT_MIN_SECONDS, float(timeout_seconds) - solve_reserve),
            )
            support_deadline = _stage_deadline(
                started, timeout_seconds,
                fraction=SUPPORT_INIT_TIME_FRACTION,
                minimum_seconds=support_min,
            )
            try:
                initialized_points = initialize_supported_motion(
                    rig, points, body_support, support_pose, support_calibration,
                    support_deadline, fps=fps, alignment_reference=alignment_source,
                    pinned=pinned, contact_targets=contact_targets, equipment=equipment,
                    max_evaluations=projection_evals)
                report['supportInitializationSeconds'] = monotonic()-support_started
                report['supportInitializationStrategy'] = 'supported_motion_ls'
            except TimeoutError:
                report['supportInitializationSeconds'] = monotonic()-support_started
                report['supportInitializationTimedOut'] = True
                report['supportInitializationStrategy'] = 'supported_motion_ls'
                # Watchdog ends this stage's LS, not the fit. Keep the last
                # placement and let the main solve / plant projection judge it.
                initialized_points = rig.decode(rig.initial)
        if isinstance(shared_support, dict) and support_key is not None:
            shared_support['supportKey'] = support_key
            shared_support['supportPose'] = np.asarray(support_pose, dtype=float).copy()
            shared_support['supportCalibration'] = deepcopy(support_calibration)
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
        support_gates = (
            'supportReferenceGeometry', 'supportReferenceAlignment', 'supportReferenceAnatomy',
            'supportReferenceEquipment', 'supportReferenceContacts')
        # Geometry/alignment/equipment already describe a usable support frame.
        # Anatomy-only polish used to require contacts to pass first, so near-miss
        # plant error blocked repair of solvable ankle/torso violations (and the
        # reverse). Recover both with the dedicated projectors before rejecting.
        support_frame_ok = all(
            report[key]['passed']
            for key in ('supportReferenceGeometry', 'supportReferenceAlignment',
                        'supportReferenceEquipment'))
        needs_anatomy = not report['supportReferenceAnatomy']['passed']
        needs_contacts = not report['supportReferenceContacts']['passed']
        if (support_frame_ok and (needs_anatomy or needs_contacts)
                and monotonic() < started + timeout_seconds):
            anatomy_budget = max(6., 0.15 * float(timeout_seconds))
            # Plant-only clips already paid for keyframe plants; anatomy polish
            # must not re-burn a soft-LS-sized window before the deferred play pass.
            if report.get('supportInitializationStrategy') == 'plant_projection':
                anatomy_budget = min(8., anatomy_budget)
            anatomy_deadline = min(
                started + timeout_seconds,
                monotonic() + anatomy_budget,
            )
            try:
                if needs_anatomy:
                    initialized_points, support_anatomy_polish = repair_rig_anatomy(
                        rig, initialized_points, deadline=anatomy_deadline)
                    report['supportReferenceAnatomyPolish'] = support_anatomy_polish
                if needs_contacts or needs_anatomy:
                    # Anatomy repair can leave planted joints a few millimeters
                    # off; incomplete projection often stops just above 0.5 mm.
                    # Plant-only already deferred plant-chain TRF to the main fit —
                    # another full-clip plant here reintroduces the same stall.
                    if report.get('supportInitializationStrategy') == 'plant_projection':
                        planted = project_contact_root_translation(
                            rig.initial, rig, pinned, contact_targets,
                            passes=3, smooth_fps=fps)
                    else:
                        planted = project_contact_plant_coordinates(
                            rig.initial, rig, pinned, contact_targets, max_nfev=40)
                    rig.initial[:] = planted
                    initialized_points = rig.decode(planted)
                    report['supportReferenceContactPolish'] = {
                        'applied': True,
                        'maximumErrorMetersBefore': reference_contact_error,
                    }
                reference_errors, reference_labels = repair_residuals(initialized_points, names)
                failed_reference_features = np.max(reference_errors, axis=0) > 1e-6
                report['supportReferenceAnatomy'] = {
                    'passed': not bool(np.any(failed_reference_features)),
                    'violations': [reference_labels[j] for j in np.flatnonzero(failed_reference_features)],
                    'residualByViolation': {
                        reference_labels[j]: float(np.max(reference_errors[:, j]))
                        for j in np.flatnonzero(failed_reference_features)},
                }
                report['supportReferenceGeometry'] = validate_support_geometry(
                    payload, initialized_points, names)
                report['supportReferenceAlignment'] = validate_alignment(
                    initialized_points, alignment_source, names, body_support)
                report['supportReferenceEquipment'] = validate_grip(initialized_points, names, equipment)
                reference_contact_error = float(np.max(
                    np.linalg.norm((initialized_points - contact_targets)[pinned], axis=-1), initial=0.))
                report['supportReferenceContacts'] = {
                    'passed': reference_contact_error < .0005,
                    'maximumErrorMeters': reference_contact_error,
                }
                if report.get('supportReferenceContactPolish'):
                    report['supportReferenceContactPolish']['maximumErrorMetersAfter'] = (
                        reference_contact_error)
            except TimeoutError:
                report['supportReferenceAnatomyPolish'] = {'passed': False, 'reason': 'time_budget'}
        if not all(report[key]['passed'] for key in support_gates):
            if (report.get('supportInitializationTimedOut')
                    or report.get('supportInitializationStrategy') == 'plant_projection'):
                # Light plant init / timed-out torso LS leave near-miss contacts for
                # the main trajectory fit and playback plant projection to finish.
                report['supportReferenceContinuedAfterTimeout'] = True
            else:
                return payload, {**report, 'reason': 'support_reference_projection_incomplete'}
        # Supported reference must itself satisfy rootContinuity. Otherwise the
        # main solve prior and Stage-C repairs fight planted contacts/anatomy.
        support_scale = body_scale(initialized_points, names)
        if not root_motion_quality(initialized_points[:, root_index], fps, support_scale)['passed']:
            continuous = project_root_continuity_coordinates(
                rig.initial.copy(), fps, support_scale)
            if np.any(pinned):
                root_plant_deadline = monotonic() + min(
                    8., max(2., 0.05 * float(timeout_seconds)))
                continuous = project_contact_plant_coordinates(
                    continuous, rig, pinned, contact_targets, max_nfev=20,
                    freeze_root=True, deadline=root_plant_deadline)
            candidate_points = rig.decode(continuous)
            contact_err = float(np.max(
                np.linalg.norm((candidate_points - contact_targets)[pinned], axis=-1), initial=0.))
            anatomy_errors, _ = repair_residuals(candidate_points, names)
            anatomy_ok = not bool(np.any(anatomy_errors > 1e-6))
            support_ok = validate_support_geometry(payload, candidate_points, names)['passed']
            root_ok = root_motion_quality(
                candidate_points[:, root_index], fps, support_scale)['passed']
            if contact_err < 0.0005 and anatomy_ok and support_ok and root_ok:
                rig.initial[:] = continuous
                initialized_points = candidate_points
                report['supportReferenceRootContinuity'] = {'applied': True, 'passed': True}
                report['supportReferenceGeometry'] = validate_support_geometry(
                    payload, initialized_points, names)
                report['supportReferenceContacts'] = {
                    'passed': True, 'maximumErrorMeters': contact_err}
            else:
                report['supportReferenceRootContinuity'] = {
                    'applied': False, 'passed': False,
                    'contactErrorMeters': contact_err,
                    'anatomyPassed': anatomy_ok, 'supportPassed': support_ok,
                    'rootPassed': root_ok,
                }
        # Explicit support owns these corrections. Keep the original temporal
        # evidence unchanged, but compare articulation to the feasible supported
        # pose rather than requiring reproduction of the unsupported geometry.
        reference = initialized_points.copy()
        # Estimated rigid-pair spacing must follow the supported geometry. A
        # pre-support reconstruction distance becomes an unreachable target once
        # support rewrites hand placement, and the main solve then fails equipment.
        if equipment.get('handRelationship') == 'rigid_pair' and equipment.get('distanceSource') != 'explicit':
            equipment = calibrated_grip_constraint(
                {**payload, 'equipmentConstraints': {
                    **(payload.get('equipmentConstraints') or {}),
                    'handRelationship': 'rigid_pair', 'distanceMeters': None}},
                reference, names)
            report['supportReferenceEquipment'] = validate_grip(reference, names, equipment)
        # Reconstruction often leaves tens of centimeters of rigid-pair variance.
        # Hard-project arm DOFs onto the calibrated spacing before the main solve.
        if (equipment.get('handRelationship') == 'rigid_pair' and equipment.get('available')
                and not report['supportReferenceEquipment']['passed']
                and monotonic() < started + timeout_seconds):
            grip_budget = min(12., max(2., 0.08 * float(timeout_seconds)))
            grip_deadline = min(started + timeout_seconds - 30., monotonic() + grip_budget)
            gripped = project_rigid_pair_grip_coordinates(
                rig.initial, rig, names, equipment, pinned=pinned, max_nfev=25,
                deadline=grip_deadline)
            if np.any(pinned):
                # Distal arm projection should not move plants; re-snap anyway in
                # case collar/shoulder coupling nudged a foot sample.
                gripped = project_contact_root_translation(
                    gripped, rig, pinned, contact_targets, passes=2, smooth_fps=fps)
                plant_deadline = min(
                    started + timeout_seconds - 30.,
                    monotonic() + min(6., max(2., 0.05 * float(timeout_seconds))))
                if plant_deadline > monotonic():
                    gripped = project_contact_plant_coordinates(
                        gripped, rig, pinned, contact_targets, max_nfev=16,
                        deadline=plant_deadline)
            rig.initial[:] = gripped
            reference = rig.decode(gripped)
            initialized_points = reference
            report['supportReferenceEquipment'] = validate_grip(reference, names, equipment)
            report['supportReferenceGripProjection'] = {
                'applied': True,
                'passed': bool(report['supportReferenceEquipment']['passed']),
                'maximumSpacingErrorMeters': report['supportReferenceEquipment'].get(
                    'maximumSpacingErrorMeters'),
            }
            if np.any(pinned):
                reference_contact_error = float(np.max(
                    np.linalg.norm((reference - contact_targets)[pinned], axis=-1), initial=0.))
                report['supportReferenceContacts'] = {
                    'passed': reference_contact_error < .0005,
                    'maximumErrorMeters': reference_contact_error,
                }
        # One playback-plant pass after keyframe plants (+ optional grip). Soft LS
        # cannot close mid-sample bows; do not pay for this twice around grip.
        if (report.get('supportInitializationStrategy') == 'plant_projection'
                and np.any(pinned)
                and monotonic() < started + timeout_seconds):
            play_budget = min(14., max(5., 0.08 * float(timeout_seconds)))
            play_deadline = min(
                started + timeout_seconds - 25.,
                monotonic() + play_budget)
            if play_deadline > monotonic() and _playback_failing_intervals(
                    rig.initial, rig, pinned, contact_targets, cyclic=cyclic_preview,
                    floor=payload.get('renderFloorY')):
                rig.initial[:] = project_interval_playback_plants(
                    rig.initial, rig, pinned, contact_targets,
                    cyclic=cyclic_preview, floor=payload.get('renderFloorY'),
                    max_nfev=16, deadline=play_deadline, spike_reference=spike_reference)
                reference = rig.decode(rig.initial)
                initialized_points = reference
                reference_contact_error = float(np.max(
                    np.linalg.norm((reference - contact_targets)[pinned], axis=-1), initial=0.))
                report['supportReferenceContacts'] = {
                    'passed': reference_contact_error < .0005,
                    'maximumErrorMeters': reference_contact_error,
                }
                if equipment.get('handRelationship') == 'rigid_pair':
                    report['supportReferenceEquipment'] = validate_grip(
                        reference, names, equipment)
            report['supportPlaybackPlantsApplied'] = True
        report['supportReferenceCorrection'] = {'source': body_support.get('source'),
            'maximumCorrectionMeters': float(np.max(np.linalg.norm(reference-points, axis=-1)))}
    # Under support, jointRange accepts articulation excursion (not world-space
    # spans that also encode placement). Fit the same metric so soft targets
    # cannot quietly shrink free-chain ROM below the acceptance floor.
    support_articulation_tracks = ()
    if body_support.get('required'):
        from .support_geometry import moving_support_articulations
        support_articulation_tracks = tuple(moving_support_articulations(
            support_range_reference, names, body_support, support_corrected_points=reference))
    # Initializers evaluate guarded geometry and can leave rotations far beyond
    # the socket boundary behind that guard. Commit the identical decoded pose
    # to coordinates before raw-geometry fitting, interpolation, and the rotation
    # prior are initialized; otherwise the main solve must undo hidden damage.
    from .physical_validation import SOCKET_ALIGNMENT_MAX_LATERAL_RATIO
    rig.project_neck_attachment(
        maximum_lateral_ratio=SOCKET_ALIGNMENT_MAX_LATERAL_RATIO - ANATOMY_FIT_MARGIN)
    target, _, evidence = controlled_target(rig.decode(rig.initial), names, fps)
    settling_basis = settling_hold_basis(temporal_reference, reference, body_support)
    _, holds, _ = controlled_target(settling_basis, names, fps)
    # Same authority as settling: when support rewrites geometry, its temporal
    # content — not the unsupported source — defines the reachable jerk floor.
    jerk_basis = settling_basis if body_support.get('required') else temporal_reference
    jerk_before = float(np.sqrt(np.mean(np.diff(jerk_basis, n=3, axis=0)**2)))
    jerk_limit = jerk_before * 1.05 + 1e-7
    hold_weights = np.minimum(holds[1:], holds[:-1])[:, :, None]
    settling_before = weighted_settling_speed(settling_basis, names, fps, hold_weights)
    settling_limit = max(settling_before * 1.1, .003)
    report['temporalReference'] = 'source_articulation_before_repairs'
    report['settlingReference'] = (
        'supported_reference' if body_support.get('required') else 'source_articulation_before_repairs')
    report['settlingLimit'] = settling_limit
    target, _, placement_report = contact_consistent_target(target, pinned, contact_targets)
    evidence['placement'] = placement_report
    evidence['placementRegistration'] = registration
    # Distinguish the three ways a fit can become unsatisfiable: a bent input
    # skeleton, a target that is anatomically impossible for the rig, or
    # anchors that conflict with the pose. Without these numbers a failed fit
    # cannot be root-caused from its report alone.
    initial_points = rig.decode(rig.initial)
    from .smpl_joint_names import SMPL_JOINT_NAMES as _SMPL_NAMES, SMPL_JOINT_PARENTS as _SMPL_PARENTS
    _index = {name: position for position, name in enumerate(names)}
    _bones = [
        (child, _SMPL_NAMES[parent])
        for child, parent in zip(_SMPL_NAMES, _SMPL_PARENTS)
        if 0 <= parent < len(_SMPL_NAMES) and child in names and _SMPL_NAMES[parent] in names
    ]

    def _bone_medians(track):
        return {
            f'{child}<-{parent}': float(
                np.median(np.linalg.norm(
                    track[:, _index[child]] - track[:, _index[parent]], axis=-1)))
            for child, parent in _bones
        }

    initial_bones = _bone_medians(initial_points)
    target_bones = _bone_medians(target)
    input_bone_variation = max(
        (float(np.ptp(np.linalg.norm(
            initial_points[:, names.index(child)] - initial_points[:, names.index(parent)],
            axis=-1)))
         for child, parent in _bones),
        default=0.0)
    target_mismatch = max(
        (abs(target_bones[bone] - initial_bones[bone])
         for bone in target_bones if bone in initial_bones),
        default=0.0)
    worst_bone = (
        max(target_bones, key=lambda bone: abs(target_bones[bone] - initial_bones.get(bone, 0.0)))
        if target_bones else None)
    evidence['fitInputEvidence'] = {
        'maximumInputBoneVariationMeters': round(float(input_bone_variation), 6),
        'maximumTargetBoneMismatchMeters': round(float(target_mismatch), 6),
        'worstTargetBone': worst_bone,
    }
    if target_mismatch > FIT_INPUT_MAX_TARGET_BONE_MISMATCH_METERS:
        # Feasibility by construction: smoothing and deviation attenuation
        # bend the target's bones, and the rig cannot honor bone lengths it
        # does not have — an infeasible target makes the whole solve
        # unreachable no matter how long it runs. Re-impose the rig's median
        # bone lengths on the target (parents first) and re-seat the contact
        # anchors, so the solve starts from a provably feasible target.
        reference_lengths = {
            bone: length for bone, length in initial_bones.items()
        }
        target = project_track_to_reference_bone_lengths(
            target, _index, _bones, reference_lengths
        )
        target, _, placement_report = contact_consistent_target(
            target, pinned, contact_targets
        )
        evidence['placement'] = placement_report
        projected_bones = _bone_medians(target)
        projected_mismatch = max(
            (
                abs(projected_bones[bone] - initial_bones[bone])
                for bone in projected_bones
                if bone in initial_bones
            ),
            default=0.0,
        )
        evidence['fitInputEvidence'].update(
            projectedToRigBones=True,
            mismatchAfterProjectionMeters=round(float(projected_mismatch), 6),
        )
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
    acceleration_fit_scale, rotation_fit_scale = temporal_fit_scales(
        settling_basis if body_support.get('required') else temporal_reference, names, fps)
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
    from .heel_contacts import heel_contact_tracks
    heel_contacts = heel_contact_tracks(points, names, payload.get('sourceFootSupportEvidence'),
                                       floor=payload.get('renderFloorY'), fps=fps)
    heel_pattern = np.vstack([
        np.tile(joint_dependencies(rig, (names[ankle], names[toe])), (3, 1))
        for ankle, toe in heel_contacts.pairs
    ]) if heel_contacts.pairs else np.empty((0, rig.width))
    frame_pattern = np.vstack([frame_pattern, heel_pattern])
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
    from .rig_playback import sample_rig_coordinates
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
    subframe_pattern = np.vstack([subframe_pattern, heel_pattern])
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
    if support_articulation_tracks:
        articulation_rows = []
        for _, cols, _ in support_articulation_tracks:
            dep = np.max(rig.dependencies[np.ravel([[j * 3 + k for k in range(3)] for j in cols])],
                         axis=0)
            articulation_rows.append(np.tile(dep, count))
        pattern = vstack([pattern, csr_matrix(np.asarray(articulation_rows))], format='csr')
    initial_rotations = Rotation.from_rotvec(rig.initial[:,3:].reshape(-1,3))
    floor = payload.get('renderFloorY')
    source_head = body_local_head_direction(reference,names)
    from .fit_runtime import current_fit_session, fit_input_key, fit_should_yield_for_priority
    fit_session = current_fit_session()
    trajectory_key = fit_input_key(payload) if fit_session is not None else None
    best_coordinates = None
    best_cost = float('inf')
    best_feasible_coordinates = None
    best_feasible_cost = float('inf')
    seam_polish_weight = 1.
    contact_polish_weight = 1.
    equipment_polish_weight = 1.
    grip_fit_weight = GRIP_FIT_WEIGHT
    if (equipment.get('handRelationship') == 'rigid_pair' and equipment.get('available')
            and not validate_grip(rig.decode(rig.initial), names, equipment)['passed']):
        # Source/reconstruction often has large rigid-pair variance; give grip
        # room to compete with pose/contact before Stage-A polish.
        grip_fit_weight = GRIP_FIT_WEIGHT_WHEN_REFERENCE_FAILS
        report['gripFitWeight'] = float(grip_fit_weight)
    def residual(values):
        nonlocal best_coordinates, best_cost, best_feasible_coordinates, best_feasible_cost
        if fit_should_yield_for_priority() or monotonic() > optimization_deadline:
            raise TimeoutError
        coordinates = values.reshape(count,rig.width)
        candidate = rig.decode(coordinates)
        # A clipped socket hides its violation from the optimizer and creates
        # velocity corners where the interpolated path enters the clamp. Score
        # the underlying geometry so fitting can remove the need for clipping.
        unconstrained_candidate = rig.decode(coordinates, project_socket=False)
        rotation_prior = .01*(initial_rotations.inv()*Rotation.from_rotvec(coordinates[:,3:].reshape(-1,3))).as_rotvec().reshape(count,-1)
        current_angles = np.stack([angles(*(candidate[:,i] for i in cols)) for _,cols,_ in specs],axis=1)
        artic_weight = (SUPPORT_ARTICULATION_FIT_WEIGHT if body_support.get('required') else 500.)
        articulation = artic_weight*(np.minimum(current_angles-low,0.)+np.maximum(current_angles-high,0.))
        floor_error = np.zeros((count,joints)) if floor is None else FLOOR_FIT_WEIGHT*np.minimum(candidate[:,:,1]-float(floor),0.)
        current_head = body_local_head_direction(candidate,names)
        head_angle = np.arccos(np.clip(np.sum(source_head*current_head,axis=1),-1.,1.))
        head_weight = (SUPPORT_HEAD_ARTICULATION_FIT_WEIGHT if body_support.get('required')
                       else HEAD_ARTICULATION_FIT_WEIGHT)
        head_penalty = head_weight*np.maximum(head_angle-np.deg2rad(14.),0.)[:,None]
        excursion_projection = np.sum((candidate-candidate[:,rig.root:rig.root+1]-excursion_center)*excursion_direction,axis=-1)
        excursion_penalty = 20.*np.minimum(excursion_projection-excursion_minimum,0.)*excursion_active/scale
        current_parent, current_bend, current_sine = hinge_coordinates(candidate,names)
        branch_dot = transported_hinge_dots(source_parent,source_bend,current_parent,current_bend)
        branch_penalty = 20.*np.minimum(branch_dot-.2,0.)*branch_supported*np.clip(current_sine/np.sin(np.deg2rad(15.)),0.,1.)
        contact_weight = CONTACT_FIT_WEIGHT * contact_polish_weight
        grip_weight = grip_fit_weight * equipment_polish_weight
        pose_error = 2. * (candidate - target) / scale
        if body_support.get('required'):
            # Pull toward a continuous supported root track. The raw support
            # reference can itself carry source root spikes; smoothing the
            # prior target prevents soft LS from re-locking those jumps.
            root_track = reference[:, rig.root]
            if not root_motion_quality(root_track, fps, scale)['passed']:
                root_track = gaussian_filter1d(
                    root_track, max(.5, fps * .08), axis=0, mode='nearest')
            pose_error[:, rig.root] = 8. * (candidate[:, rig.root] - root_track) / scale
        per_frame = np.concatenate([pose_error.reshape(count,-1),
                                    (contact_weight*(candidate-contact_targets)*pinned[:,:,None]).reshape(count,-1),
                                    articulation, floor_error, head_penalty, rotation_prior,
                                    100.*np.minimum(collision_clearances(candidate,names,scale)[0]/scale-COLLISION_FIT_MARGIN_RATIO,0.),
                                    excursion_penalty,branch_penalty,
                                    ANATOMY_FIT_WEIGHT*anatomical_structure_residuals(
                                        unconstrained_candidate,names,pose_only=True,margin=ANATOMY_FIT_MARGIN,
                                        reference=reference)[0],
                                    grip_weight*grip_residual(candidate,names,equipment)/scale,
                                    2000.*geometry_errors(candidate,names,body_support)/scale,
                                    10.*alignment_constraint_errors(candidate,source_alignment,names,body_support)/scale,
                                    (contact_weight * heel_contacts.residual(candidate)).reshape(count, -1)],axis=1)
        # Penalize output acceleration and jerk, rather than preserving the
        # input noise through a correction-relative temporal objective.
        root_relative = (candidate-candidate[:,rig.root:rig.root+1])/scale
        acceleration = (d2@(candidate-candidate[:,rig.root:rig.root+1]).reshape(count,-1)).reshape(-1,joints,3)
        acceleration = (10.*acceleration/acceleration_fit_scale[None,:,None]).reshape(-1,joints*3)
        jerk = (d3@root_relative.reshape(count,-1))*(fps*.10)**3
        relative = body_relative_points(candidate,names)
        # Keep quiet holds near the settling baseline. Underweighted settling
        # loses to stiff support/contact terms and injects hold motion that
        # later fails acceptance after burning the full candidate budget.
        settling_weight = 150. if body_support.get('required') else 50.
        settling = (settling_weight*np.diff(relative,axis=0)*hold_weights*fps
                    / (settling_limit*np.sqrt(max(np.sum(hold_weights)*3, 1.))))
        # Root-relative coordinates remove translation noise without coupling
        # every limb's temporal derivatives to the moving neck basis. Body-axis
        # acceleration below constrains torso rotation independently.
        root_acceleration = (d2@(candidate[:,rig.root]/scale))*(fps*.10)**2*np.sqrt(joints)
        root_jerk = (d3@(candidate[:,rig.root]/scale))*(fps*.07)**3*np.sqrt(joints)
        if body_support.get('required'):
            root_acceleration = 4. * root_acceleration
            root_jerk = 4. * root_jerk
        orientation_acceleration = 10.*(d2@body_orientation_axes(candidate,names).reshape(count,-1))/rotation_fit_scale
        subframe_coordinates = sample_rig_coordinates(
            {**playback_rig,'coordinates':coordinates},subframe_cursors,wrap=cyclic)
        subframe = rig.decode(subframe_coordinates)
        unconstrained_subframe = rig.decode(subframe_coordinates, project_socket=False)
        subframe_contacts = contact_weight*(subframe-subframe_targets)*subframe_pinned[:,:,None]
        subframe_floor = np.zeros((subframe_count,joints)) if floor is None else FLOOR_FIT_WEIGHT*np.minimum(subframe[:,:,1]-float(floor),0.)
        subframe_rows = np.concatenate([subframe_contacts.reshape(subframe_count,-1),subframe_floor,
                                        100.*np.minimum(collision_clearances(subframe,names,scale)[0]/scale-COLLISION_FIT_MARGIN_RATIO,0.),
                                        ANATOMY_FIT_WEIGHT*anatomical_structure_residuals(
                                            unconstrained_subframe,names,pose_only=True,margin=ANATOMY_FIT_MARGIN,
                                            reference=(reference[subframe_first]*(1.-subframe_alpha)
                                                       +reference[subframe_last]*subframe_alpha))[0],
                                        grip_weight*grip_residual(subframe,names,equipment)/scale,
                                        2000.*geometry_errors(subframe,names,body_support)/scale,
                                        10.*alignment_constraint_errors(subframe,subframe_alignment,names,body_support)/scale,
                                        (contact_weight * heel_contacts.residual(
                                            subframe, subframe_first, subframe_last)).reshape(subframe_count, -1)],axis=1)
        # The final sample precedes the first by one frame. Equal endpoint
        # positions would impose a stop; match the incoming/outgoing increments.
        closure, seam_excess, seam_velocity_excess = np.empty(0), np.empty(0), np.empty(0)
        if cyclic:
            from .loop_seam import seam_errors, MAX_STEP_EXCESS_BODY_RATIO, MAX_VELOCITY_MISMATCH_BODY_RATIO
            _, excess, increments = seam_errors(candidate)
            # Optimize the actual playback step bound as well as velocity
            # matching. A small least-squares velocity error can still leave
            # a visibly oversized restart step, especially in slow movement.
            limit = MAX_STEP_EXCESS_BODY_RATIO * scale
            # Use body-normalized meters, as for contact/grip residuals.
            # Dividing by the millimeter acceptance limit makes this term
            # dominate anatomy and contact fitting by orders of magnitude.
            # Stage-B polish raises seam_polish_weight so soft LS prioritizes
            # restart continuity once body/contact terms are already good.
            seam_excess = (2000. * seam_polish_weight) * np.maximum(
                excess - .8 * limit, 0.) / scale
            velocity_step_limit = MAX_VELOCITY_MISMATCH_BODY_RATIO * scale / fps
            # Stage-B near-misses are often velocity-limited after step is close;
            # weight wrap increments above step excess so LS closes the hitch.
            velocity_weight = 3500. * seam_polish_weight if seam_polish_weight > 1. else 2000. * seam_polish_weight
            seam_velocity_excess = velocity_weight * np.maximum(
                np.linalg.norm(increments, axis=-1) - .8 * velocity_step_limit, 0.) / scale
            closure = (150. * seam_polish_weight) * increments / scale
        errors = np.r_[per_frame.ravel(),acceleration.ravel(),jerk.ravel(),settling.ravel(),
                     root_acceleration.ravel(),root_jerk.ravel(),orientation_acceleration.ravel(),
                     subframe_rows.ravel(),closure.ravel(),seam_excess.ravel(),seam_velocity_excess.ravel()]
        # Normalize by the same RMS bound used at acceptance, independently of
        # clip size or the amount of noise introduced by a preview variant.
        world_jerk = world_d3 @ candidate.reshape(count, -1)
        errors = np.r_[errors, (10. * world_jerk / (
            TEMPORAL_FIT_TARGET_RATIO * jerk_limit * np.sqrt(world_jerk.size))).ravel()]
        if support_articulation_tracks:
            # Soft floor slightly above the 0.85 acceptance ratio so the solver
            # has margin instead of landing on the hard fail boundary. Weight
            # must compete with contact/seam terms; 5k left retained fits at
            # ~0.80 hip/shoulder ratios that still failed jointRange.
            support_range_errors = np.asarray([
                12000. * max(0., .92 * float(np.ptp(track))
                          - float(np.ptp(angles(*(candidate[:, j] for j in cols)))))
                for _, cols, track in support_articulation_tracks
            ], dtype=float)
            errors = np.r_[errors, support_range_errors]
        cost = float(errors@errors)
        if np.isfinite(cost) and cost < best_cost:
            best_cost, best_coordinates = cost, values.copy()
        # Longer solves can improve soft cost while leaving the contact-feasible
        # region. Keep the best iterate that still clears planted contacts so
        # acceptance is not hostage to an over-fit soft minimum.
        if np.isfinite(cost) and (np.any(pinned) or np.any(heel_contacts.active)):
            contact_err = float(np.max(
                np.linalg.norm((candidate - contact_targets)[pinned], axis=-1), initial=0.))
            play_err = float(np.max(
                np.linalg.norm((subframe - subframe_targets)[subframe_pinned], axis=-1), initial=0.))
            contact_err = max(contact_err, float(np.max(
                np.linalg.norm(heel_contacts.residual(candidate), axis=-1), initial=0.)))
            play_err = max(play_err, float(np.max(np.linalg.norm(
                heel_contacts.residual(subframe, subframe_first, subframe_last), axis=-1), initial=0.)))
            floor_pen = 0. if floor is None else max(
                0., float(floor) - float(min(candidate[:,:,1].min(), subframe[:,:,1].min())))
            if (contact_err < PLAYBACK_CONTACT_LIMIT_METERS
                    and play_err < PLAYBACK_CONTACT_LIMIT_METERS
                    and floor_pen <= PLAYBACK_FLOOR_LIMIT_METERS
                    and cost < best_feasible_cost):
                best_feasible_cost, best_feasible_coordinates = cost, values.copy()
        return errors
    trajectory_solver = solve_trajectory
    if support_articulation_tracks:
        from functools import partial
        trajectory_solver = partial(
            solve_trajectory,
            tail_jacobian=lambda values: support_range_jacobian(
                values, rig, support_articulation_tracks))
    try:
        if fit_should_yield_for_priority() or monotonic()-started > timeout_seconds:
            raise TimeoutError
        # Soft LS must not consume the reserved polish window after anatomy/support.
        # Keep the full reserve (do not shrink with leftover); hard-stop the solve
        # at that fence so Stage-C always gets a real window.
        outer_remaining = max(0., started + timeout_seconds - monotonic())
        polish_left = min(float(reserved_polish), max(0., outer_remaining - 20.))
        if cyclic and outer_remaining >= 8.:
            # Cyclic near-miss seam closure needs a real Stage-B/C window after solve.
            polish_left = max(polish_left, min(float(reserved_polish), min(20., 0.25 * outer_remaining)))
        polish_left = max(polish_left, min(12., max(0., outer_remaining - 30.))) if outer_remaining >= 40. else polish_left
        nominal_solve = max(45., min(150., 1.25 * float(count)))
        solve_phase_budget = min(nominal_solve, max(0., outer_remaining - polish_left))
        optimization_deadline = min(
            started + timeout_seconds - polish_left,
            monotonic() + solve_phase_budget,
        )
        report['solvePhaseBudgetSeconds'] = float(solve_phase_budget)
        report['polishReserveRemainingSeconds'] = float(polish_left)
        initial_points = rig.decode(rig.initial)
        # Rig feasibility belongs to the observed pose. Comparing against the
        # smoothed target needlessly refits already clean, small articulations
        # and can introduce solver noise larger than their original jerk.
        already_rigid = np.max(abs(initial_points-points)) < 1e-7
        already_smooth = np.max(np.linalg.norm(np.diff(initial_points,n=3,axis=0),axis=-1))*(fps/30.)**3 < .00003*scale
        anchored = np.max(np.linalg.norm((initial_points-contact_targets)[pinned],axis=-1),initial=0.) < PLAYBACK_CONTACT_LIMIT_METERS
        playback_anchored = _playback_contact_sample_error(
            rig.initial, rig, pinned, contact_targets, cyclic=cyclic) < PLAYBACK_CONTACT_LIMIT_METERS
        floor_clear = _playback_floor_penetration(
            rig.initial, rig, cyclic=cyclic, floor=floor) <= PLAYBACK_FLOOR_LIMIT_METERS
        already_valid = (not cyclic and already_rigid and already_smooth and anchored
                         and playback_anchored and floor_clear
                         and validate_physical_motion(initial_points,names,fps=fps)['passed']
                         and validate_grip(initial_points,names,equipment)['passed'])
        geometry_ready = supported_geometry_ready_for_skip_soft_solve(
            anchored=anchored, playback_anchored=playback_anchored, floor_clear=floor_clear,
            points=initial_points, names=names, equipment=equipment, payload=payload,
            support_strategy=report.get('supportInitializationStrategy'))
        if (already_valid or geometry_ready) and not heel_contacts.pairs:
            # Avoid introducing solver noise into an already controlled / supported
            # rig. Soft LS on long plant-only clips raised jerk and ate Stage-C.
            solved = SimpleNamespace(x=rig.initial.ravel(),nfev=0)
            report['skippedSoftSolve'] = (
                'already_valid' if already_valid else 'supported_geometry_ready')
            # Hard Stage-A/C only after a geometry-ready skip — leave room for
            # one playback/grip polish pass, not a soft-LS-sized leftover.
            polish_left = min(float(polish_left), 18.)
        else:
            solve_start = rig.initial.ravel()
            if fit_session is not None and trajectory_key in fit_session.trajectories:
                proposal = np.asarray(fit_session.trajectories[trajectory_key], dtype=float)
                if proposal.shape == solve_start.shape and np.isfinite(proposal).all():
                    initial_error, proposed_error = residual(solve_start), residual(proposal)
                    if proposed_error@proposed_error <= initial_error@initial_error:
                        solve_start = proposal
                        report['resumedTrajectory'] = True
            # Evidence-first main solve: short LS blocks until cost stalls.
            # Outer timeout is only a watchdog — do not require burning it.
            block = 5
            total_nfev = 0
            stall_blocks = 0
            previous_best = float('inf')
            current = solve_start
            solved = SimpleNamespace(x=current, nfev=0, status=1)
            minimum_update_seconds = 0.
            while total_nfev < int(max_evaluations) and monotonic() < optimization_deadline:
                solve_remaining = optimization_deadline - monotonic()
                if minimum_update_seconds > solve_remaining:
                    # A fresh LS call pays for its starting Jacobian before it
                    # can evaluate an update. Do not spend the remaining solve
                    # allowance initializing a block that cannot make progress.
                    report['optimizerTermination'] = 'solve_phase_budget'
                    report['deferredOptimizerBlock'] = {
                        'minimumUpdateSeconds': float(minimum_update_seconds),
                        'remainingSolveSeconds': float(max(0., solve_remaining)),
                    }
                    polish_left += max(0., solve_remaining)
                    break
                # Do not start another dense chunk inside the polish fence.
                if monotonic() >= optimization_deadline - 1.0:
                    report['optimizerTermination'] = 'solve_phase_budget'
                    break
                chunk = min(block, int(max_evaluations) - total_nfev)
                if chunk < 1:
                    break
                block_started = monotonic()
                solved = trajectory_solver(residual, current, pattern, chunk)
                block_evaluations = int(solved.nfev or chunk)
                minimum_update_seconds = 2. * (monotonic() - block_started) / max(1, block_evaluations)
                total_nfev += block_evaluations
                solved.nfev = total_nfev
                current = solved.x
                # Evaluate after the chunk so stall detection works even when the
                # solver stub does not call residual (tests) or returns early.
                chunk_errors = residual(current)
                chunk_cost = float(chunk_errors @ chunk_errors)
                improved = (
                    not np.isfinite(previous_best)
                    or previous_best - chunk_cost > max(1e-12, abs(previous_best) * 1e-6)
                )
                if chunk_cost < previous_best:
                    previous_best = chunk_cost
                if improved:
                    stall_blocks = 0
                else:
                    stall_blocks += 1
                    if stall_blocks >= 2 and total_nfev >= block:
                        report['optimizerTermination'] = 'objective_stalled'
                        break
                # least_squares status > 0 means local convergence.
                if getattr(solved, 'status', 0) > 0:
                    report.setdefault('optimizerTermination', 'converged')
                    break
            else:
                if report.get('optimizerTermination') is None:
                    report['optimizerTermination'] = (
                        'time_budget' if monotonic() >= optimization_deadline
                        else 'evaluation_limit')
            preferred = (
                best_feasible_coordinates
                if best_feasible_coordinates is not None else best_coordinates)
            if preferred is not None:
                if (best_feasible_coordinates is not None
                        and best_coordinates is not None
                        and best_feasible_coordinates is not best_coordinates):
                    report['selectedContactFeasibleIterate'] = True
                solved = SimpleNamespace(x=preferred, nfev=total_nfev,
                                         status=getattr(solved, 'status', 0))
        # Guarantee a bounded Stage-C window from now. Do not extend polish to
        # the full outer timeout — that re-burned soft LS after geometry-ready skip.
        # Mid-sample plant bows need a longer hard-plant window than jerk polish.
        plant_polish = 0.
        if (np.any(pinned) and not playback_anchored
                and report.get('supportInitializationStrategy') == 'plant_projection'):
            plant_polish = 22.
        polish_until = min(
            started + timeout_seconds,
            monotonic() + max(float(polish_left), 12.) + plant_polish,
        )
        report['polishUntilSeconds'] = float(polish_until - started)
    except TimeoutError:
        # A budget ends optimization, not validation. Prefer the best soft-LS
        # iterate; if none was scored yet, still try the initialized rig rather
        # than discarding all pre-solve work as a bare fit_timeout.
        preferred = (
            best_feasible_coordinates
            if best_feasible_coordinates is not None else best_coordinates)
        if preferred is None:
            fallback = np.asarray(rig.initial, dtype=float).ravel()
            if fallback.size and np.isfinite(fallback).all():
                preferred = fallback.copy()
                report['validatedInitializedCoordinatesOnTimeout'] = True
            else:
                return payload,{**report,'reason':'fit_timeout','elapsedSeconds':monotonic()-started}
        if (best_feasible_coordinates is not None
                and best_coordinates is not None
                and best_feasible_coordinates is not best_coordinates):
            report['selectedContactFeasibleIterate'] = True
        solved = SimpleNamespace(x=preferred, nfev=None, status=0)
        # Solve-phase caps leave outer candidate time for short polish of
        # repairable near-misses; only the true outer deadline is time_budget.
        outer_deadline = started + timeout_seconds
        report['optimizerTermination'] = (
            'time_budget' if monotonic() >= outer_deadline - reserved_polish
            else 'solve_phase_budget')
        polish_until = min(
            started + timeout_seconds,
            monotonic() + max(float(reserved_polish), 12.),
        )
        report['polishUntilSeconds'] = float(polish_until - started)
    finally:
        if fit_session is not None and best_coordinates is not None:
            fit_session.trajectories[trajectory_key] = best_coordinates.tolist()
    if 'polish_until' not in locals():
        polish_until = started + timeout_seconds
    if getattr(solved, 'status', 1) == 0:
        report.setdefault('optimizerTermination', 'evaluation_limit')
    def validate_solution(solved, *, project_playback_plants=True):
        # A finite soft-constrained solve can cross the socket boundary again after
        # initialization. Enforce its analytic attachment on the exported coordinates
        # too, then validate geometry, temporal quality and interpolated playback.
        # project_playback_plants=False means the caller already owns mid-sample
        # plants / C1 continuity — do not re-run floor clearance or playback TRF
        # that recreate knot velocity jumps.
        from .physical_validation import SOCKET_ALIGNMENT_MAX_LATERAL_RATIO
        rig.initial[:] = solved.x.reshape(count, rig.width)
        unprojected = rig.decode(rig.initial)
        # Neck / numerical anatomy projection can reintroduce C1 knot jumps after
        # velocity continuity repair — skip when the caller owns the path.
        if project_playback_plants:
            rig.project_neck_attachment(
                maximum_lateral_ratio=SOCKET_ALIGNMENT_MAX_LATERAL_RATIO-ANATOMY_FIT_MARGIN)
            # Interpolated socket clearance changes the pelvis-to-neck axis.
            # Establish it before anatomy polish so a tiny neck correction cannot
            # reopen an already boundary-tight spine constraint afterward.
            rig.initial[:] = project_playback_neck_clearance(
                rig.initial, rig, cyclic=cyclic, deadline=polish_until)
            numerical_errors, _ = repair_residuals(rig.decode(rig.initial), names)
            largest_error = float(np.max(numerical_errors, initial=0.))
            if 1e-6 < largest_error <= ANATOMY_FIT_MARGIN and monotonic() < polish_until:
                previous_coordinates, previous_offsets = rig.initial.copy(), rig.offsets.copy()
                polish_started = monotonic()
                try:
                    _, polish = repair_rig_anatomy(
                        rig, rig.decode(rig.initial), deadline=polish_until)
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
        validation_repair_deadline = min(polish_until, started + timeout_seconds)
        if (project_playback_plants and monotonic() < validation_repair_deadline
                and np.any(pinned) and _playback_failing_intervals(
                rig.initial, rig, pinned, contact_targets, cyclic=cyclic, floor=floor)):
            # Support already spent a play pass on plant_projection; keep validate
            # repair short so Stage-C temporal still gets wall time.
            if report.get('supportPlaybackPlantsApplied') or report.get('skippedSoftSolve'):
                plant_cap = 28.0
                plant_nfev = 16
            else:
                plant_cap = 8.0
                plant_nfev = 12
            rig.initial[:] = project_interval_playback_plants(
                rig.initial, rig, pinned, contact_targets, cyclic=cyclic, floor=floor,
                max_nfev=plant_nfev,
                deadline=min(validation_repair_deadline, monotonic() + plant_cap), spike_reference=spike_reference)
            result = rig.decode(rig.initial)
            solved.x = rig.initial.ravel().copy()
            fixed_rig_payload['coordinates'] = rig.initial.tolist()
            report['validatePlaybackPlantsApplied'] = True
        if (not report.get('introducedSpikeProjectionAttempted')
                and monotonic() < validation_repair_deadline):
            spikes = relative_motion_quality(
                result, result, names, fps, spike_reference=spike_reference)['introducedSpikes']
            if spikes['severe'] and monotonic() < validation_repair_deadline:
                report['introducedSpikeProjectionAttempted'] = True
                report['introducedSpikesBeforeProjection'] = spikes
                rig.initial[:] = project_introduced_spikes_coordinates(
                    rig.initial, rig, pinned, contact_targets, spike_reference,
                    fps=fps, cyclic=cyclic, floor=floor,
                    deadline=min(validation_repair_deadline, monotonic() + 16.))
                result = rig.decode(rig.initial)
                solved.x = rig.initial.ravel().copy()
                fixed_rig_payload['coordinates'] = rig.initial.tolist()
        floor_lift = 0.0
        if (project_playback_plants
                and not body_support.get('required')
                and not payload.get('elevatedSupportSurfaces')):
            rig.initial[:], floor_lift = apply_supported_floor_clearance(
                rig.initial, rig, pinned, contact_targets, floor, cyclic=cyclic)
            solved.x = rig.initial.ravel().copy()
            fixed_rig_payload['coordinates'] = rig.initial.tolist()
            result = rig.decode(rig.initial)
        report['unanchoredFloorClearanceLiftMeters'] = floor_lift
        # Root-rotation smoothing repair: the fit's root orientation DOFs can
        # wobble at movement frequency, adding torso-axis roughness the
        # sourceJoints reference does not have (measured 3-4x on ballistic
        # lifts; smoothing the spine tracks provably cannot remove it). Each
        # pass gaussian-smooths the root rotation columns and is accepted
        # only if the contact anchors still hold within the fit's own
        # keyframe standard and the rotation noise drops — escalate until
        # accepted or the pass budget ends.
        from .temporal_quality import body_orientation_noise as _body_noise
        _rotation_noise = _body_noise(result, names, spike_reference, fps)
        if _rotation_noise.get('severe'):
            _original = result.copy()
            _pinned_joints = [names.index(n) for n in
                              ('left_ankle', 'left_foot', 'right_ankle', 'right_foot')
                              if n in names]
            _sigma = max(1.0, fps * 0.05)
            for _attempt in range(3):
                _candidate = rig.initial.copy()
                _candidate[:, 3:6] = gaussian_filter1d(
                    _candidate[:, 3:6], _sigma * (1. + 0.5 * _attempt),
                    axis=0, mode='nearest')
                _trial = rig.decode(_candidate)
                # Root-rotation smoothing displaces the planted joints; the
                # displacement is a smooth per-frame rigid translation, so
                # subtracting its planted-joint mean restores the contacts
                # while keeping the axis smoothing.
                _delta = np.mean(
                    (_original - _trial)[:, _pinned_joints], axis=1, keepdims=True)
                _trial = _trial + _delta
                _after = _body_noise(_trial, names, spike_reference, fps)
                _contact = float(np.max(np.linalg.norm(
                    (_trial - contact_targets)[pinned], axis=-1), initial=0.))
                if not _after.get('severe') and _contact <= 0.0005:
                    rig.initial[:] = _candidate
                    result = _trial + _delta
                    _rotation_noise = _after
                    report['rootRotationSmoothing'] = {
                        'applied': True,
                        'sigmaFrames': round(_sigma * (1. + 0.5 * _attempt), 2),
                        'passes': _attempt + 1,
                        'rmsBefore': round(float(_rotation_noise.get('outputRmsDegreesAt30Hz') or 0.), 4),
                        'rmsAfter': round(float(_after.get('outputRmsDegreesAt30Hz') or 0.), 4),
                    }
                    break
            else:
                report['rootRotationSmoothing'] = {
                    'applied': False, 'reason': 'no_pass_satisfied_both_screens'}
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
        if body_support.get('required'):
            # Preserve articulation excursion independently of the fitted target.
            # Positional spans also encode torso placement/orientation, which the
            # observed support is explicitly allowed to correct.
            ratios = {label: float(np.ptp(angles(*(result[:, j] for j in cols)))/np.ptp(track))
                      for label, cols, track in support_articulation_tracks}
            range_preserved = support_joint_range_preserved(ratios)
            report['supportArticulationRangeRatios'] = ratios
        else:
            range_preserved = bool(np.all(result_span[moving] >= .85*target_span[moving]))
        # Same authority as settling/jerk: under support, shake baselines belong
        # to the supported working reference, not the pre-support source.
        shake_basis = settling_basis if body_support.get('required') else temporal_reference
        acceleration_before = np.sqrt(np.mean(np.diff(shake_basis,n=2,axis=0)**2,axis=(0,2)))
        acceleration_after = np.sqrt(np.mean(np.diff(result,n=2,axis=0)**2,axis=(0,2)))
        no_new_shake = bool(np.all(acceleration_after <= np.maximum(acceleration_before*1.2,.003*(30./fps)**2)))
        settling_after = weighted_settling_speed(result, names, fps, hold_weights)
        settling_preserved = settling_after <= settling_limit
        relative_quality = relative_motion_quality(
            result, shake_basis, names, fps, spike_reference=spike_reference)
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
                      settlingLimit=settling_limit,
                      relativeMotionQuality=relative_quality,
                      rootMotionQuality=root_quality,
                      physicalReasons=physical['reasons'],physicalEvents=physical['events'][:12],
                      balance=physical['balance'],balancePolicy='advisory_only',
                      maximumAnkleAnchorCalibrationMeters=ankle_anchor_calibration)
        if not accepted and getattr(solved, 'status', 1) == 0:
            term = report.get('optimizerTermination')
            # A finished check vector is a decisive reject. Optimizer
            # time_budget/eval caps are how the soft LS stopped — not missing
            # processing evidence. Only pre-validation aborts stay fit_timeout.
            if term in {'time_budget', 'solve_phase_budget', 'objective_stalled', 'converged'}:
                report['reason'] = 'fit_validation_failed'
            else:
                report['reason'] = 'fit_evaluation_limit'
        # Always build the export candidate and score playback/seam so polish and
        # diagnosis see the full acceptance vector (equipment must not hide seam).
        candidate = deepcopy(payload)
        candidate['equipmentConstraints'] = equipment
        if repaired_reference is not None:
            candidate['anatomicalSourceRepair'] = report['anatomicalSourceRepair']
            for frame, corrected in zip(candidate['frames'], repaired_reference):
                frame['correctedAnatomicalReferenceJoints'] = dict(zip(names, corrected.tolist()))
        candidate.pop('scenePlacement', None)
        for index, (frame,values,registered_source) in enumerate(zip(candidate['frames'],result,points)):
            if not (candidate.get('sourcePoseCameraReference') and frame.get('controlledSourceJoints')):
                frame['controlledSourceJoints']={n:v.tolist() for n,v in zip(names,registered_source)}
            # Same articulation reference keyframe anatomy acceptance uses.
            frame['controlledArticulationReferenceJoints'] = {
                n: v.tolist() for n, v in zip(names, reference[index])}
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
        accepted = all(report['checks'].values())
        if not accepted:
            failed = set(failed_check_names(report['checks']))
            # Keep the seam failure visible to bounded Stage-B projection.
            # Declaring an open seam applied here bypasses that repair entirely.
            # The final fallback below retains usable open motion after polish.
            if not playback['passed'] and failed <= {'playback', 'loopSeam'}:
                report.update(applied=False, reason='playback_validation_failed')
            else:
                report.update(applied=False, reason='fit_validation_failed')
            return (candidate if failed <= {'loopSeam', 'playback'} else payload), report
        if candidate.get('loop',{}).get('enabled'):
            candidate['loop'] = {**candidate['loop'],'transition':'continuous',
                                 'restartFadeMillis':0}
        candidate.pop('sequenceStabilization', None)
        report['outputPoseDigest']=pose_digest(candidate)
        report.update(applied=True, reason='validated_controlled_motion')
        return candidate,report

    validation_started = monotonic()
    remaining_polish = max(0., polish_until - validation_started)
    candidate, report = validate_solution(solved)
    # Validation includes contact projection and dense playback checks. Charge
    # that work to the outer budget, but do not silently spend the reserved
    # refinement window before the first failed checks are available.
    polish_until = min(started + timeout_seconds, monotonic() + remaining_polish)
    report['initialValidationSeconds'] = monotonic() - validation_started
    report['polishUntilSeconds'] = float(polish_until - started)
    # Evidence-first: accept or proven unreachable/conflict ends the fit.
    # Time budget is only a watchdog for polishable near-misses still moving.
    if report.get('applied'):
        return candidate, report
    if unreachable_without_polish(report):
        report['termination'] = 'unreachable_conflict'
        report['reason'] = 'fit_validation_failed'
        report.setdefault('boundedRefinement', {
            'initialFailedChecks': failed_check_names(report.get('checks')),
            'evaluationsPerBlock': 0, 'blocks': [],
            'stopReason': 'unreachable_conflict',
        })
        return payload, report
    # Soft solve often overruns into the polish reserve. Cheap Stage-C hard ops
    # (playback plants, jerk smooth) still clear near-misses — run them once
    # even slightly past the soft deadline before giving up.
    failed_checks = failed_check_names(report.get('checks'))
    skip_hard_only = bool(report.get('skippedSoftSolve'))
    if (allow_refinement and polishable_near_miss(failed_checks)
            and (set(failed_checks) <= (POLISH_STAGE_C | POLISH_STAGE_B) or skip_hard_only)
            and (report.get('maximumContactErrorMeters') or 0.) < 0.0005
            and monotonic() < started + timeout_seconds
            and not fit_should_yield_for_priority()):
        refinement = report.setdefault('boundedRefinement', {
            'initialFailedChecks': failed_checks, 'evaluationsPerBlock': 0, 'blocks': []})
        if (skip_hard_only and 'equipment' in failed_checks
                and 'contacts' not in failed_checks
                and not refinement.get('rigidPairGripProjection')
                and equipment.get('handRelationship') == 'rigid_pair'
                and equipment.get('available')):
            previous_coordinates = solved.x.copy()
            previous_failed = set(failed_checks)
            previous_contact = float(report.get('maximumContactErrorMeters') or 0.)
            grip_budget = min(10., max(2., polish_until - monotonic() - 1.))
            projected = project_rigid_pair_grip_coordinates(
                solved.x.reshape(count, rig.width), rig, names, equipment,
                pinned=pinned, max_nfev=25, deadline=min(started + timeout_seconds, monotonic() + max(1., grip_budget)))
            if np.any(pinned):
                projected = project_contact_root_translation(
                    projected, rig, pinned, contact_targets, passes=2, smooth_fps=fps)
                plant_deadline = monotonic() + min(8., max(1., polish_until - monotonic()))
                if plant_deadline > monotonic():
                    projected = project_contact_plant_coordinates(
                        projected, rig, pinned, contact_targets, max_nfev=20,
                        deadline=min(started + timeout_seconds, plant_deadline))
                    if _playback_failing_intervals(
                            projected, rig, pinned, contact_targets, cyclic=cyclic, floor=floor):
                        projected = project_interval_playback_plants(
                            projected, rig, pinned, contact_targets, cyclic=cyclic,
                            floor=floor, max_nfev=16,
                            deadline=min(started + timeout_seconds, monotonic() + min(10., max(1., polish_until - monotonic()))), spike_reference=spike_reference)
            solved = SimpleNamespace(
                x=projected.ravel(), nfev=solved.nfev, status=getattr(solved, 'status', 1))
            candidate, report = validate_solution(solved, project_playback_plants=False)
            refinement['rigidPairGripProjection'] = True
            block_failed = failed_check_names(report.get('checks'))
            refinement['blocks'].append({
                'costBefore': None, 'costAfter': None, 'method': 'rigid_pair_grip_projection',
                'stage': 'A', 'failedChecks': block_failed})
            if report.get('applied'):
                return candidate, report
            contact_after = float(report.get('maximumContactErrorMeters') or 0.)
            if (contact_after >= 0.0005
                    or ({'anatomy', 'sourceArticulation', 'contacts'} & set(block_failed)) - previous_failed):
                solved = SimpleNamespace(x=previous_coordinates, nfev=solved.nfev, status=0)
                candidate, report = validate_solution(solved)
            failed_checks = failed_check_names(report.get('checks'))
        if ('playback' in failed_checks and np.any(pinned)
                and not refinement.get('playbackPlantProjection')):
            previous_coordinates = solved.x.copy()
            previous_failed = set(failed_checks)
            previous_contact = float(report.get('maximumContactErrorMeters') or 0.)
            previous_play = float((report.get('playback') or {}).get('maximumContactErrorMeters') or 0.)
            plant_nfev = 16 if report.get('skippedSoftSolve') else 12
            plant_seconds = 24.0 if report.get('skippedSoftSolve') else 8.0
            if report.get('supportPlaybackPlantsApplied') and report.get('validatePlaybackPlantsApplied'):
                plant_seconds = min(plant_seconds, 20.0)
            projected = project_interval_playback_plants(
                solved.x.reshape(count, rig.width), rig, pinned, contact_targets,
                cyclic=cyclic, floor=floor, max_nfev=plant_nfev,
                deadline=min(started + timeout_seconds, monotonic() + plant_seconds), spike_reference=spike_reference)
            solved = SimpleNamespace(
                x=projected.ravel(), nfev=solved.nfev, status=getattr(solved, 'status', 1))
            candidate, report = validate_solution(solved, project_playback_plants=False)
            refinement['playbackPlantProjection'] = True
            block_failed = failed_check_names(report.get('checks'))
            refinement['blocks'].append({
                'costBefore': None, 'costAfter': None, 'method': 'playback_plant_projection',
                'stage': 'C', 'failedChecks': block_failed})
            if report.get('applied'):
                return candidate, report
            contact_after = float(report.get('maximumContactErrorMeters') or 0.)
            play_after = float((report.get('playback') or {}).get('maximumContactErrorMeters') or 0.)
            if (contact_after >= 0.0005
                    or contact_after > previous_contact * 1.05 + 1e-9
                    or play_after > previous_play * 1.05 + 1e-9
                    or ({'anatomy', 'sourceArticulation', 'contacts'} & set(block_failed)) - previous_failed):
                solved = SimpleNamespace(x=previous_coordinates, nfev=solved.nfev, status=0)
                candidate, report = validate_solution(solved)
            failed_checks = failed_check_names(report.get('checks'))
        # Playback can fail nested equipment / velocity while keyframe checks pass.
        nested = _playback_nested_failures(report.get('playback'))
        if (skip_hard_only and 'playback' in failed_checks
                and nested & {'equipment', 'velocity', 'physical'}
                and (report.get('maximumContactErrorMeters') or 0.) < 0.0005
                and not refinement.get('playbackPathRepair')):
            previous_coordinates = solved.x.copy()
            previous_contact = float(report.get('maximumContactErrorMeters') or 0.)
            previous_play = float((report.get('playback') or {}).get('maximumContactErrorMeters') or 0.)
            previous_nested = set(nested)
            projected = solved.x.reshape(count, rig.width).copy()
            # Grip gets its own slice; velocity budget is refreshed after grip so
            # a long grip validate cannot skip continuity repair entirely.
            outer_left = max(0., started + timeout_seconds - monotonic() - 5.)
            grip_deadline = monotonic() + min(16., max(4., 0.35 * outer_left))
            kept = previous_coordinates
            kept_play = previous_play
            kept_nested = previous_nested

            def _accept_path(trial, label):
                nonlocal kept, kept_play, kept_nested, solved, candidate, report, failed_checks
                solved = SimpleNamespace(
                    x=trial.ravel(), nfev=solved.nfev, status=getattr(solved, 'status', 1))
                candidate, report = validate_solution(solved, project_playback_plants=False)
                contact_after = float(report.get('maximumContactErrorMeters') or 0.)
                play_after = float((report.get('playback') or {}).get('maximumContactErrorMeters') or 0.)
                nested_after = _playback_nested_failures(report.get('playback'))
                # Never keep a trial that reopens the playback plant gate.
                if (contact_after >= 0.0005
                        or 'contact' in nested_after
                        or play_after > max(previous_play * 1.5, 0.00075) + 1e-9):
                    return False
                cleared_velocity = (
                    'velocity' in (kept_nested | previous_nested)
                    and 'velocity' not in nested_after)
                cleared_equipment = (
                    'equipment' in (kept_nested | previous_nested)
                    and 'equipment' not in nested_after)
                improved = (
                    report.get('applied')
                    or (not nested_after and previous_nested)
                    or cleared_velocity
                    or (cleared_equipment and 'velocity' not in nested_after)
                    or (len(nested_after) < len(kept_nested)
                        and not ({'velocity'} & nested_after - kept_nested)))
                if improved:
                    kept = trial.copy()
                    kept_play = play_after
                    kept_nested = nested_after
                    refinement['blocks'].append({
                        'costBefore': None, 'costAfter': None, 'method': label,
                        'stage': 'C', 'failedChecks': failed_check_names(report.get('checks')),
                        'nestedBefore': sorted(previous_nested),
                        'nestedAfter': sorted(nested_after)})
                    failed_checks = failed_check_names(report.get('checks'))
                    return True
                return False

            if 'equipment' in nested and equipment.get('handRelationship') == 'rigid_pair':
                trial = project_rigid_pair_grip_coordinates(
                    projected, rig, names, equipment, pinned=pinned, max_nfev=25,
                    deadline=min(started + timeout_seconds, grip_deadline))
                trial = project_playback_rigid_pair_grip(
                    trial, rig, names, equipment, pinned=pinned, cyclic=cyclic,
                    max_nfev=16, deadline=grip_deadline)
                if np.any(pinned):
                    trial = project_contact_plant_coordinates(
                        trial, rig, pinned, contact_targets, max_nfev=16,
                        freeze_root=True, deadline=min(started + timeout_seconds, grip_deadline))
                    if _playback_failing_intervals(
                            trial, rig, pinned, contact_targets, cyclic=cyclic, floor=floor):
                        trial = project_interval_playback_plants(
                            trial, rig, pinned, contact_targets, cyclic=cyclic,
                            floor=floor, max_nfev=12, deadline=min(started + timeout_seconds, grip_deadline), spike_reference=spike_reference)
                if _accept_path(trial, 'playback_grip_repair'):
                    projected = kept.reshape(count, rig.width)
                    if report.get('applied'):
                        refinement['playbackPathRepair'] = True
                        return candidate, report
            # Always continue velocity repair from the best kept state, even when
            # the last validate rejected a grip trial.
            projected = np.asarray(kept, dtype=float).reshape(count, rig.width)
            nested = set(kept_nested)
            path_deadline = monotonic() + min(
                60., max(20., started + timeout_seconds - monotonic() - 5.))
            if nested & {'velocity', 'physical', 'equipment'} and monotonic() < path_deadline:
                trial = repair_playback_velocity_continuity(
                    projected, rig, pinned, contact_targets, cyclic=cyclic, sigma=0.75,
                    names=names, equipment=equipment,
                    deadline=min(started + timeout_seconds, path_deadline), floor=floor, spike_reference=spike_reference, fps=fps)
                # Keep the velocity/plant win first — mid-sample anatomy polish must
                # not discard a cleared C1 jump when it fails or reopens plants.
                _accept_path(trial, 'playback_velocity_repair')
                if (report.get('applied')
                        or ('physical' not in set(kept_nested))
                        or monotonic() >= path_deadline):
                    pass
                else:
                    anatomy_trial = np.asarray(kept, dtype=float).reshape(count, rig.width)
                    previous_initial = rig.initial.copy()
                    previous_offsets = rig.offsets.copy()
                    rig.initial[:] = anatomy_trial
                    try:
                        from .anatomical_repair import repair_rig_anatomy
                        _, polish = repair_rig_anatomy(
                            rig, rig.decode(rig.initial),
                            deadline=min(path_deadline, monotonic() + 8.))
                        if polish.get('passed'):
                            anatomy_trial = rig.initial.copy()
                            if np.any(pinned):
                                anatomy_trial = project_contact_plant_coordinates(
                                    anatomy_trial, rig, pinned, contact_targets,
                                    max_nfev=12, freeze_root=True, deadline=min(started + timeout_seconds, path_deadline))
                                if _playback_failing_intervals(
                                        anatomy_trial, rig, pinned, contact_targets,
                                        cyclic=cyclic, floor=floor):
                                    anatomy_trial = project_interval_playback_plants(
                                        anatomy_trial, rig, pinned, contact_targets,
                                        cyclic=cyclic, floor=floor, max_nfev=12,
                                        deadline=min(started + timeout_seconds, path_deadline), spike_reference=spike_reference)
                            _accept_path(anatomy_trial, 'playback_anatomy_repair')
                        else:
                            rig.initial[:] = previous_initial
                            rig.offsets[:] = previous_offsets
                    except Exception:
                        rig.initial[:] = previous_initial
                        rig.offsets[:] = previous_offsets
            # Restore best kept trial if the last validate rejected it.
            if not np.allclose(solved.x.reshape(count, -1), kept.reshape(count, -1)):
                solved = SimpleNamespace(
                    x=kept.ravel(), nfev=solved.nfev, status=getattr(solved, 'status', 1))
                candidate, report = validate_solution(solved, project_playback_plants=False)
                failed_checks = failed_check_names(report.get('checks'))
            refinement['playbackPathRepair'] = True
            if report.get('applied'):
                return candidate, report
            # If path repair reopened the plant gate, roll back.
            contact_after = float(report.get('maximumContactErrorMeters') or 0.)
            play_after = float((report.get('playback') or {}).get('maximumContactErrorMeters') or 0.)
            if (contact_after >= 0.0005
                    or play_after >= PLAYBACK_CONTACT_LIMIT_METERS):
                solved = SimpleNamespace(x=previous_coordinates, nfev=solved.nfev, status=0)
                candidate, report = validate_solution(solved)
                failed_checks = failed_check_names(report.get('checks'))
        if (({'jointShake', 'relativeJointShake', 'settling'} & set(failed_checks))
                and not refinement.get('temporalShakeSmooth')
                and (set(failed_checks) <= (POLISH_STAGE_C | POLISH_STAGE_B | {'anatomy', 'playback'})
                     or refinement.get('playbackPathRepair'))
                and (report.get('maximumContactErrorMeters') or 0.) < 0.0005):
            previous_coordinates = solved.x.copy()
            previous_failed = set(failed_checks)
            previous_contact = float(report.get('maximumContactErrorMeters') or 0.)
            previous_jerk = report.get('jerkAfter')
            previous_nested = _playback_nested_failures(report.get('playback'))
            keep_path = bool(refinement.get('playbackPathRepair'))
            # After path repair, aggressive shake smooth recreates C1 jumps and
            # lifts plants; use a mild pass then restore velocity continuity.
            shake_sigma = 0.55 if keep_path else 1.5
            shaken = temporal_coordinate_smooth(
                solved.x.reshape(count, rig.width), cyclic=cyclic, sigma=shake_sigma)
            if np.any(pinned):
                shaken = project_contact_plant_coordinates(
                    shaken, rig, pinned, contact_targets, max_nfev=8, freeze_root=True,
                    deadline=started + timeout_seconds)
            if keep_path and np.any(pinned):
                shaken = repair_playback_velocity_continuity(
                    shaken, rig, pinned, contact_targets, cyclic=cyclic, sigma=0.45,
                    deadline=min(started + timeout_seconds, monotonic() + 12.), floor=floor, spike_reference=spike_reference, fps=fps)
            solved = SimpleNamespace(
                x=shaken.ravel(), nfev=solved.nfev, status=getattr(solved, 'status', 1))
            candidate, report = validate_solution(
                solved, project_playback_plants=(
                    False if keep_path else ('playback' in failed_checks)))
            refinement['temporalShakeSmooth'] = True
            block_failed = failed_check_names(report.get('checks'))
            refinement['blocks'].append({
                'costBefore': None, 'costAfter': None, 'method': 'temporal_shake_smooth',
                'stage': 'C', 'failedChecks': block_failed})
            if report.get('applied'):
                return candidate, report
            contact_after = float(report.get('maximumContactErrorMeters') or 0.)
            play_after = float((report.get('playback') or {}).get('maximumContactErrorMeters') or 0.)
            nested_after = _playback_nested_failures(report.get('playback'))
            if (contact_after >= 0.0005
                    or play_after >= PLAYBACK_CONTACT_LIMIT_METERS
                    or contact_after > previous_contact * 1.05 + 1e-9
                    or ({'anatomy', 'sourceArticulation', 'contacts'} & set(block_failed)) - previous_failed
                    or polish_worsened_jerk(report, previous_jerk)
                    or ('velocity' not in previous_nested and 'velocity' in nested_after)):
                solved = SimpleNamespace(x=previous_coordinates, nfev=solved.nfev, status=0)
                candidate, report = validate_solution(
                    solved, project_playback_plants=not keep_path)
            failed_checks = failed_check_names(report.get('checks'))
        if (report.get('checks') and 'jerk' in failed_checks
                and not refinement.get('temporalJerkSmooth')
                and (set(failed_checks) <= (POLISH_STAGE_C | POLISH_STAGE_B | {'anatomy', 'playback'})
                     or refinement.get('playbackPathRepair'))
                and (report.get('maximumContactErrorMeters') or 0.) < 0.0005):
            previous_coordinates = solved.x.copy()
            previous_failed = set(failed_checks)
            previous_contact = float(report.get('maximumContactErrorMeters') or 0.)
            previous_jerk = report.get('jerkAfter')
            previous_nested = _playback_nested_failures(report.get('playback'))
            keep_path = bool(refinement.get('playbackPathRepair'))
            # Milder than the default Stage-C smooth — sigma=1 often re-broke
            # plants/anatomy on long plant-only clips after grip projection.
            jerk_sigma = 0.4 if keep_path else 0.5
            smoothed = temporal_coordinate_smooth(
                solved.x.reshape(count, rig.width), cyclic=cyclic, sigma=jerk_sigma)
            if np.any(pinned):
                smoothed = project_contact_plant_coordinates(
                    smoothed, rig, pinned, contact_targets, max_nfev=8, freeze_root=True,
                    deadline=started + timeout_seconds)
            if keep_path and np.any(pinned):
                smoothed = repair_playback_velocity_continuity(
                    smoothed, rig, pinned, contact_targets, cyclic=cyclic, sigma=0.4,
                    deadline=min(started + timeout_seconds, monotonic() + 10.), floor=floor, spike_reference=spike_reference, fps=fps)
            solved = SimpleNamespace(
                x=smoothed.ravel(), nfev=solved.nfev, status=getattr(solved, 'status', 1))
            candidate, report = validate_solution(
                solved, project_playback_plants=(
                    False if keep_path else ('playback' in failed_checks)))
            refinement['temporalJerkSmooth'] = True
            block_failed = failed_check_names(report.get('checks'))
            refinement['blocks'].append({
                'costBefore': None, 'costAfter': None, 'method': 'temporal_smooth',
                'stage': 'C', 'failedChecks': block_failed})
            if report.get('applied'):
                return candidate, report
            contact_after = float(report.get('maximumContactErrorMeters') or 0.)
            play_after = float((report.get('playback') or {}).get('maximumContactErrorMeters') or 0.)
            nested_after = _playback_nested_failures(report.get('playback'))
            # Keep a partial jerk improvement; only revert when plants/anatomy break
            # or jerk gets worse.
            if (contact_after >= 0.0005
                    or play_after >= PLAYBACK_CONTACT_LIMIT_METERS
                    or contact_after > previous_contact * 1.05 + 1e-9
                    or ({'anatomy', 'sourceArticulation', 'contacts'} & set(block_failed)) - previous_failed
                    or polish_worsened_jerk(report, previous_jerk)
                    or ('velocity' not in previous_nested and 'velocity' in nested_after)):
                solved = SimpleNamespace(x=previous_coordinates, nfev=solved.nfev, status=0)
                candidate, report = validate_solution(
                    solved, project_playback_plants=not keep_path)
            failed_checks = failed_check_names(report.get('checks'))
        # Playback path is clear but mild temporal left jerk/shake — free-DOF
        # smooth plus anatomy restore. Full-rotation smooth lifts plants; free
        # smooth alone can trip anatomy_torso_bend on hinge clips.
        if (refinement.get('playbackPathRepair')
                and not refinement.get('temporalPathStrong')
                and (report.get('playback') or {}).get('passed')
                and ({'jerk', 'jointShake', 'relativeJointShake', 'settling'} & set(failed_checks))
                and (report.get('maximumContactErrorMeters') or 0.) < 0.0005):
            previous_coordinates = solved.x.copy()
            previous_failed = set(failed_checks)
            previous_jerk = report.get('jerkAfter')
            previous_play = float((report.get('playback') or {}).get('maximumContactErrorMeters') or 0.)
            previous_initial = rig.initial.copy()
            previous_offsets = rig.offsets.copy()
            strong = polish_free_temporal_preserving_anatomy(
                solved.x.reshape(count, rig.width), rig, pinned, contact_targets,
                cyclic=cyclic, sigma=1.25,
                deadline=min(started + timeout_seconds, monotonic() + min(18., max(6., started + timeout_seconds - monotonic()))),
                floor=floor, fps=fps, spike_reference=spike_reference)
            solved = SimpleNamespace(
                x=strong.ravel(), nfev=solved.nfev, status=getattr(solved, 'status', 1))
            candidate, report = validate_solution(solved, project_playback_plants=False)
            refinement['temporalPathStrong'] = True
            block_failed = failed_check_names(report.get('checks'))
            refinement['blocks'].append({
                'costBefore': None, 'costAfter': None, 'method': 'temporal_path_strong',
                'stage': 'C', 'failedChecks': block_failed})
            if report.get('applied'):
                return candidate, report
            contact_after = float(report.get('maximumContactErrorMeters') or 0.)
            play_after = float((report.get('playback') or {}).get('maximumContactErrorMeters') or 0.)
            nested_after = _playback_nested_failures(report.get('playback'))
            if (contact_after >= 0.0005
                    or play_after >= PLAYBACK_CONTACT_LIMIT_METERS
                    or play_after > previous_play * 1.05 + 1e-9
                    or not (report.get('playback') or {}).get('passed')
                    or 'velocity' in nested_after
                    or ({'anatomy', 'sourceArticulation', 'contacts'} & set(block_failed)) - previous_failed
                    or polish_worsened_jerk(report, previous_jerk)):
                rig.initial[:] = previous_initial
                rig.offsets[:] = previous_offsets
                solved = SimpleNamespace(x=previous_coordinates, nfev=solved.nfev, status=0)
                candidate, report = validate_solution(solved, project_playback_plants=False)
            failed_checks = failed_check_names(report.get('checks'))
            # Path repair often outlives the original polish fence; give Stage-C a
            # fresh outer-bounded window when only temporal leftovers remain.
            if (not report.get('applied')
                    and (report.get('playback') or {}).get('passed')
                    and set(failed_checks) <= POLISH_STAGE_C):
                leftover_budget = max(0., started + timeout_seconds - monotonic())
                if leftover_budget >= 4.:
                    polish_until = min(
                        started + timeout_seconds,
                        monotonic() + min(20., leftover_budget))
                    report['polishUntilSeconds'] = float(polish_until - started)
        if (report.get('skippedSoftSolve') and not report.get('applied')
                and polishable_near_miss(failed_check_names(report.get('checks')))):
            leftover = set(failed_check_names(report.get('checks')))
            nested_left = _playback_nested_failures(report.get('playback'))
            play_ok = bool((report.get('playback') or {}).get('passed'))
            seam_pending = cyclic and play_ok and leftover == {'loopSeam'}
            if seam_pending:
                # Reserve the bounded 10-second projection plus its before/after
                # validation; the approach window must not lose its solve budget
                # to the earlier cheap nudge.
                polish_until = min(started + timeout_seconds, max(polish_until, monotonic() + 16.))
            # Exhaust only when playback path issues remain. Pure temporal leftovers
            # after a cleared path keep polishing (free-DOF Stage-C / soft loop).
            if not seam_pending and (leftover & (POLISH_STAGE_A | POLISH_STAGE_B)
                    or nested_left & {'equipment', 'velocity', 'contact', 'physical'}
                    or ('playback' in leftover and nested_left)
                    or not (play_ok and leftover <= POLISH_STAGE_C)):
                refinement = report.setdefault('boundedRefinement', {
                    'initialFailedChecks': failed_checks, 'evaluationsPerBlock': 0, 'blocks': []})
                refinement['stopReason'] = 'hard_polish_exhausted'
                report['termination'] = 'hard_polish_exhausted'
    # Spend remaining outer time on staged post-solve polish:
    # A contacts/equipment → B seam/playback → C temporal.
    while (allow_refinement and not report.get('applied') and report.get('checks')
            and monotonic() < polish_until
            and report.get('termination') not in EVIDENCE_TERMINATIONS
            and not fit_should_yield_for_priority()):
        failed_checks = failed_check_names(report['checks'])
        remaining = max(0., polish_until - monotonic())
        if remaining < 0.5:
            break
        if unreachable_without_polish(report):
            report['termination'] = 'unreachable_conflict'
            report.setdefault('boundedRefinement', {
                'initialFailedChecks': failed_checks, 'evaluationsPerBlock': 0, 'blocks': []
            })['stopReason'] = 'unreachable_conflict'
            break
        near_miss = polishable_near_miss(failed_checks)
        # Near-miss leftovers should keep polishing even after a solve time_budget label.
        # Reserved polish window (polish_until) is authoritative — do not abort early
        # just because the soft LS reported time_budget.
        if (report.get('optimizerTermination') == 'time_budget'
                and not near_miss
                and remaining < 1.):
            break
        if hard_trajectory_and_root_failure(report.get('checks')):
            report.setdefault('boundedRefinement', {
                'initialFailedChecks': failed_checks, 'evaluationsPerBlock': 5, 'blocks': []
            })['stopReason'] = 'hard_trajectory_root_failure'
            report['termination'] = 'hard_trajectory_root_failure'
            break
        stage = polish_stage_for_failures(failed_checks)
        polish_evaluations = 5 if remaining < 40. else min(8, int(max_evaluations))
        refinement = report.setdefault('boundedRefinement', {
            'initialFailedChecks': failed_checks, 'evaluationsPerBlock': polish_evaluations, 'blocks': []})
        refinement['evaluationsPerBlock'] = polish_evaluations
        refinement['stage'] = stage
        # Stage-capped block budgets so one LS timeout cannot eat the whole leftover.
        stage_share = {'A': .40, 'B': .35, 'C': .30}.get(stage, .35)
        if report.get('optimizerTermination') in {'solve_phase_budget', 'time_budget', 'evaluation_limit'}:
            block_budget = min(remaining - 0.5, max(5., remaining * stage_share))
            optimization_deadline = monotonic() + block_budget
            report['optimizerTermination'] = 'evaluation_limit'
        # Soft LS rarely beats contact-dominated cost on jerk-only near-misses.
        # One cheap rotation smooth often clears excess third differences without
        # another long least-squares burn.
        if (stage == 'C' and 'playback' in failed_checks
                and not refinement.get('playbackPlantProjection')
                and np.any(pinned)
                and (report.get('maximumContactErrorMeters') or 0.) < 0.0005):
            previous_coordinates = solved.x.copy()
            previous_failed = set(failed_checks)
            previous_contact = float(report.get('maximumContactErrorMeters') or 0.)
            remaining = started + timeout_seconds - monotonic()
            plant_budget = max(0.5, min(4.0, remaining)) if remaining > 0.5 else 0.5
            projected = project_interval_playback_plants(
                solved.x.reshape(count, rig.width), rig, pinned, contact_targets,
                cyclic=cyclic, floor=floor, deadline=min(started + timeout_seconds, monotonic() + plant_budget), spike_reference=spike_reference)
            solved = SimpleNamespace(
                x=projected.ravel(), nfev=solved.nfev, status=getattr(solved, 'status', 1))
            # Plants already projected; skip a second clip-wide plant TRF in validate.
            candidate, report = validate_solution(solved, project_playback_plants=False)
            refinement['playbackPlantProjection'] = True
            block_failed = failed_check_names(report.get('checks'))
            refinement['blocks'].append({
                'costBefore': None, 'costAfter': None, 'method': 'playback_plant_projection',
                'stage': stage, 'failedChecks': block_failed})
            if report.get('applied'):
                break
            contact_after = float(report.get('maximumContactErrorMeters') or 0.)
            if (contact_after >= 0.0005
                    or contact_after > previous_contact * 1.05 + 1e-9
                    or ({'anatomy', 'sourceArticulation', 'contacts'} & set(block_failed)) - previous_failed):
                solved = SimpleNamespace(x=previous_coordinates, nfev=solved.nfev, status=0)
                candidate, report = validate_solution(solved)
            continue
        if (stage == 'C' and 'jerk' in failed_checks and not refinement.get('temporalJerkSmooth')
                and set(failed_checks) <= (POLISH_STAGE_C | POLISH_STAGE_B)
                and (report.get('maximumContactErrorMeters') or 0.) < 0.00035):
            previous_coordinates = solved.x.copy()
            previous_failed = set(failed_checks)
            previous_contact = float(report.get('maximumContactErrorMeters') or 0.)
            smoothed = temporal_coordinate_smooth(
                solved.x.reshape(count, rig.width), cyclic=cyclic).ravel()
            solved = SimpleNamespace(x=smoothed, nfev=solved.nfev, status=getattr(solved, 'status', 1))
            candidate, report = validate_solution(solved)
            refinement['temporalJerkSmooth'] = True
            block_failed = failed_check_names(report.get('checks'))
            refinement['blocks'].append({
                'costBefore': None, 'costAfter': None, 'method': 'temporal_smooth', 'stage': stage,
                'failedChecks': block_failed})
            if report.get('applied'):
                break
            contact_after = float(report.get('maximumContactErrorMeters') or 0.)
            if ('jerk' in block_failed
                    or contact_after >= 0.0005
                    or contact_after > previous_contact * 1.05 + 1e-9
                    or ({'anatomy', 'sourceArticulation', 'contacts'} & set(block_failed)) - previous_failed):
                solved = SimpleNamespace(x=previous_coordinates, nfev=solved.nfev, status=0)
                candidate, report = validate_solution(solved)
            continue
        # Stage-C: hard root continuity smooth before soft LS burns the leftover.
        if (stage == 'C' and 'rootContinuity' in failed_checks
                and not refinement.get('rootContinuitySmooth')
                and (report.get('maximumContactErrorMeters') or 0.) < 0.0005):
            previous_coordinates = solved.x.copy()
            previous_failed = set(failed_checks)
            previous_contact = float(report.get('maximumContactErrorMeters') or 0.)
            smoothed = smooth_root_translation_coordinates(
                solved.x.reshape(count, rig.width), fps, scale=scale)
            if np.any(pinned):
                # Continuity edits move world plants. Recover with limb DOFs only
                # (frozen root) so contact repair cannot reintroduce pelvis spikes.
                smoothed = project_contact_plant_coordinates(
                    smoothed, rig, pinned, contact_targets, max_nfev=40, freeze_root=True,
                    deadline=started + timeout_seconds)
                if not root_motion_quality(smoothed[:, :3], fps, scale)['passed']:
                    smoothed = project_root_continuity_coordinates(smoothed, fps, scale)
                    smoothed = project_contact_plant_coordinates(
                        smoothed, rig, pinned, contact_targets, max_nfev=30, freeze_root=True,
                        deadline=started + timeout_seconds)
            solved = SimpleNamespace(
                x=smoothed.ravel(), nfev=solved.nfev, status=getattr(solved, 'status', 1))
            candidate, report = validate_solution(solved)
            refinement['rootContinuitySmooth'] = True
            block_failed = failed_check_names(report.get('checks'))
            refinement['blocks'].append({
                'costBefore': None, 'costAfter': None, 'method': 'root_continuity_smooth',
                'stage': stage, 'failedChecks': block_failed})
            if report.get('applied'):
                break
            contact_after = float(report.get('maximumContactErrorMeters') or 0.)
            introduced = set(block_failed) - previous_failed
            # Never keep a continuity edit that invents anatomy/articulation damage
            # or re-breaks planted contacts / support.
            if (introduced & {'anatomy', 'sourceArticulation', 'jointRange'}
                    or contact_after >= 0.0005
                    or contact_after > previous_contact * 1.05 + 1e-9
                    or ({'contacts', 'bodySupport', 'supportAlignment'} & introduced)):
                solved = SimpleNamespace(x=previous_coordinates, nfev=solved.nfev, status=0)
                candidate, report = validate_solution(solved)
            continue
        if (stage == 'C' and 'motionDiscontinuity' in failed_checks
                and not refinement.get('motionDiscontinuitySmooth')
                and (report.get('maximumContactErrorMeters') or 0.) < 0.0005):
            previous_coordinates = solved.x.copy()
            previous_failed = set(failed_checks)
            previous_contact = float(report.get('maximumContactErrorMeters') or 0.)
            previous_jerk = report.get('jerkAfter')
            # Mild single-pass extremity smooth left ~0.2 body-ratio swing-foot
            # spikes intact; escalate free distal-chain repair until the gate clears.
            smoothed = repair_motion_discontinuity_coordinates(
                solved.x.reshape(count, rig.width), rig, names, cyclic=cyclic, fps=fps,
                pinned=pinned, scale=scale, contact_targets=contact_targets)
            # Skip plant recovery when only free extremities moved.
            solved = SimpleNamespace(
                x=smoothed.ravel(), nfev=solved.nfev, status=getattr(solved, 'status', 1))
            candidate, report = validate_solution(solved)
            refinement['motionDiscontinuitySmooth'] = True
            block_failed = failed_check_names(report.get('checks'))
            refinement['blocks'].append({
                'costBefore': None, 'costAfter': None, 'method': 'motion_discontinuity_smooth',
                'stage': stage, 'failedChecks': block_failed})
            if report.get('applied'):
                break
            contact_after = float(report.get('maximumContactErrorMeters') or 0.)
            introduced = set(block_failed) - previous_failed
            if (introduced & {'anatomy', 'sourceArticulation', 'jointRange', 'rootContinuity'}
                    or contact_after >= 0.0005
                    or contact_after > previous_contact * 1.05 + 1e-9
                    or ({'contacts', 'bodySupport', 'supportAlignment'} & introduced)
                    or polish_worsened_jerk(report, previous_jerk)):
                solved = SimpleNamespace(x=previous_coordinates, nfev=solved.nfev, status=0)
                candidate, report = validate_solution(solved)
                block_failed = failed_check_names(report.get('checks'))
            # Continuity smooth often leaves shake; apply the cheap temporal
            # shake pass immediately so Stage-B/open-seam is reachable.
            if (not report.get('applied')
                    and ({'jointShake', 'relativeJointShake', 'settling'} & set(block_failed))
                    and not refinement.get('temporalShakeSmooth')
                    and (report.get('maximumContactErrorMeters') or 0.) < 0.0005):
                previous_coordinates = solved.x.copy()
                previous_failed = set(block_failed)
                previous_contact = float(report.get('maximumContactErrorMeters') or 0.)
                previous_jerk = report.get('jerkAfter')
                shaken = temporal_coordinate_smooth(
                    solved.x.reshape(count, rig.width), cyclic=cyclic, sigma=2.0)
                shaken = temporal_coordinate_smooth(shaken, cyclic=cyclic, sigma=2.5)
                if np.any(pinned):
                    contact_err = float(np.max(np.linalg.norm(
                        (rig.decode(shaken) - contact_targets)[pinned], axis=-1), initial=0.))
                    if contact_err >= 0.0005:
                        shaken = project_contact_plant_coordinates(
                            shaken, rig, pinned, contact_targets, max_nfev=15, freeze_root=True,
                            deadline=started + timeout_seconds)
                solved = SimpleNamespace(
                    x=shaken.ravel(), nfev=solved.nfev, status=getattr(solved, 'status', 1))
                candidate, report = validate_solution(solved)
                refinement['temporalShakeSmooth'] = True
                block_failed = failed_check_names(report.get('checks'))
                refinement['blocks'].append({
                    'costBefore': None, 'costAfter': None, 'method': 'temporal_shake_smooth',
                    'stage': 'C', 'failedChecks': block_failed})
                if report.get('applied'):
                    break
                contact_after = float(report.get('maximumContactErrorMeters') or 0.)
                introduced = set(block_failed) - previous_failed
                if (introduced & {'anatomy', 'sourceArticulation', 'jointRange', 'rootContinuity',
                                  'motionDiscontinuity'}
                        or contact_after >= 0.0005
                        or ({'contacts', 'bodySupport'} & introduced)
                        or polish_worsened_jerk(report, previous_jerk)):
                    solved = SimpleNamespace(x=previous_coordinates, nfev=solved.nfev, status=0)
                    candidate, report = validate_solution(solved)
            continue
        # Stage-A: hard root translation onto contact targets before soft LS.
        if (stage == 'A' and 'contacts' in failed_checks
                and not refinement.get('contactRootProjection')):
            previous_coordinates = solved.x.copy()
            previous_failed = set(failed_checks)
            previous_contact = float(report.get('maximumContactErrorMeters') or 0.)
            projected = project_contact_root_translation(
                solved.x.reshape(count, rig.width), rig, pinned, contact_targets).ravel()
            solved = SimpleNamespace(x=projected, nfev=solved.nfev, status=getattr(solved, 'status', 1))
            candidate, report = validate_solution(solved)
            refinement['contactRootProjection'] = True
            block_failed = failed_check_names(report.get('checks'))
            refinement['blocks'].append({
                'costBefore': None, 'costAfter': None, 'method': 'contact_root_projection',
                'stage': stage, 'failedChecks': block_failed,
                'contactBefore': previous_contact,
                'contactAfter': report.get('maximumContactErrorMeters')})
            if report.get('applied'):
                break
            new_contact = float(report.get('maximumContactErrorMeters') or 0.)
            if (new_contact > previous_contact * 1.01 + 1e-9
                    or ({'anatomy', 'sourceArticulation'} & set(block_failed)) - previous_failed):
                solved = SimpleNamespace(x=previous_coordinates, nfev=solved.nfev, status=0)
                candidate, report = validate_solution(solved)
            continue
        if (stage == 'A' and 'contacts' in failed_checks
                and refinement.get('contactRootProjection')
                and not refinement.get('contactPlantProjection')):
            previous_coordinates = solved.x.copy()
            previous_failed = set(failed_checks)
            previous_contact = float(report.get('maximumContactErrorMeters') or 0.)
            plant_budget = min(12., max(1., remaining - 1.))
            projected = project_contact_plant_coordinates(
                solved.x.reshape(count, rig.width), rig, pinned, contact_targets,
                max_nfev=25 if remaining >= 8. else 12,
                deadline=min(started + timeout_seconds, monotonic() + plant_budget)).ravel()
            solved = SimpleNamespace(x=projected, nfev=solved.nfev, status=getattr(solved, 'status', 1))
            candidate, report = validate_solution(solved)
            refinement['contactPlantProjection'] = True
            block_failed = failed_check_names(report.get('checks'))
            refinement['blocks'].append({
                'costBefore': None, 'costAfter': None, 'method': 'contact_plant_projection',
                'stage': stage, 'failedChecks': block_failed,
                'contactBefore': previous_contact,
                'contactAfter': report.get('maximumContactErrorMeters')})
            if report.get('applied'):
                break
            new_contact = float(report.get('maximumContactErrorMeters') or 0.)
            if (new_contact > previous_contact * 1.01 + 1e-9
                    or ({'anatomy', 'sourceArticulation'} & set(block_failed)) - previous_failed):
                solved = SimpleNamespace(x=previous_coordinates, nfev=solved.nfev, status=0)
                candidate, report = validate_solution(solved)
            continue
        # Stage-A: hard arm projection onto rigid_pair spacing once plants hold.
        if (stage == 'A' and 'equipment' in failed_checks
                and 'contacts' not in failed_checks
                and not refinement.get('rigidPairGripProjection')
                and equipment.get('handRelationship') == 'rigid_pair'
                and equipment.get('available')
                and (report.get('maximumContactErrorMeters') or 0.) < 0.0005):
            previous_coordinates = solved.x.copy()
            previous_failed = set(failed_checks)
            previous_contact = float(report.get('maximumContactErrorMeters') or 0.)
            grip_budget = min(10., max(1., remaining - 1.))
            projected = project_rigid_pair_grip_coordinates(
                solved.x.reshape(count, rig.width), rig, names, equipment,
                pinned=pinned, max_nfev=25, deadline=min(started + timeout_seconds, monotonic() + grip_budget))
            if np.any(pinned):
                projected = project_contact_root_translation(
                    projected, rig, pinned, contact_targets, passes=2, smooth_fps=fps)
                plant_deadline = monotonic() + min(
                    8., max(1., started + timeout_seconds - monotonic() - 0.5))
                if plant_deadline > monotonic():
                    projected = project_contact_plant_coordinates(
                        projected, rig, pinned, contact_targets, max_nfev=20,
                        deadline=min(started + timeout_seconds, plant_deadline))
            solved = SimpleNamespace(
                x=projected.ravel(), nfev=solved.nfev, status=getattr(solved, 'status', 1))
            candidate, report = validate_solution(solved)
            refinement['rigidPairGripProjection'] = True
            block_failed = failed_check_names(report.get('checks'))
            refinement['blocks'].append({
                'costBefore': None, 'costAfter': None, 'method': 'rigid_pair_grip_projection',
                'stage': stage, 'failedChecks': block_failed,
                'contactBefore': previous_contact,
                'contactAfter': report.get('maximumContactErrorMeters')})
            if report.get('applied'):
                break
            contact_after = float(report.get('maximumContactErrorMeters') or 0.)
            # Keep grip when plants stay under the gate; a small contact rise under
            # 0.5 mm is not worth discarding a rigid_pair fix.
            if (contact_after >= 0.0005
                    or ({'anatomy', 'sourceArticulation', 'contacts'} & set(block_failed)) - previous_failed):
                solved = SimpleNamespace(x=previous_coordinates, nfev=solved.nfev, status=0)
                candidate, report = validate_solution(solved)
            continue
        # After contacts clear, Stage-C soft LS often re-breaks them or times out.
        # Prefer one temporal smooth for shake before burning soft LS.
        if (stage == 'C'
                and ({'jointShake', 'relativeJointShake', 'settling'} & set(failed_checks))
                and not refinement.get('temporalShakeSmooth')
                and (report.get('maximumContactErrorMeters') or 0.) < 0.0005):
            previous_coordinates = solved.x.copy()
            previous_failed = set(failed_checks)
            previous_contact = float(report.get('maximumContactErrorMeters') or 0.)
            previous_jerk = report.get('jerkAfter')
            smoothed = temporal_coordinate_smooth(
                solved.x.reshape(count, rig.width), cyclic=cyclic).ravel()
            solved = SimpleNamespace(x=smoothed, nfev=solved.nfev, status=getattr(solved, 'status', 1))
            candidate, report = validate_solution(solved)
            refinement['temporalShakeSmooth'] = True
            block_failed = failed_check_names(report.get('checks'))
            refinement['blocks'].append({
                'costBefore': None, 'costAfter': None, 'method': 'temporal_shake_smooth',
                'stage': stage, 'failedChecks': block_failed})
            if report.get('applied'):
                break
            contact_after = float(report.get('maximumContactErrorMeters') or 0.)
            if (contact_after >= 0.0005
                    or contact_after > previous_contact * 1.05 + 1e-9
                    or ({'anatomy', 'sourceArticulation', 'contacts'} & set(block_failed)) - previous_failed
                    or polish_worsened_jerk(report, previous_jerk)):
                solved = SimpleNamespace(x=previous_coordinates, nfev=solved.nfev, status=0)
                candidate, report = validate_solution(solved)
            continue
        # Stage-B: cheap nudge, then hard free-DOF wrap projection. Soft LS does
        # not close near-miss seams under support — do not burn polish on it.
        if (stage == 'B' and cyclic and 'loopSeam' in failed_checks
                and set(failed_checks) <= POLISH_STAGE_B
                and (report.get('maximumContactErrorMeters') or 0.) < 0.0005
                and (report.get('maximumArticulationChangeDegrees') or 0.) < 15.):
            stage_b_start = solved.x.copy()
            stage_b_ratios = seam_over_limit_ratios(report.get('playback') or {})
            ratios = stage_b_ratios
            large_seam = bool(ratios) and max(ratios) > SEAM_NEAR_MISS_CYCLE_SKIP_MULTIPLE
            if not refinement.get('seamBoundaryNudge'):
                previous_coordinates = solved.x.copy()
                previous_ratios = seam_over_limit_ratios(report.get('playback') or {})
                previous_score = max(previous_ratios) if previous_ratios else None
                closed = close_loop_seam_coordinates(
                    solved.x.reshape(count, rig.width), rig, pinned,
                    scale=scale, fps=fps).ravel()
                solved = SimpleNamespace(x=closed, nfev=solved.nfev, status=getattr(solved, 'status', 1))
                candidate, report = validate_solution(solved)
                refinement['seamBoundaryNudge'] = True
                refinement['blocks'].append({
                    'costBefore': None, 'costAfter': None, 'method': 'seam_boundary_nudge', 'stage': stage,
                    'failedChecks': failed_check_names(report.get('checks'))})
                if report.get('applied'):
                    break
                new_ratios = seam_over_limit_ratios(report.get('playback') or {})
                new_score = max(new_ratios) if new_ratios else None
                nudge_failed = failed_check_names(report.get('checks'))
                if ((previous_score is not None and new_score is not None
                     and float(new_score) > float(previous_score) * 1.01)
                        or (nudge_failed and not set(nudge_failed) <= POLISH_STAGE_B)):
                    solved = SimpleNamespace(x=previous_coordinates, nfev=solved.nfev, status=0)
                    candidate, report = validate_solution(solved)
            if (not refinement.get('seamHardProjection')
                    or refinement.pop('seamProjectionRetryPending', False)):
                if not refinement.get('seamHardProjection'):
                    # Bound admission of new solves across the seam episode;
                    # time spent validating also consumes this allowance.
                    # A fixed attempt count can discard a converging solve even
                    # when its next short step fits the original allowance.
                    seam_repair_deadline = min(started + timeout_seconds, monotonic() + 30.)
                previous_coordinates = solved.x.copy()
                previous_ratios = seam_over_limit_ratios(report.get('playback') or {})
                previous_score = max(previous_ratios) if previous_ratios else None
                projected = project_loop_seam_coordinates(
                    solved.x.reshape(count, rig.width), rig, pinned,
                    scale=scale, fps=fps, settling_weights=hold_weights,
                    settling_limit=settling_limit,
                    # Nudge validation can consume the polish reserve. Give
                    # each bounded solve its own window, still inside
                    # the candidate's outer deadline.
                    deadline=min(seam_repair_deadline, monotonic() + 10.),
                    max_nfev=80).ravel()
                solved = SimpleNamespace(
                    x=projected, nfev=solved.nfev, status=getattr(solved, 'status', 1))
                candidate, report = validate_solution(solved)
                refinement['seamHardProjection'] = True
                refinement['seamHardProjectionAttempts'] = refinement.get('seamHardProjectionAttempts', 0) + 1
                refinement['blocks'].append({
                    'costBefore': None, 'costAfter': None, 'method': 'seam_hard_projection',
                    'stage': stage, 'failedChecks': failed_check_names(report.get('checks'))})
                if report.get('applied'):
                    break
                new_ratios = seam_over_limit_ratios(report.get('playback') or {})
                new_score = max(new_ratios) if new_ratios else None
                block_failed = failed_check_names(report.get('checks'))
                if (block_failed and set(block_failed) <= POLISH_STAGE_C
                        and (report.get('checks') or {}).get('loopSeam') is True
                        and (report.get('playback') or {}).get('passed')
                        and monotonic() < started + timeout_seconds):
                    # A closed, body-valid seam with temporal leftovers belongs
                    # to Stage C. Rolling it back here prevents that stage from
                    # ever seeing the repaired loop; acceptance still requires
                    # every temporal and seam check to pass together.
                    refinement['seamClosedNeedsTemporalPolish'] = True
                    polish_until = min(started + timeout_seconds,
                                       max(polish_until, monotonic() + 16.))
                    continue
                # Revert if wrap score worsened or body checks regressed.
                if ((previous_score is not None and new_score is not None
                     and float(new_score) > float(previous_score) * 1.01)
                        or (block_failed and not set(block_failed) <= POLISH_STAGE_B)):
                    solved = SimpleNamespace(x=previous_coordinates, nfev=solved.nfev, status=0)
                    candidate, report = validate_solution(solved)
                    new_ratios = seam_over_limit_ratios(report.get('playback') or {})
                    block_failed = failed_check_names(report.get('checks'))
                if not report.get('applied') and (
                        block_failed and not set(block_failed) <= POLISH_STAGE_B):
                    solved = SimpleNamespace(x=stage_b_start, nfev=solved.nfev, status=0)
                    candidate, report = validate_solution(solved)
                    new_ratios = seam_over_limit_ratios(report.get('playback') or {})
                # Continue only with measured progress and clear body checks,
                # inside the original episode and candidate deadlines.
                if (block_failed and set(block_failed) <= POLISH_STAGE_B
                        and previous_score is not None and new_ratios
                        and max(new_ratios) < previous_score * .8
                        and seam_repair_deadline - monotonic() >= 5.):
                    refinement['seamProjectionRetryPending'] = True
                    polish_until = min(seam_repair_deadline,
                                       max(polish_until, monotonic() + 12.))
                    continue
                ratios_now = new_ratios or previous_ratios or stage_b_ratios or []
                if ratios_now and max(ratios_now) > SEAM_NEAR_MISS_CYCLE_SKIP_MULTIPLE:
                    refinement['stopReason'] = 'seam_excess_needs_different_cycle'
                    report['termination'] = 'seam_excess_needs_different_cycle'
                else:
                    refinement['stopReason'] = 'seam_playback_only'
                    report['termination'] = 'seam_playback_only'
                break
            # Already projected once; do not soft-LS Stage-B seam leftovers.
            refinement['stopReason'] = 'seam_playback_only'
            report['termination'] = 'seam_playback_only'
            break
        if stage == 'B' and cyclic and 'loopSeam' in failed_checks and set(failed_checks) <= POLISH_STAGE_B:
            # Seam-only Stage-B must not fall through into soft LS.
            continue
        if report.get('skippedSoftSolve'):
            leftover = set(failed_checks)
            play_ok = bool((report.get('playback') or {}).get('passed'))
            # Geometry-ready skips must not soft-LS plant-only clips, but after a
            # cleared playback path free-DOF temporal can still clear Stage-C.
            if (play_ok and leftover <= POLISH_STAGE_C
                    and ({'jerk', 'jointShake', 'relativeJointShake', 'settling'} & leftover)
                    and not refinement.get('temporalFreeStageC')):
                previous_coordinates = solved.x.copy()
                previous_failed = set(failed_checks)
                previous_jerk = report.get('jerkAfter')
                previous_play = float(
                    (report.get('playback') or {}).get('maximumContactErrorMeters') or 0.)
                previous_initial = rig.initial.copy()
                previous_offsets = rig.offsets.copy()
                free_sigma = 1.75 if refinement.get('temporalPathStrong') else 1.25
                smoothed = polish_free_temporal_preserving_anatomy(
                    solved.x.reshape(count, rig.width), rig, pinned, contact_targets,
                    cyclic=cyclic, sigma=free_sigma,
                    deadline=min(started + timeout_seconds, monotonic() + min(16., max(5., remaining))),
                    floor=floor, fps=fps, spike_reference=spike_reference)
                solved = SimpleNamespace(
                    x=smoothed.ravel(), nfev=solved.nfev, status=getattr(solved, 'status', 1))
                candidate, report = validate_solution(solved, project_playback_plants=False)
                refinement['temporalFreeStageC'] = True
                block_failed = failed_check_names(report.get('checks'))
                refinement['blocks'].append({
                    'costBefore': None, 'costAfter': None, 'method': 'temporal_free_stage_c',
                    'stage': 'C', 'failedChecks': block_failed})
                if report.get('applied'):
                    break
                contact_after = float(report.get('maximumContactErrorMeters') or 0.)
                play_after = float(
                    (report.get('playback') or {}).get('maximumContactErrorMeters') or 0.)
                nested_after = _playback_nested_failures(report.get('playback'))
                if (contact_after >= 0.0005
                        or play_after >= PLAYBACK_CONTACT_LIMIT_METERS
                        or play_after > previous_play * 1.05 + 1e-9
                        or not (report.get('playback') or {}).get('passed')
                        or 'velocity' in nested_after
                        or ({'anatomy', 'sourceArticulation', 'contacts'} & set(block_failed))
                        - previous_failed
                        or polish_worsened_jerk(report, previous_jerk)):
                    rig.initial[:] = previous_initial
                    rig.offsets[:] = previous_offsets
                    solved = SimpleNamespace(x=previous_coordinates, nfev=solved.nfev, status=0)
                    candidate, report = validate_solution(solved, project_playback_plants=False)
                continue
            refinement['stopReason'] = 'hard_polish_exhausted'
            report['termination'] = 'hard_polish_exhausted'
            break
        initial_evaluations = solved.nfev or 0
        previous_coordinates = solved.x.copy()
        previous_failed = set(failed_checks)
        previous_contact = float(report.get('maximumContactErrorMeters') or 0.)
        previous_jerk = report.get('jerkAfter')
        contacts_were_clear = previous_contact < 0.0005 and 'contacts' not in previous_failed
        cost_before = cost_after = None
        stalled = False
        if stage == 'A':
            # Only boost the terms that actually failed; raising contacts for an
            # equipment-only miss starves the grip residual.
            if 'contacts' in failed_checks:
                contact_polish_weight = STAGE_A_CONTACT_POLISH_WEIGHT
            if 'equipment' in failed_checks:
                equipment_polish_weight = STAGE_A_EQUIPMENT_POLISH_WEIGHT
        elif contacts_were_clear:
            # Protect a hard-won contact clearance while Stage-C soft LS works.
            contact_polish_weight = max(STAGE_A_CONTACT_POLISH_WEIGHT * 0.5, 2.)
        try:
            errors = residual(solved.x)
            cost_before = float(errors@errors)
            solved = trajectory_solver(residual, solved.x, pattern, polish_evaluations)
            solved.nfev = (solved.nfev or 0) + initial_evaluations
            errors = residual(solved.x)
            cost_after = float(errors@errors)
            stalled = cost_before-cost_after <= max(1e-12, abs(cost_before)*1e-6)
        except TimeoutError:
            report['optimizerTermination'] = 'time_budget'
            # Prefer the block start over a partial best_coordinates that often
            # improves soft cost while re-breaking planted contacts.
            solved = SimpleNamespace(x=previous_coordinates, nfev=None, status=0)
            hard_stage_c_tried = any(
                refinement.get(key) for key in (
                    'temporalShakeSmooth', 'temporalJerkSmooth',
                    'rootContinuitySmooth', 'motionDiscontinuitySmooth'))
            if stage == 'A' and refinement.get('contactRootProjection'):
                stalled = True
            elif stage == 'C' and hard_stage_c_tried:
                # Hard Stage-C ops already ran; another timed-out soft LS will
                # not clear settling/shake under contact protection.
                stalled = True
            else:
                stalled = max(0., started + timeout_seconds - monotonic()) < 3.
        finally:
            seam_polish_weight = 1.
            contact_polish_weight = 1.
            equipment_polish_weight = 1.
        if fit_session is not None and best_coordinates is not None:
            fit_session.trajectories[trajectory_key] = best_coordinates.tolist()
        candidate, report = validate_solution(solved)
        block_failed = failed_check_names(report.get('checks'))
        contact_after = float(report.get('maximumContactErrorMeters') or 0.)
        # Soft polish must not re-break contacts, invent anatomy/articulation, or
        # raise jerk when acceptance did not improve (common Stage-C trap).
        acceptance_improved = bool(previous_failed) and set(block_failed) < previous_failed
        if ((stage == 'A'
                and ({'anatomy', 'sourceArticulation'} & set(block_failed))
                and not ({'anatomy', 'sourceArticulation'} & previous_failed))
                or (contacts_were_clear and (
                    'contacts' in block_failed or contact_after >= 0.0005
                    or contact_after > previous_contact * 1.05 + 1e-9))
                or (stage == 'C' and polish_worsened_jerk(report, previous_jerk)
                    and not acceptance_improved)):
            solved = SimpleNamespace(x=previous_coordinates, nfev=solved.nfev, status=0)
            candidate, report = validate_solution(solved)
            block_failed = failed_check_names(report.get('checks'))
            stalled = True
        refinement['blocks'].append({'costBefore': cost_before, 'costAfter': cost_after,
            'failedChecks': block_failed, 'stage': stage,
            **({'method': 'stage_a_contact_boost'} if stage == 'A' else {})})
        hard_blocks = sum(
            1 for block in refinement['blocks']
            if 'trajectoryFit' in (block.get('failedChecks') or [])
            and 'rootTravel' in (block.get('failedChecks') or [])
        )
        remaining = max(0., started + timeout_seconds - monotonic())
        if hard_trajectory_and_root_failure(report.get('checks')) and (
                stalled or hard_blocks >= 2 or remaining < 0.2 * timeout_seconds):
            refinement['stopReason'] = 'hard_trajectory_root_failure'
            report['termination'] = 'hard_trajectory_root_failure'
            break
        if acceptance_stalled_after_refinement(refinement):
            # Same-stage near-misses can keep the failed-check set while cost moves;
            # only stop hard when the stage itself is not a polishable near-miss.
            if not polishable_near_miss(block_failed):
                refinement['stopReason'] = 'acceptance_stalled'
                report['termination'] = 'acceptance_stalled'
                break
        if stalled and not report.get('applied'):
            if set(block_failed) <= POLISH_STAGE_B and 'loopSeam' in block_failed:
                refinement['stopReason'] = 'seam_playback_only'
                report['termination'] = 'seam_playback_only'
                break
            if polishable_near_miss(block_failed) and contacts_were_clear and 'contacts' not in block_failed:
                # Soft LS could not improve temporal terms without breaking
                # contacts; keep the cleared-contact state and stop burning.
                refinement['stopReason'] = 'polish_stalled'
                report['termination'] = 'polish_stalled'
                break
            if polishable_near_miss(block_failed):
                refinement['stopReason'] = 'polish_stalled'
                report['termination'] = 'polish_stalled'
            else:
                refinement['stopReason'] = 'objective_stalled'
                report['termination'] = 'objective_stalled'
            break
    # Map evidence stops to decisive outcomes; do not leave fit_timeout when we
    # already know acceptance cannot move.
    stop = (report.get('boundedRefinement') or {}).get('stopReason') or report.get('termination')
    if (not report.get('applied') and stop in EVIDENCE_TERMINATIONS
            and report.get('checks')):
        report['termination'] = stop
        failed = set(failed_check_names(report.get('checks')))
        playback = report.get('playback') or {}
        if (cyclic and failed <= {'loopSeam', 'playback'}
                and (report.get('checks') or {}).get('loopSeam') is False
                and not playback.get('seamContinuous', True)
                and candidate is not None
                and loop_disabled_playback_passed(candidate)):
            candidate['loop'] = {
                **(candidate.get('loop') or {}),
                'enabled': True,
                'transition': 'requires_cycle_repair',
                'restartFadeMillis': 0,
            }
            candidate.pop('sequenceStabilization', None)
            report['outputPoseDigest'] = pose_digest(candidate)
            report['loopSeamOpen'] = True
            report['seamStepExcessMeters'] = playback.get('seamStepExcessMeters')
            report['seamVelocityMismatchMetersPerSecond'] = playback.get(
                'seamVelocityMismatchMetersPerSecond')
            report.update(applied=True, reason='validated_controlled_motion_open_seam')
            return candidate, report
        if report.get('reason') in {
                None, 'fit_timeout', 'fit_evaluation_limit', 'fit_validation_failed'}:
            if failed <= {'loopSeam', 'playback'}:
                if (report.get('checks') or {}).get('loopSeam') is False:
                    report['reason'] = 'loop_requires_cycle_repair'
                else:
                    report['reason'] = 'playback_validation_failed'
            else:
                report['reason'] = 'fit_validation_failed'
        return (candidate if report.get('applied') else payload), report
    # Use leftover outer budget for another full polish block when acceptance is
    # still moving, or a staged near-miss remains.
    remaining = max(0., started + timeout_seconds - monotonic())
    refinement = report.get('boundedRefinement') or {}
    failed_now = failed_check_names(report.get('checks'))
    polishable_only = polishable_near_miss(failed_now)
    if (allow_refinement and not report.get('applied')
            and remaining >= 5.
            and stop not in EVIDENCE_TERMINATIONS
            and not report.get('skippedSoftSolve')
            and (
                report.get('optimizerTermination') != 'time_budget'
                or polishable_only
            )
            and (
                (report.get('reason') == 'fit_evaluation_limit'
                 and refinement_improved_acceptance(refinement))
                or polishable_only
            )
            and refinement.get('stopReason') not in EVIDENCE_TERMINATIONS
            and not fit_should_yield_for_priority()):
        continuation = {
            'remainingSeconds': round(remaining, 3),
            'extraEvaluations': int(max_evaluations),
            'stage': polish_stage_for_failures(failed_now),
        }
        previous_coordinates = solved.x.copy()
        initial_evaluations = solved.nfev or 0
        if report.get('optimizerTermination') in {'solve_phase_budget', 'time_budget'}:
            optimization_deadline = started + timeout_seconds - min(5., max(0., timeout_seconds) * .05)
            report['optimizerTermination'] = 'evaluation_limit'
        try:
            solved = trajectory_solver(residual, solved.x, pattern, max_evaluations)
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
    elif (not report.get('applied')
          and report.get('reason') in {'fit_evaluation_limit', 'fit_timeout', 'fit_validation_failed'}
          and report.get('checks')
          and (
              (report.get('boundedRefinement') or {}).get('stopReason') in EVIDENCE_TERMINATIONS
              or report.get('termination') in EVIDENCE_TERMINATIONS
              or (report.get('optimizerTermination') in {'time_budget', 'solve_phase_budget', 'objective_stalled'}
                  and not refinement_improved_acceptance(report.get('boundedRefinement') or {})))):
        report['reason'] = 'fit_validation_failed'
        if report.get('optimizerTermination') == 'objective_stalled':
            report['termination'] = 'objective_stalled'
    # Final safety: completed checks must never leave an incomplete fit_timeout
    # label just because the soft LS burned its watchdog.
    if (not report.get('applied') and report.get('checks')
            and report.get('reason') in {'fit_timeout', 'fit_evaluation_limit'}):
        report['reason'] = 'fit_validation_failed'
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
