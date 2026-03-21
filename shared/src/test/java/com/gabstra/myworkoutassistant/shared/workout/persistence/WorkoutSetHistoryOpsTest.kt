package com.gabstra.myworkoutassistant.shared.workout.persistence

import androidx.compose.runtime.mutableStateOf
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.ProgressionMode
import com.gabstra.myworkoutassistant.shared.initializeSetData
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import java.util.UUID
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class WorkoutSetHistoryOpsTest {
    @Test
    fun `shouldSkipPersistingState skips top-level workout rest`() {
        val restSet = RestSet(id = UUID.randomUUID(), timeInSeconds = 60)
        val state = WorkoutState.Rest(
            set = restSet,
            order = 0u,
            currentSetDataState = mutableStateOf(initializeSetData(restSet)),
            exerciseId = null
        )

        assertTrue(WorkoutSetHistoryOps.shouldSkipPersistingState(state, emptyMap()))
    }

    @Test
    fun `shouldSkipPersistingState keeps exercise rest set history`() {
        val exerciseId = UUID.randomUUID()
        val restSet = RestSet(id = UUID.randomUUID(), timeInSeconds = 60)
        val exercise = Exercise(
            id = exerciseId,
            enabled = true,
            name = "Bench Press",
            doNotStoreHistory = false,
            notes = "",
            sets = listOf(restSet),
            exerciseType = ExerciseType.WEIGHT,
            minLoadPercent = 0.0,
            maxLoadPercent = 100.0,
            minReps = 5,
            maxReps = 10,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = UUID.randomUUID(),
            bodyWeightPercentage = null,
            generateWarmUpSets = false,
            progressionMode = ProgressionMode.DOUBLE_PROGRESSION,
            keepScreenOn = false,
            showCountDownTimer = false
        )
        val state = WorkoutState.Rest(
            set = restSet,
            order = 0u,
            currentSetDataState = mutableStateOf(initializeSetData(restSet)),
            exerciseId = exerciseId
        )

        assertFalse(WorkoutSetHistoryOps.shouldSkipPersistingState(state, mapOf(exerciseId to exercise)))
    }
}
