"""Equipment relationships, independent of exercise-name exceptions."""
import numpy as np

from .contract_authority import contract_field_authority


HAND_RELATIONSHIPS = {'rigid_pair', 'independent', 'single', 'none', 'unknown'}


def normalized_equipment_relationships(contract):
    """Resolve only explicit equipment facts and structural field dependencies."""
    context = contract.get('motionContext')
    primary = context.get('primaryEquipment') if isinstance(context, dict) else None
    kind = str(primary.get('type') or '').upper() if isinstance(primary, dict) else ''
    required = contract.get('requiredEquipment')
    required = [required] if isinstance(required, str) else required
    required = required if isinstance(required, (list, tuple, set)) else []
    required_kinds = {
        str(value).strip().upper()
        for value in required or []
        if isinstance(value, str) and str(value).strip()
    }
    relationship = contract.get('handRelationship')
    support_mode = contract.get('implementSupportMode')
    updates = {}
    # Equipment count and explicitly named acting-arm count outrank model guesses.
    if kind in {'DUMBBELLS', 'KETTLEBELLS'} or required_kinds.intersection(
        {'DUMBBELLS', 'KETTLEBELLS'}
    ):
        relationship = 'independent'
        updates['handRelationship'] = relationship
        updates['implementSupportMode'] = 'none'
    elif kind in {'DUMBBELL', 'KETTLEBELL'}:
        authority = contract_field_authority(str(contract.get('exerciseName') or ''), {})
        if authority.get('actingArmCount', {}).get('value') == 1:
            relationship = 'single'
            updates['handRelationship'] = relationship
            updates['implementSupportMode'] = 'none'
    if support_mode == 'hands_only' and relationship in {'independent', 'single', 'none'}:
        updates['implementSupportMode'] = 'none'
    return updates


def declared_hand_relationship(contract):
    contract = contract if isinstance(contract, dict) else {}
    relationship = normalized_equipment_relationships(contract).get('handRelationship', contract.get('handRelationship'))
    if isinstance(relationship, str) and relationship in HAND_RELATIONSHIPS and relationship != 'unknown':
        return relationship
    context = contract.get('motionContext') or {}
    primary = context.get('primaryEquipment') or {}
    kind = str(primary.get('type') or '').upper()
    if kind in {'DUMBBELLS', 'KETTLEBELLS'}:
        # Separate implements do not imply symmetric hand trajectories.
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
