package com.gabstra.myworkoutassistant.insights

import com.gabstra.myworkoutassistant.shared.ExerciseSessionProgressionDao
import com.gabstra.myworkoutassistant.shared.RestHistoryDao
import com.gabstra.myworkoutassistant.shared.SetHistoryDao
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryDao
import com.gabstra.myworkoutassistant.shared.WorkoutRecordDao
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import java.util.UUID

sealed class WorkoutHistoryChatPrepareResult {
    data class Ready(
        val title: WorkoutHistoryChatTitle,
        val toolContext: WorkoutInsightsToolContext,
        val systemPrompt: String,
    ) : WorkoutHistoryChatPrepareResult()

    data class Failure(
        val reason: WorkoutHistoryChatFailureReason,
        val diagnostic: String,
    ) : WorkoutHistoryChatPrepareResult()
}

/**
 * App-owned chat title subject. User-written names stay as-is; the screen adds the
 * localized chat framing so no English UI prose is baked into the coordinator.
 */
sealed class WorkoutHistoryChatTitle {
    data class Exercise(val exerciseName: String) : WorkoutHistoryChatTitle()

    data object WorkoutSession : WorkoutHistoryChatTitle()
}

enum class WorkoutHistoryChatFailureReason {
    WORKOUT_NOT_FOUND,
    EXERCISE_NOT_FOUND,
    EXERCISE_HISTORY_UNAVAILABLE,
    WORKOUT_SESSION_UNAVAILABLE,
    CHAT_PREPARATION_FAILED,
}

suspend fun prepareExerciseHistoryChatContext(
    exercise: Exercise,
    workoutHistoryDao: WorkoutHistoryDao,
    setHistoryDao: SetHistoryDao,
    restHistoryDao: RestHistoryDao,
    exerciseSessionProgressionDao: ExerciseSessionProgressionDao,
    workouts: List<Workout>,
    workoutStore: WorkoutStore,
): WorkoutHistoryChatPrepareResult {
    return when (
        val promptResult = buildExerciseInsightsPrompt(
            exercise = exercise,
            workoutHistoryDao = workoutHistoryDao,
            setHistoryDao = setHistoryDao,
            restHistoryDao = restHistoryDao,
            exerciseSessionProgressionDao = exerciseSessionProgressionDao,
            workouts = workouts,
            workoutStore = workoutStore
        )
    ) {
        is WorkoutInsightsPromptResult.Failure ->
            WorkoutHistoryChatPrepareResult.Failure(
                reason = WorkoutHistoryChatFailureReason.EXERCISE_HISTORY_UNAVAILABLE,
                diagnostic = promptResult.message,
            )
        is WorkoutInsightsPromptResult.Success -> {
            val toolContext = promptResult.toolContext
                ?: return WorkoutHistoryChatPrepareResult.Failure(
                    reason = WorkoutHistoryChatFailureReason.CHAT_PREPARATION_FAILED,
                    diagnostic = "Missing tool context for exercise chat.",
                )
            WorkoutHistoryChatPrepareResult.Ready(
                title = WorkoutHistoryChatTitle.Exercise(exercise.name),
                toolContext = toolContext,
                systemPrompt = buildHistoryChatToolCallingSystemPrompt("one exercise"),
            )
        }
    }
}

suspend fun prepareWorkoutSessionHistoryChatContext(
    workoutHistoryId: UUID,
    workoutHistoryDao: WorkoutHistoryDao,
    workoutRecordDao: WorkoutRecordDao,
    setHistoryDao: SetHistoryDao,
    restHistoryDao: RestHistoryDao,
    exerciseSessionProgressionDao: ExerciseSessionProgressionDao,
    workoutStore: WorkoutStore,
): WorkoutHistoryChatPrepareResult {
    return when (
        val promptResult = buildWorkoutSessionInsightsPrompt(
            workoutHistoryId = workoutHistoryId,
            workoutHistoryDao = workoutHistoryDao,
            workoutRecordDao = workoutRecordDao,
            setHistoryDao = setHistoryDao,
            restHistoryDao = restHistoryDao,
            exerciseSessionProgressionDao = exerciseSessionProgressionDao,
            workoutStore = workoutStore
        )
    ) {
        is WorkoutInsightsPromptResult.Failure ->
            WorkoutHistoryChatPrepareResult.Failure(
                reason = WorkoutHistoryChatFailureReason.WORKOUT_SESSION_UNAVAILABLE,
                diagnostic = promptResult.message,
            )
        is WorkoutInsightsPromptResult.Success -> {
            val toolContext = promptResult.toolContext
                ?: return WorkoutHistoryChatPrepareResult.Failure(
                    reason = WorkoutHistoryChatFailureReason.CHAT_PREPARATION_FAILED,
                    diagnostic = "Missing tool context for workout chat.",
                )
            WorkoutHistoryChatPrepareResult.Ready(
                title = WorkoutHistoryChatTitle.WorkoutSession,
                toolContext = toolContext,
                systemPrompt = withAlwaysAvailableFacts(
                    systemPrompt = buildHistoryChatToolCallingSystemPrompt("one completed workout session"),
                    coreFactsBlock = promptResult.coreFactsBlock,
                ),
            )
        }
    }
}
