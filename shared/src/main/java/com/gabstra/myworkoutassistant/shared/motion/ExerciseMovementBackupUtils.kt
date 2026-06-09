package com.gabstra.myworkoutassistant.shared.motion

import android.content.Context
import com.gabstra.myworkoutassistant.shared.ExerciseMovementBackup
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset

fun collectExerciseMovementBackups(
    context: Context,
    workoutStore: WorkoutStore,
): List<ExerciseMovementBackup> {
    return workoutStore.workouts
        .asSequence()
        .flatMap { workout ->
            workout.workoutComponents.asSequence().flatMap { component ->
                when (component) {
                    is Exercise -> sequenceOf(component)
                    is Superset -> component.exercises.asSequence()
                    else -> emptySequence()
                }
            }
        }
        .mapNotNull { exercise -> exercise.movementRef }
        .distinctBy { movementRef -> movementRef.movementId to movementRef.contentHash }
        .mapNotNull { movementRef ->
            ExerciseMovementStorage.readMovementJson(context, movementRef)?.let { json ->
                ExerciseMovementBackup(
                    movementRef = movementRef,
                    json = json,
                )
            }
        }
        .toList()
}

fun restoreExerciseMovementBackups(
    context: Context,
    movementBackups: List<ExerciseMovementBackup>,
) {
    movementBackups.forEach { movementBackup ->
        ExerciseMovementStorage.writeMovementJson(
            context = context,
            movementRef = movementBackup.movementRef,
            json = movementBackup.json,
        )
    }
}
