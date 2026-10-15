"""Shared training-role convention for library review and workout generation."""

MUSCLE_ROLE_GUIDANCE = """Use a consistent training-role convention across the entire inventory:
muscleGroups identifies the directly trained target regions; secondaryMuscleGroups identifies
meaningfully loaded assisting regions. These roles feed fractional set accounting (direct 1,
compound assistance 0.5), so do not classify every dynamically active anatomical prime mover as
a direct training target. Determine roles from the defining loaded movement, joint actions,
range of motion and technique, not from the current workout, desired volume or equipment name.
Equivalent movements with different implements must have equivalent roles unless their mechanics
actually change. In multi-joint pushing/pulling, arm muscles assisting the defining shoulder action
are normally secondary; targeted elbow-dominant variants can train them directly. Distinguish
loaded knee extension from hip flexion with a held knee angle: leg position or an active muscle
alone does not establish meaningful quadriceps training. Likewise simultaneous hip/knee motion
does not automatically provide meaningful hamstring training; consider whether that region is
actually loaded through a hypertrophy-relevant action/range. Exclude merely stabilizing/bracing,
balance, grip, contact and incidental activation from both arrays. Allow multiple direct targets
when each is materially trained; never promote an assistant to meet a set target or demote a
target to avoid exceeding one. This is an explicit accounting convention, not a measurement of
precise hypertrophic stimulus. Never infer muscle roles from the supplied current arrays alone.
"""
