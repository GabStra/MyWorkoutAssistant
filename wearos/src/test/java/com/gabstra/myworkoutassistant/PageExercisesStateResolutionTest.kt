package com.gabstra.myworkoutassistant

import androidx.compose.runtime.mutableStateOf
import com.gabstra.myworkoutassistant.composables.resolvePageExercisesActiveState
import com.gabstra.myworkoutassistant.composables.toExerciseSetDisplayRowOrNull
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Test
import java.util.UUID

class PageExercisesStateResolutionTest {

    @Test
    fun `rest state resolves to next executable state for exercises page`() {
        val upcomingSetState = createSetState()
        val restState = createRestState(nextState = upcomingSetState)

        val resolvedState = resolvePageExercisesActiveState(workoutState = restState)

        assertSame(upcomingSetState, resolvedState)
    }

    @Test
    fun `rest state falls back to provided set state when next state is missing`() {
        val fallbackSetState = createSetState()
        val restState = createRestState(nextState = null)

        val resolvedState = resolvePageExercisesActiveState(
            workoutState = restState,
            fallbackSetState = fallbackSetState
        )

        assertSame(fallbackSetState, resolvedState)
    }

    @Test
    fun `rest state resolves to same exercise next set for exercises page`() {
        val exerciseId = UUID.randomUUID()
        val upcomingSetState = createSetState(exerciseId = exerciseId)
        val restState = createRestState(
            exerciseId = exerciseId,
            nextState = upcomingSetState
        )

        val resolvedState = resolvePageExercisesActiveState(workoutState = restState)

        assertSame(upcomingSetState, resolvedState)
    }

    @Test
    fun `rest states are omitted from exercise display rows`() {
        val restState = createRestState(nextState = null)

        val displayRow = toExerciseSetDisplayRowOrNull(restState)

        assertNull(displayRow)
    }

    @Test
    fun `non rest state remains unchanged`() {
        val setState = createSetState()

        val resolvedState = resolvePageExercisesActiveState(workoutState = setState)

        assertSame(setState, resolvedState)
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

    private fun createRestState(
        nextState: WorkoutState?,
        exerciseId: UUID = UUID.randomUUID(),
    ): WorkoutState.Rest {
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
            exerciseId = exerciseId,
            nextState = nextState
        )
    }
}
