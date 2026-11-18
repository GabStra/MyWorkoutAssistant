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

enum class WorkoutStoreRecurringMetadataIssueCode {
    FIXED_PRESCRIBED_LOAD_UNSUPPORTED_SETS,
    MISSING_RECURRING_SESSION_ID,
    NON_POSITIVE_PRESCRIPTION_ORDINAL,
    DUPLICATE_PRESCRIPTION_ORDINAL,
    DUPLICATE_RECURRING_EXERCISE_SLOT_IDS,
    LAST_WORKING_LOAD_MISSING_SLOT_ID,
    LAST_WORKING_LOAD_UNSUPPORTED_SETS,
    CONFLICTING_RECURRING_SLOT_IDENTITY,
}

data class WorkoutStoreRecurringMetadataIssue(
    val workoutId: UUID,
    val code: WorkoutStoreRecurringMetadataIssueCode,
    val workoutName: String,
    val exerciseName: String? = null,
    val prescriptionOrdinal: Int? = null,
    val recurringExerciseSlotId: UUID? = null,
) {
    /**
     * English developer diagnostic for logs and regression tests.
     * User-facing text is resolved from [code] and its structured fields at the UI boundary.
     */
    val details: String
        get() = when (code) {
            WorkoutStoreRecurringMetadataIssueCode.FIXED_PRESCRIBED_LOAD_UNSUPPORTED_SETS ->
                "$workoutName / ${exerciseName.orEmpty()}: fixed prescribed load only supports weight or bodyweight sets."
            WorkoutStoreRecurringMetadataIssueCode.MISSING_RECURRING_SESSION_ID ->
                "$workoutName: recurring slot or prescription metadata needs a recurring session ID."
            WorkoutStoreRecurringMetadataIssueCode.NON_POSITIVE_PRESCRIPTION_ORDINAL ->
                "$workoutName: recurring prescriptions need a positive ordinal."
            WorkoutStoreRecurringMetadataIssueCode.DUPLICATE_PRESCRIPTION_ORDINAL ->
                "$workoutName: prescription ordinal $prescriptionOrdinal is duplicated in its recurring session."
            WorkoutStoreRecurringMetadataIssueCode.DUPLICATE_RECURRING_EXERCISE_SLOT_IDS ->
                "$workoutName: recurring exercise slot IDs must be unique within the workout."
            WorkoutStoreRecurringMetadataIssueCode.LAST_WORKING_LOAD_MISSING_SLOT_ID ->
                "$workoutName / ${exerciseName.orEmpty()}: last-load carry needs a recurring exercise slot ID."
            WorkoutStoreRecurringMetadataIssueCode.LAST_WORKING_LOAD_UNSUPPORTED_SETS ->
                "$workoutName / ${exerciseName.orEmpty()}: last-load carry only supports loaded weight and bodyweight sets."
            WorkoutStoreRecurringMetadataIssueCode.CONFLICTING_RECURRING_SLOT_IDENTITY ->
                "Recurring exercise slot $recurringExerciseSlotId changes definition, exercise type, or equipment within one session."
        }
}

class WorkoutStoreValidationException(
    val duplicateSetIdIssues: List<WorkoutStoreDuplicateSetIdIssue>,
    val recurringMetadataIssues: List<WorkoutStoreRecurringMetadataIssue> = emptyList()
) : IllegalStateException("Workout data contains invalid identities or duplicate set IDs.") {
    /**
     * English diagnostic text for logs and bug reports.
     * User-facing dialogs resolve the structured issues through localized resources instead.
     */
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
                    workoutId = workout.id,
                    code = WorkoutStoreRecurringMetadataIssueCode.FIXED_PRESCRIBED_LOAD_UNSUPPORTED_SETS,
                    workoutName = workout.name,
                    exerciseName = exercise.name,
                )
            }
        }
        if (sessionId == null) {
            if (workout.prescriptionOrdinal != null || exercises.any {
                    it.recurringExerciseId != null || it.loadHistoryPolicy == LoadHistoryPolicy.LAST_WORKING_LOAD
                }
            ) {
                issues += WorkoutStoreRecurringMetadataIssue(
                    workoutId = workout.id,
                    code = WorkoutStoreRecurringMetadataIssueCode.MISSING_RECURRING_SESSION_ID,
                    workoutName = workout.name,
                )
            }
            return@forEach
        }
        if (workout.prescriptionOrdinal == null || workout.prescriptionOrdinal <= 0) {
            issues += WorkoutStoreRecurringMetadataIssue(
                workoutId = workout.id,
                code = WorkoutStoreRecurringMetadataIssueCode.NON_POSITIVE_PRESCRIPTION_ORDINAL,
                workoutName = workout.name,
            )
        } else if (!ordinals.add(sessionId to workout.prescriptionOrdinal)) {
            issues += WorkoutStoreRecurringMetadataIssue(
                workoutId = workout.id,
                code = WorkoutStoreRecurringMetadataIssueCode.DUPLICATE_PRESCRIPTION_ORDINAL,
                workoutName = workout.name,
                prescriptionOrdinal = workout.prescriptionOrdinal,
            )
        }
        val tracked = exercises.filter { it.recurringExerciseId != null }
        if (tracked.mapNotNull { it.recurringExerciseId }.distinct().size != tracked.size) {
            issues += WorkoutStoreRecurringMetadataIssue(
                workoutId = workout.id,
                code = WorkoutStoreRecurringMetadataIssueCode.DUPLICATE_RECURRING_EXERCISE_SLOT_IDS,
                workoutName = workout.name,
            )
        }
        exercises.forEach { exercise ->
            if (exercise.loadHistoryPolicy == LoadHistoryPolicy.LAST_WORKING_LOAD) {
                if (exercise.recurringExerciseId == null) {
                    issues += WorkoutStoreRecurringMetadataIssue(
                        workoutId = workout.id,
                        code = WorkoutStoreRecurringMetadataIssueCode.LAST_WORKING_LOAD_MISSING_SLOT_ID,
                        workoutName = workout.name,
                        exerciseName = exercise.name,
                    )
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
                    issues += WorkoutStoreRecurringMetadataIssue(
                        workoutId = workout.id,
                        code = WorkoutStoreRecurringMetadataIssueCode.LAST_WORKING_LOAD_UNSUPPORTED_SETS,
                        workoutName = workout.name,
                        exerciseName = exercise.name,
                    )
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
            issues += WorkoutStoreRecurringMetadataIssue(
                workoutId = workoutId,
                code = WorkoutStoreRecurringMetadataIssueCode.CONFLICTING_RECURRING_SLOT_IDENTITY,
                workoutName = workouts.firstOrNull { it.recurringSessionId == key.first }?.name.orEmpty(),
                recurringExerciseSlotId = key.second,
            )
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
