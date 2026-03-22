package com.gabstra.myworkoutassistant.shared.workout.history

import com.gabstra.myworkoutassistant.shared.RestHistory
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Rest
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import java.util.UUID

/**
 * Ordered sections for Workout History UI: follows [Workout.workoutComponents] (template order).
 * Rest-between-workout-components sections appear after the preceding exercise/superset block when
 * the next template component is a [Rest].
 */
sealed class WorkoutHistoryLayoutItem {
    data class ExerciseSection(val exerciseId: UUID) : WorkoutHistoryLayoutItem()
    data class SupersetSection(val supersetId: UUID) : WorkoutHistoryLayoutItem()
    data class RestSection(val restComponentId: UUID, val history: RestHistory) :
        WorkoutHistoryLayoutItem()
}

/**
 * Builds layout items in workout template order. Skips exercises/supersets with no set history.
 * Between-workout-component [RestHistory] rows are placed at each template [Rest] via
 * [orderedBetweenWorkoutComponentRestHistories] (one row per template [Rest] per session).
 */
fun buildWorkoutHistoryLayout(
    workout: Workout,
    setHistoriesByExerciseId: Map<UUID, List<SetHistory>>,
    sessionRestHistories: List<RestHistory>
): List<WorkoutHistoryLayoutItem> {
    val orderedBetween = orderedBetweenWorkoutComponentRestHistories(sessionRestHistories, workout)
    val historyByRestComponentId: Map<UUID, RestHistory> =
        orderedBetween.associateBy { it.workoutComponentId!! }

    val items = mutableListOf<WorkoutHistoryLayoutItem>()

    for (component in workout.workoutComponents) {
        when (component) {
            is Exercise -> {
                if (setHistoriesByExerciseId[component.id].orEmpty().isNotEmpty()) {
                    items.add(WorkoutHistoryLayoutItem.ExerciseSection(component.id))
                }
            }
            is Superset -> {
                if (setHistoriesByExerciseId[component.id].orEmpty().isNotEmpty()) {
                    items.add(WorkoutHistoryLayoutItem.SupersetSection(component.id))
                }
            }
            is Rest -> {
                val history = historyByRestComponentId[component.id] ?: continue
                items.add(
                    WorkoutHistoryLayoutItem.RestSection(
                        restComponentId = component.id,
                        history = history
                    )
                )
            }
        }
    }

    return items
}
