"""Shared muscle labels and library primary/secondary assignment guidance."""

MUSCLE_LABELS = {
    'chest': 'Chest', 'back': 'Back', 'lowerBack': 'Lower back',
    'quads': 'Quadriceps', 'hamstrings': 'Hamstrings', 'glutes': 'Glutes',
    'shoulders': 'Shoulders', 'biceps': 'Biceps', 'triceps': 'Triceps', 'calves': 'Calves',
    'abs': 'Abdominals', 'obliques': 'Obliques', 'adductors': 'Hip adductors',
    'forearms': 'Forearms', 'traps': 'Trapezius', 'tibialis': 'Tibialis anterior', 'neck': 'Neck',
}

MUSCLE_ROLE_GUIDANCE = """Use a consistent training-role convention across the entire inventory:
muscleGroups identifies the directly trained target regions; secondaryMuscleGroups identifies
meaningfully loaded assisting regions. These roles feed fractional set accounting (direct 1,
secondary assistance 0.5), so do not classify every dynamically active anatomical prime mover as
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
