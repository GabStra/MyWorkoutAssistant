package com.gabstra.myworkoutassistant.shared.workout.persistence

import com.gabstra.myworkoutassistant.shared.RestHistoryScope
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import java.util.UUID

internal object WorkoutRestHistoryOps {
    fun shouldSkipPersistingRest(
        state: WorkoutState.Rest,
        exercisesById: Map<UUID, Exercise>
    ): Boolean {
        if (state.set !is RestSet) return true

        val scope = if (state.isIntraSetRest) {
            RestHistoryScope.INTRA_EXERCISE
        } else {
            RestHistoryScope.BETWEEN_WORKOUT_COMPONENTS
        }

        if (scope == RestHistoryScope.INTRA_EXERCISE) {
            val exerciseId = state.exerciseId ?: return true
            exercisesById[exerciseId] ?: return true
        }

        return false
    }
}
