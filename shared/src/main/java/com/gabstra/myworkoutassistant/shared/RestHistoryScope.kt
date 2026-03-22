package com.gabstra.myworkoutassistant.shared

/**
 * Classifies persisted [RestHistory] rows: top-level workout `Rest` components vs rests inside an exercise.
 */
enum class RestHistoryScope {
    /** Top-level [com.gabstra.myworkoutassistant.shared.workoutcomponents.Rest] between other components. */
    BETWEEN_WORKOUT_COMPONENTS,

    /** Rest after a set or unilateral mid-set rest ([WorkoutState.Rest] with exercise context). */
    INTRA_EXERCISE
}
