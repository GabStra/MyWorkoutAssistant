"""Shared training-role convention for library review and workout generation."""

# Training identities are separate from the app's coarse front/back body-map regions.
TRAINING_MUSCLES = {
    'chest': 'Chest', 'lats': 'Lats', 'upperBack': 'Upper back', 'lowerBack': 'Lower back',
    'quads': 'Quadriceps', 'hamstrings': 'Hamstrings', 'glutes': 'Glutes',
    'anteriorDelts': 'Anterior deltoids', 'lateralDelts': 'Lateral deltoids', 'rearDelts': 'Rear deltoids',
    'biceps': 'Biceps', 'triceps': 'Triceps', 'calves': 'Calves', 'abs': 'Abdominals',
    'obliques': 'Obliques', 'adductors': 'Hip adductors', 'abductors': 'Hip abductors',
    'forearms': 'Forearms', 'traps': 'Trapezius', 'tibialis': 'Tibialis anterior', 'neck': 'Neck',
}
TRAINING_MUSCLE_GROUPS = {'back': {'lats', 'upperBack'}, 'shoulders': {'anteriorDelts', 'lateralDelts', 'rearDelts'}}


def validate_training_muscles(definition):
    roles = definition.get('trainingMuscles')
    if roles is None:
        return
    if not isinstance(roles, dict) or set(roles) != {'primary', 'secondary'}:
        raise ValueError('trainingMuscles requires exactly primary and secondary arrays.')
    for key, values in roles.items():
        if (not isinstance(values, list) or any(not isinstance(value, str) or value not in TRAINING_MUSCLES for value in values)
                or len(values) != len(set(values))):
            raise ValueError(f'Invalid trainingMuscles.{key}; use unique canonical training-muscle identities.')
    if set(roles['primary']) & set(roles['secondary']):
        raise ValueError('A training muscle cannot be both primary and secondary for one exercise.')

MUSCLE_ROLE_GUIDANCE = """Use a consistent training-role convention across the entire inventory:
muscleGroups identifies the directly trained target regions; secondaryMuscleGroups identifies
meaningfully loaded assisting regions. These roles feed fractional set accounting (direct 1,
compound assistance 0.5), so do not classify every dynamically active anatomical prime mover as
a direct training target. Determine roles from the defining loaded movement, joint actions,
range of motion and technique, not from the current workout, desired volume or equipment name.
Equivalent movements with different implements must have equivalent roles unless their mechanics
actually change. In multi-joint pushing/pulling, arm muscles assisting the defining shoulder action
are normally secondary; targeted elbow-dominant variants can train them directly. Distinguish
chest-dominant horizontal/low-incline pressing (chest target, deltoid and elbow-extensor
assistance) from shoulder-dominant overhead pressing (deltoid target, elbow-extensor assistance).
Changing the implement, adding external load, or changing the grip alone does not promote an
assisting muscle to a direct target; a target change requires a meaningful mechanical change.
For shoulder-driven pulling, use back targets and elbow-flexor assistance; elbow-dominant
curling can directly target elbow flexors. Do not infer substantial hamstring set credit from
ordinary knee-dominant squat/lunge patterns merely because the hamstrings cross both joints.
Distinguish loaded knee extension from hip flexion with a held knee angle: leg position or an active muscle
alone does not establish meaningful quadriceps training. Likewise simultaneous hip/knee motion
does not automatically provide meaningful hamstring training; consider whether that region is
actually loaded through a hypertrophy-relevant action/range. Exclude merely stabilizing/bracing,
balance, grip, contact and incidental activation from both arrays. Allow multiple direct targets
when each is materially trained; never promote an assistant to meet a set target or demote a
target to avoid exceeding one. This is an explicit accounting convention, not a measurement of
precise hypertrophic stimulus. Never infer muscle roles from the supplied current arrays alone.
"""
