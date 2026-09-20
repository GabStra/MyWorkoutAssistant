"""Shared, explicitly observed support constraints for fitting and acceptance.

Support planes are geometry evidence, not exercise-name templates. Unknown
contacts must not be promoted to confirmed contacts by the motion solver.
"""
from __future__ import annotations

import numpy as np

POLICY_VERSION = 3
TOLERANCE_METERS = .005


def declare_support_requirements(payload, contract):
    """Require evidence for a supported reference torso, never invent its plane."""
    from .body_support_observation import requires_body_support
    if requires_body_support(contract):
        if not isinstance(payload.get('sourceFootSupportEvidence'), dict):
            payload['sourceFootSupportEvidence'] = {}
        evidence = payload['sourceFootSupportEvidence']
        evidence.setdefault('bodySupport', {'required': True, 'status': 'unknown',
            'reason': 'supported_reference_body_requires_observed_surface_geometry'})


def support_evidence(payload):
    return (payload.get('sourceFootSupportEvidence') or {}).get('bodySupport', {})


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


def geometry_errors(points, names, evidence):
    """Plane equality and one-sided chain clearance in the observed normal."""
    errors = []
    for contact in evidence.get('soleContacts', []):
        _, ankle, toe = (points[:, names.index(n)] for n in contact['joints'])
        normal = np.asarray(contact['normal'], dtype=float)
        normal /= np.linalg.norm(normal)
        forward = toe - ankle
        # Pitch belongs to joint geometry. Shoe roll is an independent axial
        # orientation; tying it to the shin would also pin valid knee motion.
        errors.append((forward @ normal)[:, None])
    for group in evidence.get('coplanarGroups', []):
        indices = [names.index(n) for n in group['joints']]
        normal = np.asarray(group['normal'], dtype=float)
        normal /= np.linalg.norm(normal)
        heights = points[:, indices] @ normal
        errors.append(heights[:, 1:] - heights[:, :1])
        if 'planeOffsetMeters' in group:
            errors.append(heights[:, :1]-float(group['planeOffsetMeters']))
    for chain in evidence.get('nonPenetrationChains', []):
        normal = np.asarray(chain['normal'], dtype=float)
        normal /= np.linalg.norm(normal)
        plane = chain_support_plane(chain, evidence)
        if plane is not None:
            # Endpoints are also subject to the observed support: otherwise a
            # lowered neck can redefine a sloping chord that legitimizes sag.
            anchor = points[:, names.index(plane['joints'][0])]
            for name in dict.fromkeys(chain['joints']+chain['endpoints']):
                errors.append(np.minimum((points[:, names.index(name)]-anchor) @ normal, 0.)[:, None])
            continue
        start, end = (points[:, names.index(n)] for n in chain['endpoints'])
        direction = end - start
        denominator = np.maximum(np.sum(direction * direction, axis=-1), 1e-12)
        for name in chain['joints']:
            point = points[:, names.index(name)]
            ratio = np.clip(np.sum((point-start)*direction, axis=-1)/denominator, 0., 1.)
            chord = start + ratio[:, None]*direction
            errors.append(np.minimum(np.sum((point-chord)*normal, axis=-1), 0.)[:, None])
    return np.concatenate(errors, axis=1) if errors else np.empty((len(points), 0))


def validate_support_geometry(payload, points=None, names=None):
    evidence = support_evidence(payload)
    if not evidence.get('required'):
        return {'required': False, 'passed': True, 'policyVersion': POLICY_VERSION}
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
    indices = [names.index(n) for n in evidence.get('stationaryJoints', [])]
    drift = float(np.max(np.linalg.norm(np.ptp(points[:, indices], axis=0), axis=-1), initial=0.))
    geometry = float(np.max(np.abs(geometry_errors(points, names, evidence)), initial=0.))
    reasons = []
    if drift > TOLERANCE_METERS:
        reasons.append('supported_body_moves')
    if geometry > TOLERANCE_METERS:
        reasons.append('support_surface_geometry_mismatch')
    return {'required': True, 'passed': not reasons, 'policyVersion': POLICY_VERSION,
            'maximumStationaryJointRangeMeters': drift,
            'maximumSurfaceErrorMeters': geometry,
            'toleranceMeters': TOLERANCE_METERS, 'rejectionReasons': reasons}


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


def validate_supported_shoe_orientation(payload):
    """Check exported shoe-up against the surface, independently of knee pose."""
    evidence = support_evidence(payload)
    contacts = evidence.get('soleContacts', [])
    if not contacts:
        return {'required': False, 'passed': True}
    if evidence.get('status') != 'confirmed' or not evidence_is_complete(evidence, payload.get('jointNames', [])):
        return {'required': True, 'passed': False, 'reason': 'sole_orientation_evidence_unresolved'}
    maximum = 0.
    try:
        if not payload.get('frames'):
            raise ValueError('Missing frames')
        for contact in contacts:
            _, ankle, toe = contact['joints']
            normal = np.asarray(contact['normal'], dtype=float)
            normal /= np.linalg.norm(normal)
            for frame in payload['frames']:
                forward = np.asarray(frame['joints'][toe])-frame['joints'][ankle]
                length = np.linalg.norm(forward)
                if length < 1e-8:
                    raise ValueError('Degenerate foot')
                forward /= length
                side = np.asarray(frame['boneSides'][f'{ankle}->{toe}'], dtype=float)
                side -= forward*np.dot(side, forward)
                if np.linalg.norm(side) < 1e-8:
                    raise ValueError('Degenerate shoe side')
                side /= np.linalg.norm(side)
                up = np.cross(side, forward)
                error = np.linalg.norm(up-normal)*length
                if not np.isfinite(error):
                    raise ValueError('Nonfinite shoe orientation')
                maximum = max(maximum, float(error))
    except (KeyError, TypeError, ValueError):
        return {'required': True, 'passed': False, 'reason': 'sole_orientation_unavailable'}
    return {'required': True, 'passed': maximum <= TOLERANCE_METERS,
            'maximumOrientationErrorMeters': maximum}


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
        valid = (reference.shape == (len(frames), len(names), 3)
                 and np.isfinite(reference).all()
                 and not np.any(repair_residuals(reference, names)[0] > 1e-6)
                 and validate_support_geometry(payload, reference, names)['passed']
                 and validate_payload_alignment(payload, reference)['passed'])
    except (TypeError, ValueError, KeyError):
        valid = False
    if not valid:
        return None, 'support_corrected_reference_invalid'
    return reference, None


def calibrate_support_pose(rig, points, evidence, alignment_reference=None):
    """Find one feasible fixed-rig support pose, retaining bone lengths."""
    from scipy.optimize import least_squares
    from .physical_validation import anatomical_structure_residuals, collision_clearances, body_scale
    from .controlled_motion import ANATOMY_FIT_MARGIN

    if evidence.get('status') != 'confirmed' or not evidence_is_complete(evidence, rig.names):
        return None, {'passed': False, 'reason': 'supported_body_evidence_unresolved'}
    indices = [rig.names.index(n) for n in evidence.get('stationaryJoints', [])]
    target = np.median(points, axis=0)
    closest = int(np.argmin(np.sum((points[:, indices]-target[indices])**2, axis=(1, 2))))
    initial = rig.initial[closest].copy()
    scale = body_scale(points, rig.names)
    from .support_alignment import alignment_features, alignment_constraint_errors
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
                     1000.*np.minimum(collision_clearances(candidate, rig.names, scale)[0]-.003*scale, 0.).ravel(),
                     .001*(values-initial)]

    solved = least_squares(residual, initial, max_nfev=100)
    pose = rig.decode(solved.x[None, :])[0]
    error = float(np.max(np.abs(geometry_errors(pose[None], rig.names, evidence)), initial=0.))
    return (pose if error < TOLERANCE_METERS*.5 else None), {
        'passed': error < TOLERANCE_METERS*.5, 'surfaceErrorMeters': error,
        'evaluations': solved.nfev, 'coordinates': solved.x.tolist(),
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
                                *, pinned=None, contact_targets=None, equipment=None, max_evaluations=40):
    """Project observed articulation onto contacts without locking ancestors."""
    from time import monotonic
    from scipy.sparse import eye, kron, csr_matrix, vstack
    from .controlled_motion import (joint_dependencies, solve_trajectory, anatomical_structure_dependencies,
                                    ANATOMY_FIT_MARGIN)
    from .physical_validation import SOCKET_ALIGNMENT_MAX_LATERAL_RATIO
    from .physical_validation import anatomical_structure_residuals, collision_clearances, collision_specs, body_scale

    stationary = evidence['stationaryJoints']
    indices = [rig.names.index(n) for n in stationary]
    source_coordinates = rig.initial.copy()
    source_points = rig.decode(source_coordinates)
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

    def residual(values):
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
            1000.*np.minimum(collision_clearances(candidate, rig.names, scale)[0]-.003*scale, 0.),
            .0001*(coordinates-source_coordinates),
            # Acceptance rejects stationary ptp > 5 mm. Soft-penalize wander about
            # the median plant so under-iterated projections do not leave 7–17 mm drift.
            (400. * (candidate[:, indices] - np.median(candidate[:, indices], axis=0, keepdims=True))
             ).reshape(count, -1),
        ], axis=1).ravel()
        # Independent pose projections can choose different redundant spine
        # configurations in adjacent frames. Regularize the correction itself
        # before making it the reference for the final trajectory fit.
        correction_acceleration = np.diff(candidate-desired, n=2, axis=0)*(fps*.15)**2
        return np.r_[frame_errors, correction_acceleration.ravel()]

    contact_rows = [j*3+k for j in contact_indices for k in range(3)]
    grip_rows = (np.asarray([joint_dependencies(rig, equipment['endpointPair'])])
                 if equipment.get('handRelationship') == 'rigid_pair' and equipment.get('available')
                 else np.empty((0, rig.width)))
    collision_rows = [joint_dependencies(rig, [*a, *b]) for _, a, b, _, _ in collision_specs(rig.names)]
    direction_rows = np.repeat(np.asarray([joint_dependencies(rig, [rig.names[j], rig.names[parent]])
                                         for j, parent in zip(direction_children, direction_parents)]), 3, axis=0)
    plant_rows = np.repeat(
        np.asarray([joint_dependencies(rig, [rig.names[j]]) for j in indices]), 3, axis=0)
    frame_pattern = np.vstack([rig.dependencies, direction_rows, rig.dependencies[contact_rows], grip_rows,
        geometry_dependencies(rig, evidence), alignment_dependencies(rig, evidence), anatomical_structure_dependencies(rig, original, rig.names),
        collision_rows, np.eye(rig.width), plant_rows])
    pattern = kron(eye(count), csr_matrix(frame_pattern), format='csr')
    d2 = csr_matrix(abs(np.diff(np.eye(count), n=2, axis=0)))
    pattern = vstack([pattern, kron(d2, csr_matrix(rig.dependencies))], format='csr')
    if pattern.shape != (residual(rig.initial.ravel()).size, rig.initial.size):
        raise ValueError('Support projection residual and dependency shapes differ')
    solved = solve_trajectory(residual, rig.initial.ravel(), pattern, max(1, int(max_evaluations)))
    calibration['projectionEvaluations'] = solved.nfev
    calibration['projectionEvaluationBudget'] = int(max_evaluations)
    rig.initial[:] = solved.x.reshape(count, rig.width)
    rig.project_neck_attachment(maximum_lateral_ratio=SOCKET_ALIGNMENT_MAX_LATERAL_RATIO-ANATOMY_FIT_MARGIN)
    return rig.decode(rig.initial)
