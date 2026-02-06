package com.gabstra.myworkoutassistant.shared.workout.persistence

import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutStateQueries
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import java.time.LocalDateTime
import java.util.UUID

internal object WorkoutSetHistoryOps {
    fun shouldSkipPersistingState(
        state: WorkoutState,
        exercisesById: Map<UUID, Exercise>
    ): Boolean {
        val currentSet = WorkoutStateQueries.stateSetObjectOrNull(state) ?: return true
        if (currentSet is RestSet) return true

        if (state is WorkoutState.Rest && state.isIntraSetRest) {
            return true
        }

        if (state is WorkoutState.Set) {
            val exercise = exercisesById[state.exerciseId] ?: return true
            val isWarmupSet = isWarmupSet(state.set)
            val isCalibrationSet = isCalibrationSet(state.set)
            val hasCalibrationRIR = hasCalibrationRIR(state.currentSetData)

            if (exercise.doNotStoreHistory || isWarmupSet || (isCalibrationSet && !hasCalibrationRIR)) {
                return true
            }
        }

        return false
    }

    fun buildSetHistory(
        state: WorkoutState,
        historyIdentity: WorkoutStateQueries.StateHistoryIdentity
    ): SetHistory? {
        val setData = when (state) {
            is WorkoutState.Set -> state.currentSetData
            is WorkoutState.Rest -> state.currentSetData
            else -> return null
        }
        val startTime = when (state) {
            is WorkoutState.Set -> state.startTime ?: LocalDateTime.now()
            is WorkoutState.Rest -> state.startTime ?: LocalDateTime.now()
            else -> return null
        }
        val skipped = (state as? WorkoutState.Set)?.skipped ?: false

        return SetHistory(
            id = UUID.randomUUID(),
            setId = historyIdentity.setId,
            setData = setData,
            order = historyIdentity.order,
            skipped = skipped,
            exerciseId = historyIdentity.exerciseId,
            startTime = startTime,
            endTime = LocalDateTime.now()
        )
    }

    private fun isWarmupSet(set: Set): Boolean = when (set) {
        is BodyWeightSet -> set.subCategory == SetSubCategory.WarmupSet
        is WeightSet -> set.subCategory == SetSubCategory.WarmupSet
        else -> false
    }

    private fun isCalibrationSet(set: Set): Boolean = when (set) {
        is BodyWeightSet -> set.subCategory == SetSubCategory.CalibrationSet
        is WeightSet -> set.subCategory == SetSubCategory.CalibrationSet
        else -> false
    }

    private fun hasCalibrationRIR(setData: com.gabstra.myworkoutassistant.shared.setdata.SetData): Boolean = when (setData) {
        is WeightSetData -> setData.calibrationRIR != null
        is BodyWeightSetData -> setData.calibrationRIR != null
        else -> false
    }
}

