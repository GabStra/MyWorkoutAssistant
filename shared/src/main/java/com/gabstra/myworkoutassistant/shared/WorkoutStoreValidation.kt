package com.gabstra.myworkoutassistant.shared

import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import java.util.UUID

data class WorkoutStoreDuplicateSetIdIssue(
    val workoutId: UUID,
    val workoutName: String,
    val setId: UUID,
    val exerciseNames: List<String>
)

class WorkoutStoreValidationException(
    val duplicateSetIdIssues: List<WorkoutStoreDuplicateSetIdIssue>
) : IllegalStateException("One or more workouts contain duplicate set IDs.") {
    val userMessage: String = buildUserMessage(duplicateSetIdIssues)

    companion object {
        private fun buildUserMessage(issues: List<WorkoutStoreDuplicateSetIdIssue>): String {
            val preview = issues
                .take(3)
                .joinToString(separator = "\n\n") { issue ->
                    buildString {
                        append("Workout: ${issue.workoutName}\n")
                        append("Duplicate set ID: ${issue.setId}\n")
                        append("Exercises: ${issue.exerciseNames.joinToString(", ")}")
                    }
                }
            val remaining = issues.size - 3
            val suffix = if (remaining > 0) {
                "\n\n...and $remaining more duplicate set ID issue(s)."
            } else {
                ""
            }
            return buildString {
                append("The workout store contains duplicate set IDs inside one or more workouts, so it was not applied automatically.\n\n")
                append(preview)
                append(suffix)
            }
        }
    }
}

fun validateWorkoutStoreForRuntimeUse(workoutStore: WorkoutStore) {
    val issues = workoutStore.findDuplicateSetIdIssues()
    if (issues.isNotEmpty()) {
        throw WorkoutStoreValidationException(issues)
    }
}

fun WorkoutStore.findDuplicateSetIdIssues(): List<WorkoutStoreDuplicateSetIdIssue> {
    return workouts.flatMap { workout ->
        val occurrencesBySetId = linkedMapOf<UUID, MutableList<String>>()
        workout.flattenExercises().forEach { exercise ->
            exercise.sets.forEach { set ->
                occurrencesBySetId
                    .getOrPut(set.id) { mutableListOf() }
                    .add(exercise.name)
            }
        }
        occurrencesBySetId
            .filterValues { exerciseNames -> exerciseNames.size > 1 }
            .map { (setId, exerciseNames) ->
                WorkoutStoreDuplicateSetIdIssue(
                    workoutId = workout.id,
                    workoutName = workout.name,
                    setId = setId,
                    exerciseNames = exerciseNames.distinct()
                )
            }
    }
}

private fun Workout.flattenExercises(): List<Exercise> {
    return workoutComponents.filterIsInstance<Exercise>() +
        workoutComponents.filterIsInstance<Superset>().flatMap { it.exercises }
}
