package com.gabstra.myworkoutassistant.composables

/** Stable semantics contentDescription strings for the inter-exercise rest page in [PageExercises]. */
object PageExercisesRestSemantics {
    const val BetweenExercisesTransitionDescription = "Between exercises down arrow"

    fun previousExerciseDescription(plainPreviousName: String): String =
        "Rest page previous exercise: $plainPreviousName"

    fun nextExerciseDescription(plainNextName: String): String =
        "Rest page next exercise: $plainNextName"

    fun restDurationRowDescription(formattedDuration: String): String =
        "Rest between exercises duration row: $formattedDuration"
}
