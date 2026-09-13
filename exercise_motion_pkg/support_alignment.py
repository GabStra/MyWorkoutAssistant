"""Preserve supported torso structure independently of placement and sag repair."""
import numpy as np

ANCHORS = ('pelvis', 'left_hip', 'right_hip', 'left_shoulder', 'right_shoulder')
SPINE = ('spine1', 'spine2', 'spine3')
ANGLE_SCALE_METERS = .2
LIMITS = np.array([np.deg2rad(3.)*ANGLE_SCALE_METERS, .005, .005, .005,
                   np.deg2rad(1.)*ANGLE_SCALE_METERS, .001])


def support_normal(evidence, names):
    if not evidence.get('required') or evidence.get('status') != 'confirmed':
        return None
    if not set(ANCHORS + SPINE).issubset(names):
        return None
    for group in evidence.get('coplanarGroups', []):
        if {'pelvis', 'left_shoulder', 'right_shoulder'}.issubset(group.get('joints', [])):
            normal = np.asarray(group['normal'], dtype=float)
            return normal / np.linalg.norm(normal)
    return None


def alignment_features(points, names, evidence):
    normal = support_normal(evidence, names)
    if normal is None:
        return np.empty((len(points), 0))
    hip_left, hip_right = (points[:, names.index(n)] for n in ('left_hip', 'right_hip'))
    hips = (hip_left + hip_right)*.5
    shoulders = (points[:, names.index('left_shoulder')] + points[:, names.index('right_shoulder')])*.5
    longitudinal = shoulders - hips
    longitudinal -= (longitudinal @ normal)[:, None]*normal
    longitudinal /= np.maximum(np.linalg.norm(longitudinal, axis=1, keepdims=True), 1e-12)
    lateral = np.cross(normal, longitudinal)
    hip_axis = hip_right-hip_left
    heading = np.arctan2(np.sum(hip_axis*longitudinal, axis=1), np.sum(hip_axis*lateral, axis=1))
    offsets = [np.sum((points[:, names.index(n)]-hips)*lateral, axis=1) for n in SPINE]
    roll = np.arctan2(hip_axis @ normal,
                     np.linalg.norm(hip_axis-(hip_axis @ normal)[:, None]*normal, axis=1))
    pelvis_offset = np.sum((points[:, names.index('pelvis')]-hips)*lateral, axis=1)
    return np.column_stack([heading*ANGLE_SCALE_METERS, *offsets,
                            roll*ANGLE_SCALE_METERS, pelvis_offset])


def alignment_errors(points, reference_features, names, evidence, *, bounded=False):
    current = alignment_features(points, names, evidence)
    if not current.shape[1]:
        return current
    delta = current-reference_features
    # Stationary supported anchors establish one rest orientation. Preserving
    # each noisy reconstruction roll would turn jitter into a fit requirement.
    stationary = set(evidence.get('stationaryJoints', []))
    if {'pelvis', 'left_shoulder', 'right_shoulder'}.issubset(stationary):
        delta[:, 4] = current[:, 4]-np.median(reference_features[:, 4])
    angle = delta[:, 0]/ANGLE_SCALE_METERS
    delta[:, 0] = np.arctan2(np.sin(angle), np.cos(angle))*ANGLE_SCALE_METERS
    if bounded:
        delta = np.sign(delta)*np.maximum(abs(delta)-LIMITS*.6, 0.)
    return delta


def alignment_dependencies(rig, evidence):
    if support_normal(evidence, rig.names) is None:
        return np.empty((0, rig.width))
    from .controlled_motion import joint_dependencies
    return np.array([joint_dependencies(rig, ANCHORS),
                     *(joint_dependencies(rig, ANCHORS+(n,)) for n in SPINE),
                     joint_dependencies(rig, ('left_hip', 'right_hip')),
                     joint_dependencies(rig, ANCHORS)])


def alignment_constraint_errors(points, reference_features, names, evidence):
    """Penalize equal fractions of the allowed error equally across features."""
    errors = alignment_errors(points, reference_features, names, evidence, bounded=True)
    return errors / LIMITS if errors.shape[1] else errors


def validate_alignment(points, original, names, evidence):
    if support_normal(evidence, names) is None:
        return {'required': False, 'passed': True}
    if original is None or original.shape != points.shape or not np.isfinite(original).all():
        return {'required': True, 'passed': False, 'reason': 'support_alignment_reference_unavailable'}
    errors = alignment_errors(points, alignment_features(original, names, evidence), names, evidence)
    maximum = np.max(abs(errors), axis=0)
    passed = bool(np.isfinite(maximum).all() and np.all(maximum <= LIMITS))
    return {'required': True, 'passed': passed,
            'maximumIntroducedPelvisHeadingDegrees': float(np.rad2deg(maximum[0]/ANGLE_SCALE_METERS)),
            'maximumIntroducedSpineLateralOffsetMeters': float(max(maximum[1:4])),
            'maximumIntroducedPelvisRollDegrees': float(np.rad2deg(maximum[4]/ANGLE_SCALE_METERS)),
            'maximumIntroducedPelvisLateralOffsetMeters': float(maximum[5]),
            'reason': None if passed else 'support_correction_introduced_torso_deformation'}


def payload_alignment_reference(payload):
    try:
        result = np.asarray([[f['supportAlignmentReferenceJoints'][n] for n in payload['jointNames']]
                             for f in payload['frames']], dtype=float)
        if result.shape == (len(payload['frames']), len(payload['jointNames']), 3):
            return result
    except (KeyError, ValueError, TypeError):
        pass
    return None


def validate_payload_alignment(payload, points=None, cursors=None):
    from .support_geometry import support_evidence
    names, evidence = payload.get('jointNames', []), support_evidence(payload)
    if support_normal(evidence, names) is None:
        return {'required': False, 'passed': True}
    original = payload_alignment_reference(payload)
    if points is None:
        points = np.asarray([[f['joints'][n] for n in names] for f in payload['frames']])
    if cursors is not None and original is not None:
        first = np.floor(cursors).astype(int)
        last = (first+1)%len(original)
        alpha = (cursors-first)[:, None, None]
        original = original[first]*(1.-alpha)+original[last]*alpha
    return validate_alignment(points, original, names, evidence)
