package com.gabstra.myworkoutassistant.shared

import com.gabstra.myworkoutassistant.shared.workout.state.ProgressionState
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise

data class DeloadConfig(
    val failedSessionsThreshold: Int? = DEFAULT_FAILED_SESSIONS_THRESHOLD,
    val completedSessionsInterval: Int? = DEFAULT_COMPLETED_SESSIONS_INTERVAL,
    val weightFactor: Double = DEFAULT_WEIGHT_FACTOR,
    val repsDrop: Int = DEFAULT_REPS_DROP,
    val cutSetsTo: Int? = DEFAULT_CUT_SETS_TO,
) {
    companion object {
        val DEFAULT_FAILED_SESSIONS_THRESHOLD: Int? = 2
        val DEFAULT_COMPLETED_SESSIONS_INTERVAL: Int? = null
        const val DEFAULT_WEIGHT_FACTOR: Double = 0.9
        const val DEFAULT_REPS_DROP: Int = 2
        val DEFAULT_CUT_SETS_TO: Int? = null
    }
}

data class ProgressionDecision(
    val progressionState: ProgressionState,
    val shouldLoadLastSuccessfulSession: Boolean,
)

fun WorkoutStore.resolveDeloadConfig(exercise: Exercise): DeloadConfig {
    return DeloadConfig(
        failedSessionsThreshold = exercise.deloadFailedSessionsThreshold ?: deloadConfig.failedSessionsThreshold,
        completedSessionsInterval = exercise.deloadCompletedSessionsInterval ?: deloadConfig.completedSessionsInterval,
        weightFactor = exercise.deloadWeightFactor ?: deloadConfig.weightFactor,
        repsDrop = exercise.deloadRepsDrop ?: deloadConfig.repsDrop,
        cutSetsTo = exercise.deloadCutSetsTo ?: deloadConfig.cutSetsTo,
    )
}

fun shouldConsiderDeload(exercise: Exercise): Boolean {
    return exercise.enabled &&
        exercise.progressionMode != ProgressionMode.OFF &&
        !exercise.requiresLoadCalibration &&
        (exercise.exerciseType == ExerciseType.WEIGHT || exercise.exerciseType == ExerciseType.BODY_WEIGHT)
}

fun resolveProgressionDecision(
    exercise: Exercise,
    exerciseInfo: ExerciseInfo?,
    workoutStore: WorkoutStore,
): ProgressionDecision {
    val fails = exerciseInfo?.sessionFailedCounter?.toInt() ?: 0
    val completedSessionsSinceDeload = exerciseInfo?.completedSessionsSinceDeload?.toInt() ?: 0
    val lastWasDeload = exerciseInfo?.lastSessionWasDeload ?: false

    val shouldDeload = if (shouldConsiderDeload(exercise) && !lastWasDeload) {
        val deloadConfig = workoutStore.resolveDeloadConfig(exercise)
        val failedThresholdHit = deloadConfig.failedSessionsThreshold?.let { fails >= it } ?: false
        val completedIntervalHit = deloadConfig.completedSessionsInterval?.let {
            completedSessionsSinceDeload >= it
        } ?: false
        failedThresholdHit || completedIntervalHit
    } else {
        false
    }

    val shouldRetry = !lastWasDeload && fails >= 1
    val progressionState = when {
        shouldDeload -> ProgressionState.DELOAD
        shouldRetry -> ProgressionState.RETRY
        else -> ProgressionState.PROGRESS
    }

    return ProgressionDecision(
        progressionState = progressionState,
        shouldLoadLastSuccessfulSession = lastWasDeload || (shouldRetry && !shouldDeload)
    )
}
