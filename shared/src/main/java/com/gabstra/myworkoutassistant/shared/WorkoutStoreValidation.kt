package com.gabstra.myworkoutassistant.shared

import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.LoadHistoryPolicy
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import java.util.UUID

data class WorkoutStoreDuplicateSetIdIssue(
    val workoutId: UUID,
    val workoutName: String,
    val setId: UUID,
    val exerciseNames: List<String>
)

data class WorkoutStoreRecurringMetadataIssue(val workoutId: UUID, val details: String)

class WorkoutStoreValidationException(
    val duplicateSetIdIssues: List<WorkoutStoreDuplicateSetIdIssue>,
    val recurringMetadataIssues: List<WorkoutStoreRecurringMetadataIssue> = emptyList()
) : IllegalStateException("Workout data contains invalid identities or duplicate set IDs.") {
    val userMessage: String = buildUserMessage(duplicateSetIdIssues, recurringMetadataIssues)

    companion object {
        private fun buildUserMessage(
            issues: List<WorkoutStoreDuplicateSetIdIssue>,
            recurringIssues: List<WorkoutStoreRecurringMetadataIssue>
        ): String {
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
                if (issues.isNotEmpty()) {
                    append("The workout store contains duplicate set IDs inside one or more workouts, so it was not applied automatically.\n\n")
                    append(preview)
                    append(suffix)
                }
                if (recurringIssues.isNotEmpty()) {
                    if (issues.isNotEmpty()) append("\n\n")
                    append("Recurring workout metadata is inconsistent:\n")
                    append(recurringIssues.take(5).joinToString("\n") { "- ${it.details}" })
                    if (recurringIssues.size > 5) append("\n...and ${recurringIssues.size - 5} more issue(s).")
                }
            }
        }
    }
}

fun validateWorkoutStoreForRuntimeUse(workoutStore: WorkoutStore) {
    val issues = workoutStore.findDuplicateSetIdIssues()
    val recurringIssues = workoutStore.findRecurringMetadataIssues()
    if (issues.isNotEmpty() || recurringIssues.isNotEmpty()) {
        throw WorkoutStoreValidationException(issues, recurringIssues)
    }
}

fun WorkoutStore.findRecurringMetadataIssues(): List<WorkoutStoreRecurringMetadataIssue> {
    val issues = mutableListOf<WorkoutStoreRecurringMetadataIssue>()
    val occurrences = mutableMapOf<Pair<UUID, UUID>, MutableList<Exercise>>()
    val ordinals = mutableSetOf<Pair<UUID, Int>>()
    workouts.forEach { workout ->
        if (!workout.isActive) return@forEach
        val sessionId = workout.recurringSessionId
        val exercises = workout.flattenExercises()
        exercises.filter { it.loadHistoryPolicy == LoadHistoryPolicy.PRESCRIBED_WEIGHT }.forEach { exercise ->
            val workingSets = exercise.sets.filterNot { it is com.gabstra.myworkoutassistant.shared.sets.RestSet }
            val compatibleSets = when (exercise.exerciseType) {
                ExerciseType.WEIGHT -> workingSets.all { it is WeightSet }
                ExerciseType.BODY_WEIGHT -> workingSets.all { it is BodyWeightSet }
                else -> false
            }
            if (!compatibleSets || (workingSets.isEmpty() && exercise.sets.isNotEmpty())) {
                issues += WorkoutStoreRecurringMetadataIssue(
                    workout.id,
                    "${workout.name} / ${exercise.name}: fixed prescribed load only supports weight or bodyweight sets.",
                )
            }
        }
        if (sessionId == null) {
            if (workout.prescriptionOrdinal != null || exercises.any {
                    it.recurringExerciseId != null || it.loadHistoryPolicy == LoadHistoryPolicy.LAST_WORKING_LOAD
                }
            ) {
                issues += WorkoutStoreRecurringMetadataIssue(workout.id, "${workout.name}: recurring slot or prescription metadata needs a recurring session ID.")
            }
            return@forEach
        }
        if (workout.prescriptionOrdinal == null || workout.prescriptionOrdinal <= 0) {
            issues += WorkoutStoreRecurringMetadataIssue(workout.id, "${workout.name}: recurring prescriptions need a positive ordinal.")
        } else if (!ordinals.add(sessionId to workout.prescriptionOrdinal)) {
            issues += WorkoutStoreRecurringMetadataIssue(workout.id, "${workout.name}: prescription ordinal ${workout.prescriptionOrdinal} is duplicated in its recurring session.")
        }
        val tracked = exercises.filter { it.recurringExerciseId != null }
        if (tracked.mapNotNull { it.recurringExerciseId }.distinct().size != tracked.size) {
            issues += WorkoutStoreRecurringMetadataIssue(workout.id, "${workout.name}: recurring exercise slot IDs must be unique within the workout.")
        }
        exercises.forEach { exercise ->
            if (exercise.loadHistoryPolicy == LoadHistoryPolicy.LAST_WORKING_LOAD) {
                if (exercise.recurringExerciseId == null) {
                    issues += WorkoutStoreRecurringMetadataIssue(workout.id, "${workout.name} / ${exercise.name}: last-load carry needs a recurring exercise slot ID.")
                }
            }
            if (exercise.loadHistoryPolicy == LoadHistoryPolicy.LAST_WORKING_LOAD) {
                val workingSets = exercise.sets.filterNot { it is com.gabstra.myworkoutassistant.shared.sets.RestSet }
                val compatibleSets = when (exercise.exerciseType) {
                    ExerciseType.WEIGHT -> workingSets.all { it is WeightSet }
                    ExerciseType.BODY_WEIGHT -> workingSets.all { it is BodyWeightSet }
                    else -> false
                }
                val supportedWorkingSets = compatibleSets && workingSets.isNotEmpty()
                if (!supportedWorkingSets) {
                    issues += WorkoutStoreRecurringMetadataIssue(workout.id, "${workout.name} / ${exercise.name}: last-load carry only supports loaded weight and bodyweight sets.")
                }
            }
            exercise.recurringExerciseId?.let { trackId ->
                occurrences.getOrPut(sessionId to trackId) { mutableListOf() }.add(exercise)
            }
        }
    }
    occurrences.forEach { (key, exercises) ->
        val signatures = exercises.map { Triple(it.exerciseDefinitionId, it.exerciseType, it.equipmentId) }.distinct()
        if (signatures.size > 1) {
            val workoutId = workouts.firstOrNull { it.recurringSessionId == key.first }?.id ?: UUID(0L, 0L)
            issues += WorkoutStoreRecurringMetadataIssue(workoutId, "Recurring exercise slot ${key.second} changes definition, exercise type, or equipment within one session.")
        }
    }
    return issues
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
