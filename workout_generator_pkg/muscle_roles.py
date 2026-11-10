"""Shared muscle labels and library primary/secondary assignment guidance."""

MUSCLE_LABELS = {
    'chest': 'Chest', 'back': 'Back', 'lowerBack': 'Lower back',
    'quads': 'Quadriceps', 'hamstrings': 'Hamstrings', 'glutes': 'Glutes',
    'shoulders': 'Shoulders', 'biceps': 'Biceps', 'triceps': 'Triceps', 'calves': 'Calves',
    'abs': 'Abdominals', 'obliques': 'Obliques', 'adductors': 'Hip adductors',
    'forearms': 'Forearms', 'traps': 'Trapezius', 'tibialis': 'Tibialis anterior', 'neck': 'Neck',
}

# An omitted reviewed region remains unknown.
REGIONAL_MUSCLE_LABELS = {
    'latissimus_dorsi': 'Latissimus dorsi',
    'upper_back': 'Upper back',
    'deltoid_anterior': 'Anterior deltoid',
    'deltoid_lateral': 'Lateral deltoid',
    'deltoid_posterior': 'Posterior deltoid',
    'pectoralis_clavicular': 'Clavicular pectoralis',
    'pectoralis_sternocostal': 'Sternocostal pectoralis',
}

AGGREGATE_MUSCLE_TAGS = {
    'chest': {'FRONT_CHEST'}, 'back': {'BACK_UPPER_BACK'},
    'quads': {'FRONT_QUADRICEPS'}, 'hamstrings': {'BACK_HAMSTRING'},
    'glutes': {'BACK_GLUTEAL'}, 'shoulders': {'FRONT_DELTOIDS', 'BACK_DELTOIDS'},
    'biceps': {'FRONT_BICEPS'}, 'triceps': {'FRONT_TRICEPS', 'BACK_TRICEPS'},
    'calves': {'FRONT_CALVES', 'BACK_CALVES'}, 'abs': {'FRONT_ABS'},
    'obliques': {'FRONT_OBLIQUES'}, 'adductors': {'FRONT_ADDUCTORS', 'BACK_ADDUCTORS'},
    'forearms': {'FRONT_FOREARM', 'BACK_FOREARM'}, 'traps': {'FRONT_TRAPEZIUS', 'BACK_TRAPEZIUS'},
    'lowerBack': {'BACK_LOWER_BACK'}, 'tibialis': {'FRONT_TIBIALIS'}, 'neck': {'FRONT_NECK', 'BACK_NECK'},
}
REGIONAL_MUSCLE_PARENT = {
    'latissimus_dorsi': 'back', 'upper_back': 'back',
    'deltoid_anterior': 'shoulders', 'deltoid_lateral': 'shoulders', 'deltoid_posterior': 'shoulders',
    'pectoralis_clavicular': 'chest', 'pectoralis_sternocostal': 'chest',
}


def muscle_credits_per_set(exercise):
    """Combine legacy aggregate roles and positive reviewed evidence, once per parent."""
    if exercise.get('exerciseType') is not None and exercise['exerciseType'] not in {'WEIGHT', 'BODY_WEIGHT'}:
        return {}
    primary = set(exercise.get('muscleGroups') or ())
    secondary = set(exercise.get('secondaryMuscleGroups') or ())
    credits = {}
    for muscle, tags in AGGREGATE_MUSCLE_TAGS.items():
        if primary & tags:
            credits[muscle] = {'direct': 1, 'indirect': 0}
        elif secondary & tags:
            credits[muscle] = {'direct': 0, 'indirect': 0.5}
    from .recipe_contracts import regional_muscle_credit_roles
    regional = regional_muscle_credit_roles(exercise)
    for region, roles in regional.items():
        parent = REGIONAL_MUSCLE_PARENT[region]
        existing = credits.get(parent, {'direct': 0, 'indirect': 0})
        if sum(roles.values()) > sum(existing.values()):
            credits[parent] = dict(roles)
    credits.update(regional)
    return credits


def project_training_muscles(definition):
    """Synchronize exported roles with the same accounting used by planning and audit."""
    credits = muscle_credits_per_set(definition)
    primary = list(definition.get('muscleGroups') or ())
    secondary = list(definition.get('secondaryMuscleGroups') or ())
    for muscle, tags in AGGREGATE_MUSCLE_TAGS.items():
        roles = credits.get(muscle, {})
        if roles.get('direct') and not set(primary) & tags:
            primary.extend([tag for tag in secondary if tag in tags] or [sorted(tags)[0]])
            secondary = [tag for tag in secondary if tag not in tags]
        elif roles.get('indirect') and not (set(primary) | set(secondary)) & tags:
            secondary.append(sorted(tags)[0])
    if primary != list(definition.get('muscleGroups') or ()):
        definition['muscleGroups'] = primary
    if secondary != list(definition.get('secondaryMuscleGroups') or ()):
        definition['secondaryMuscleGroups'] = secondary
    definition['trainingMuscles'] = {
        'primary': sorted(muscle for muscle, roles in credits.items() if roles['direct']),
        'secondary': sorted(muscle for muscle, roles in credits.items() if roles['indirect']),
    }
    return definition

MOVEMENT_COVERAGE_ROLES = {
    'knee_dominant': 'Knee-dominant lower-body work',
    'posterior_chain': 'Posterior-chain work',
    'upper_push': 'Upper-body pushing work',
    'upper_pull': 'Upper-body pulling work',
    'horizontal_push': 'Horizontal push work',
    'horizontal_pull': 'Horizontal pull work',
    'vertical_push': 'Vertical push work',
    'vertical_pull': 'Vertical pull work',
    'hip_dominant': 'Hip-dominant lower-body work',
    'knee_flexion_hamstring': 'Knee-flexion hamstring work',
    'lateral_delt': 'Lateral-delt work',
    'rear_delt': 'Rear-delt work',
    'elbow_flexion': 'Elbow-flexion work',
    'elbow_extension': 'Elbow-extension work',
    'calves': 'Dedicated calf work',
    'core': 'Dedicated abdominal/core work',
    'sagittal_plane': 'Sagittal-plane work across the weekly program; program coverage does not require every muscle in every plane',
    'frontal_plane': 'Frontal-plane work across the weekly program; program coverage does not require every muscle in every plane',
    'transverse_plane': 'Transverse-plane work across the weekly program, including loaded rotation or qualifying resistance to rotation; program coverage does not require every muscle in every plane',
    'unilateral': 'Unilateral work; single-limb execution does not automatically establish balance-control work',
    'lateral_movement': 'Lower-body lateral movement work; lateral raises alone do not satisfy this role',
    'rotational_core': 'Dedicated core work with controlled rotation or anti-rotation; generic bracing alone does not establish this role',
}


def coverage_role_descriptions(supported_muscles=None):
    """Code-owned labels for movement patterns and supported muscle groups."""
    muscle_roles = {name.replace('lowerBack', 'lower_back'):
                    f'Dedicated {label.lower()} work' for name, label in MUSCLE_LABELS.items()
                    if supported_muscles is None or name in supported_muscles}
    return {**muscle_roles, **MOVEMENT_COVERAGE_ROLES}

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
