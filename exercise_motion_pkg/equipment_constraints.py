"""Equipment relationships, independent of exercise-name exceptions."""
import numpy as np


HAND_RELATIONSHIPS = {'rigid_pair', 'independent', 'single', 'none', 'unknown'}


def declared_hand_relationship(contract):
    contract = contract if isinstance(contract, dict) else {}
    relationship = contract.get('handRelationship')
    if isinstance(relationship, str) and relationship in HAND_RELATIONSHIPS and relationship != 'unknown':
        return relationship
    context = contract.get('motionContext') or {}
    primary = context.get('primaryEquipment') or {}
    kind = str(primary.get('type') or '').upper()
    required = ' '.join(str(value).lower() for value in contract.get('requiredEquipment', []))
    if kind in {'DUMBBELL', 'DUMBBELLS', 'KETTLEBELL', 'KETTLEBELLS'} or 'dumbbell' in required:
        # Independent implements do not imply symmetric hand trajectories.
        return 'independent'
    return 'unknown'


def calibrated_grip_constraint(payload, points, names):
    supplied = payload.get('equipmentConstraints') or {}
    if supplied.get('handRelationship') != 'rigid_pair':
        return {'handRelationship': supplied.get('handRelationship', 'none')}
    pair = ['left_hand', 'right_hand'] if all(n in names for n in ('left_hand', 'right_hand')) else ['left_wrist', 'right_wrist']
    if not all(n in names for n in pair):
        return {'handRelationship': 'rigid_pair', 'available': False}
    spacing = np.linalg.norm(points[:, names.index(pair[0])]-points[:, names.index(pair[1])], axis=-1)
    measured = spacing[np.isfinite(spacing) & (spacing > .001)]
    distance = supplied.get('distanceMeters')
    explicit = isinstance(distance, (int, float)) and np.isfinite(distance) and distance > .001
    if not explicit:
        distance = float(np.median(measured)) if len(measured) else None
    return {'handRelationship': 'rigid_pair', 'available': distance is not None,
            'endpointPair': pair, 'distanceMeters': distance,
            'distanceSource': 'explicit' if explicit else 'robust_reconstruction_estimate',
            'toleranceMeters': max(.005, .02*distance) if distance is not None else .005}


def grip_residual(points, names, constraint):
    if constraint.get('handRelationship') != 'rigid_pair' or not constraint.get('available'):
        return np.empty((len(points), 0))
    left, right = [names.index(n) for n in constraint['endpointPair']]
    spacing = np.linalg.norm(points[:, left]-points[:, right], axis=-1)
    return (spacing-float(constraint['distanceMeters']))[:, None]


def validate_grip(points, names, constraint):
    required = constraint.get('handRelationship') == 'rigid_pair'
    residual = grip_residual(points, names, constraint)
    error = float(np.max(abs(residual), initial=0.))
    passed = not required or (constraint.get('available', False) and error <= constraint['toleranceMeters'])
    return {'required': required, 'passed': bool(passed), 'maximumSpacingErrorMeters': error,
            'constraint': constraint}


def supported_bilateral_geometry_metrics(payload, *, required):
    """Check the same centered shoulder-relative grip used by supported IK.

    A constant hand distance alone also describes a tilted or displaced bar.
    These relationships use 3D relative vectors, independent of camera angle.
    They apply only when the caller declares a supported bilateral constraint.
    """
    if not required:
        return {'required': False, 'passed': True}
    names = ('left_shoulder', 'right_shoulder', 'left_hand', 'right_hand')
    frames = payload.get('frames') or []
    if not frames or any(not all(n in f.get('joints', {}) for n in names) for f in frames):
        return {'required': True, 'passed': False, 'reason': 'supported_pair_geometry_unavailable'}
    points = np.asarray([[f['joints'][n] for n in names] for f in frames], dtype=float)
    if not np.isfinite(points).all():
        return {'required': True, 'passed': False, 'reason': 'supported_pair_geometry_invalid'}
    shoulders = points[:, 1] - points[:, 0]
    hands = points[:, 3] - points[:, 2]
    shoulder_width = np.linalg.norm(shoulders, axis=-1)
    grip_width = np.linalg.norm(hands, axis=-1)
    if np.any(np.minimum(shoulder_width, grip_width) < 1e-6):
        return {'required': True, 'passed': False, 'reason': 'supported_pair_geometry_degenerate'}
    axis = shoulders / shoulder_width[:, None]
    angle = np.degrees(np.arccos(np.clip(np.sum(hands * axis, axis=-1) / grip_width, -1, 1)))
    center = (points[:, 2] + points[:, 3] - points[:, 0] - points[:, 1]) / 2
    offset = abs(np.sum(center * axis, axis=-1)) / shoulder_width
    # Allow small fitting residuals and normal anatomical differences; reject
    # a persistently different endpoint relationship, not one noisy frame.
    angle_p90, offset_p90 = float(np.percentile(angle, 90)), float(np.percentile(offset, 90))
    return {'required': True, 'passed': angle_p90 <= 15. and offset_p90 <= .25,
            'p90GripShoulderAxisAngleDegrees': angle_p90,
            'p90GripCenterOffsetShoulderWidthRatio': offset_p90,
            'maximumAxisAngleDegrees': 15., 'maximumCenterOffsetShoulderWidthRatio': .25}
