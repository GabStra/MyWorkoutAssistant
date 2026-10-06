package com.gabstra.myworkoutassistant.composables.workout.pages

/** Stable semantics contentDescription strings for the inter-exercise rest page in [ExercisesPage]. */
object ExercisesPageRestSemantics {
    fun nextExerciseDescription(plainNextName: String): String =
        "Rest page next exercise: $plainNextName"

    fun restDurationRowDescription(formattedDuration: String): String =
        "Rest between exercises duration row: $formattedDuration"
}
