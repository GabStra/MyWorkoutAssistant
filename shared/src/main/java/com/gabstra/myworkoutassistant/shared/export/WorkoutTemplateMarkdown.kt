package com.gabstra.myworkoutassistant.shared.export

import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import java.util.UUID

/** Exercises in template order (standalone exercises and superset exercises in superset order). */
internal fun templateExerciseIdsInWorkoutOrder(workout: Workout): List<UUID> = buildList {
    for (c in workout.workoutComponents) {
        when (c) {
            is Exercise -> add(c.id)
            is Superset -> c.exercises.forEach { add(it.id) }
            else -> {}
        }
    }
}

internal fun templatePosition1BasedForExercise(workout: Workout, exerciseId: UUID): Int? {
    val idx = templateExerciseIdsInWorkoutOrder(workout).indexOf(exerciseId)
    return if (idx >= 0) idx + 1 else null
}
