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
        val title: String,
        val toolContext: WorkoutInsightsToolContext,
        val systemPrompt: String,
    ) : WorkoutHistoryChatPrepareResult()

    data class Failure(
        val message: String,
    ) : WorkoutHistoryChatPrepareResult()
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
            WorkoutHistoryChatPrepareResult.Failure(promptResult.message)
        is WorkoutInsightsPromptResult.Success -> {
            val toolContext = promptResult.toolContext
                ?: return WorkoutHistoryChatPrepareResult.Failure("Missing tool context for exercise chat.")
            WorkoutHistoryChatPrepareResult.Ready(
                title = "${exercise.name} — chat",
                toolContext = toolContext,
                systemPrompt = buildHistoryChatSystemPromptWithExportedData(
                    instructionsPrompt = buildExerciseHistoryChatSystemPrompt(),
                    toolContext = toolContext,
                ),
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
            WorkoutHistoryChatPrepareResult.Failure(promptResult.message)
        is WorkoutInsightsPromptResult.Success -> {
            val toolContext = promptResult.toolContext
                ?: return WorkoutHistoryChatPrepareResult.Failure("Missing tool context for workout chat.")
            WorkoutHistoryChatPrepareResult.Ready(
                title = "${promptResult.title} — chat",
                toolContext = toolContext,
                systemPrompt = buildHistoryChatSystemPromptWithExportedData(
                    instructionsPrompt = buildWorkoutSessionHistoryChatSystemPrompt(),
                    toolContext = toolContext,
                ),
            )
        }
    }
}
