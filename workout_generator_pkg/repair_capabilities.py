"""Shared statement of repair behavior supported by review and repair."""
from copy import deepcopy

REPAIR_DIMENSIONS = {
    'session_labels': 'Edit workout name and description.',
    'exercise_selection': 'Propose adding, removing, or replacing library exercises; Python qualifies entries and validates the complete plan.',
    'prescription': 'Edit sets, repetitions, load, rest, and duration within approved bounds.',
    'ordering': 'Reorder exercises and workouts.',
    'superset': 'Edit supported superset membership and rest structure.',
    'coverage': 'Edit assignments to approved coverage requirements.',
    'session_timing': 'Edit setup and timing estimates; Python recalculates total duration.',
}

# Keep this inventory aligned with the existing typed repair-path classifier.
FIELD_REPAIR_DIMENSIONS = {
    'name': {'session_labels'},
    'description': {'session_labels'},
    'definition_id': {'exercise_selection'},
    'numWorkSets': {'prescription', 'session_timing'},
    'minReps': {'prescription', 'session_timing'},
    'maxReps': {'prescription', 'session_timing'},
    'workSetTemplate': {'prescription', 'session_timing'},
    'targetSetPrescriptions': {'prescription', 'session_timing'},
    'generateWarmUpSets': {'session_timing'},
    'effortAcceptance': {'prescription'},
    'satisfiesCoverage': {'coverage'},
    'setupSeconds': {'session_timing', 'prescription'},
    'restBetweenSetsSeconds': {'session_timing', 'prescription'},
    'restAfterExerciseSeconds': {'session_timing', 'prescription'},
    'durationSeconds': {'session_timing', 'prescription'},
    'repDurationSeconds': {'session_timing', 'prescription'},
    'intraSetRestInSeconds': {'session_timing', 'prescription'},
    'timesCompletedInAWeek': {'session_timing', 'prescription'},
    'superset': {'superset', 'session_timing'},
    'restAfterSupersetExerciseSeconds': {'superset', 'session_timing'},
    'trainingDays': {'ordering', 'session_timing'},
}

REPAIR_OBJECTIVE_DIMENSIONS = {
    # This objective preserves the selected recipes and their set prescriptions;
    # only exercise placement and order are editable. The solver recalculates timing.
    'redistribute_work': {'exercise_selection', 'ordering'},
}


def repair_field_dimensions(field):
    return set(FIELD_REPAIR_DIMENSIONS.get(field, ()))


def repair_objective_dimensions(objective):
    """Return code-owned edit scope implied by a supported typed objective."""
    if not isinstance(objective, dict):
        return set()
    return set(REPAIR_OBJECTIVE_DIMENSIONS.get(objective.get('kind'), ()))


def repair_group_dimensions(group):
    """Combine supported semantic fields with the effects of selected operations."""
    if not isinstance(group, dict):
        return set()
    dimensions = set(group.get('repairDimensions') or [])
    for objective in (group or {}).get('repairObjectives', []):
        dimensions.update(repair_objective_dimensions(objective))
    return dimensions

RECOVERY_ADJUSTMENT_GUIDANCE = (
    'If recovery is inadequate, request a re-audit before changing set counts. Any proposed reduction '
    'must preserve approved per-exercise floors and weekly or per-session minimums; the audit rejects reductions '
    'that breach them. Changing approved targets requires a human decision. The app owns progression.'
)

CODE_OWNED_BEHAVIORS = {
    'hypothetical_alternative_evaluation': (
        'Python binds the exact source-authorized numerical proposal for candidate evaluation. Listed changes '
        'are hypothetical exceptions to only those clauses, including older decisions. All unlisted requirements '
        'remain binding. Pending approval is workflow state, not missing execution behavior.'),
    'alternative_acceptance': (
        'Explicit selection is enforced after the alternative passes numerical audit and independent review. '
        'Preparing accurate proposed guidance does not accept an alternative or change active requirements.'),
    'working_set_effort_acceptance': (
        'Python renders the approved working-set RIR target or the plan-authored typed acceptance and stop criteria. '
        'The typed prescription owns these criteria.'),
    'native_load_calibration': (
        'The app-native requiresLoadCalibration flag is code-owned and derived from exercise type, equipment, and '
        'available load history. It is not a model-editable per-exercise calibration protocol.'),
    'app_native_rep_load_progression': (
        'finalArtifact.progressionMode is authoritative: DOUBLE_PROGRESSION and AUTO_REGULATION use app double progression; AUTO_REGULATION adds per-set RIR except the last work set; OFF has none. Do not require a generator method or prose.'),
    'execution_instructions': (
        'Python renders setup time estimates, straight-set and superset order/rest instructions, and warm-up '
        'generation availability from the final prescription. Exact app-generated ramp-ups depend on runtime '
        'load/equipment; unweighted configurations do not supply a lighter loaded ramp-up protocol.'),
    'recovery_adjustment': RECOVERY_ADJUSTMENT_GUIDANCE,
}

UNSUPPORTED_REPAIR_CAPABILITIES = {
    'automatic_load_reduction': 'Automatically lower the load during a working set or between sets.',
}


def repair_capability_contract():
    return deepcopy({'editableDimensions': REPAIR_DIMENSIONS,
        'editableFields': {field: sorted(dimensions) for field, dimensions in FIELD_REPAIR_DIMENSIONS.items()},
        'codeOwnedBehaviors': CODE_OWNED_BEHAVIORS,
        'unsupportedBehaviors': UNSUPPORTED_REPAIR_CAPABILITIES})


def has_unresolved_capabilities(assessment):
    return any(group.get('disposition') == 'unresolved_capability'
               for group in (assessment or {}).get('groups', []))


def preserve_source_selection_for_repair(previous_joint_solve=None, *, valid_carried_domain=False):
    """Keep the submitted menu fixed unless continuing a validated solver domain."""
    return not (valid_carried_domain is True
                and isinstance(previous_joint_solve, dict)
                and previous_joint_solve.get('preserveSourceSelection') is False)
