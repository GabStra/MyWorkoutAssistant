"""Shared statement of repair behavior supported by review and repair."""
from copy import deepcopy

REPAIR_DIMENSIONS = {
    'session_labels': 'Edit workout name and description.',
    'exercise_selection': 'Propose adding, removing, or replacing library exercises; Python qualifies entries and validates the complete plan.',
    'prescription': 'Edit sets, repetitions, load, rest, and duration within approved bounds.',
    'progression': 'Edit typed progression plans and supported post-ceiling routes.',
    'ordering': 'Reorder exercises and workouts.',
    'superset': 'Edit supported superset membership and rest structure.',
    'coverage': 'Edit assignments to approved coverage requirements.',
    'session_timing': 'Edit setup and timing estimates; Python recalculates total duration.',
    'guidance': 'Edit local movement technique and setup cues only.',
    'program_guidance': 'Edit plan-level manual coaching guidance shown with the workout; it does not alter app behavior.',
}

# Keep this inventory aligned with the existing typed repair-path classifier.
FIELD_REPAIR_DIMENSIONS = {
    'name': {'session_labels'},
    'description': {'session_labels'},
    'programGuidance': {'program_guidance'},
    'definition_id': {'exercise_selection'},
    'numWorkSets': {'prescription', 'session_timing'},
    'minReps': {'prescription', 'session_timing'},
    'maxReps': {'prescription', 'session_timing'},
    'workSetTemplate': {'prescription', 'session_timing'},
    'targetSetPrescriptions': {'prescription', 'session_timing'},
    'progressionPlan': {'progression'},
    'progressionMethod': {'progression'},
    'generateWarmUpSets': {'session_timing'},
    'effortAcceptance': {'prescription'},
    'placementNotes': {'guidance'},
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


def repair_field_dimensions(field):
    return set(FIELD_REPAIR_DIMENSIONS.get(field, ()))

WORKING_SET_UNDERPERFORMANCE_GUIDANCE = (
    'For normal working sets, if prescribed reps or duration cannot be completed within accepted effort/technical criteria, '
    'stop the set and stop the affected prescription; do not change load, equipment, or configuration. Re-audit before '
    'continuing. A failed target is not a successfully completed set.')

CODE_OWNED_BEHAVIORS = {
    'working_set_effort_acceptance': (
        'Python renders the approved working-set RIR target or the plan-authored typed acceptance and stop criteria. '
        'Local placementNotes cannot replace or override these criteria.'),
    'native_load_calibration': (
        'The app-native requiresLoadCalibration flag is code-owned and derived from exercise type, equipment, and '
        'available load history. It is not a model-editable per-exercise calibration protocol.'),
    'typed_progression_rendering': (
        'Python renders a validated typed progression plan or supported progression method. Local placementNotes '
        'cannot replace or override its progression triggers.'),
    'working_set_underperformance_stop_reaudit': {
        'guidance': WORKING_SET_UNDERPERFORMANCE_GUIDANCE,
        'authority': 'Python',
        'editable': False,
    },
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
