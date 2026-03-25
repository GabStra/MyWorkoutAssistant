package com.gabstra.myworkoutassistant

import androidx.compose.runtime.mutableStateOf
import com.gabstra.myworkoutassistant.data.WorkoutHistorySyncRequestMode
import com.gabstra.myworkoutassistant.data.resolveWorkoutHistorySyncRequestMode
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import org.junit.Assert.assertEquals
import org.junit.Test
import java.time.LocalDateTime
import java.util.UUID

class WorkoutHistorySyncRequestModeTest {

    @Test
    fun `completed workout requests immediate sync`() {
        val requestMode = resolveWorkoutHistorySyncRequestMode(
            currentState = WorkoutState.Completed(LocalDateTime.now()),
            isDone = true
        )

        assertEquals(WorkoutHistorySyncRequestMode.Immediate, requestMode)
    }

    @Test
    fun `set state requests debounced sync while workout is still active`() {
        val requestMode = resolveWorkoutHistorySyncRequestMode(
            currentState = createSetState(),
            isDone = false
        )

        assertEquals(WorkoutHistorySyncRequestMode.Debounced, requestMode)
    }

    @Test
    fun `rest state requests debounced sync while workout is still active`() {
        val requestMode = resolveWorkoutHistorySyncRequestMode(
            currentState = createRestState(),
            isDone = false
        )

        assertEquals(WorkoutHistorySyncRequestMode.Debounced, requestMode)
    }

    private fun createSetState(exerciseId: UUID = UUID.randomUUID()): WorkoutState.Set {
        val setData = WeightSetData(
            actualReps = 8,
            actualWeight = 60.0,
            volume = 480.0
        )
        return WorkoutState.Set(
            exerciseId = exerciseId,
            set = WeightSet(
                id = UUID.randomUUID(),
                reps = 8,
                weight = 60.0,
                subCategory = SetSubCategory.WorkSet
            ),
            setIndex = 1u,
            previousSetData = setData,
            currentSetDataState = mutableStateOf(setData),
            hasNoHistory = false,
            skipped = false,
            currentBodyWeight = 0.0,
            streak = 0,
            progressionState = null,
            isWarmupSet = false,
            equipmentId = null
        )
    }

    private fun createRestState(): WorkoutState.Rest {
        return WorkoutState.Rest(
            set = RestSet(
                id = UUID.randomUUID(),
                timeInSeconds = 90,
                subCategory = SetSubCategory.WorkSet
            ),
            order = 2u,
            currentSetDataState = mutableStateOf(
                RestSetData(
                    startTimer = 90,
                    endTimer = 90
                )
            ),
            exerciseId = UUID.randomUUID(),
            nextState = null
        )
    }
}
