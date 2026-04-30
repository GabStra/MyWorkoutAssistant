package com.gabstra.myworkoutassistant

import androidx.compose.runtime.mutableStateOf
import com.gabstra.myworkoutassistant.composables.buildSetTrendIndicator
import com.gabstra.myworkoutassistant.composables.resolveSetTrendIndicator
import com.gabstra.myworkoutassistant.composables.userEditedTrendForReps
import com.gabstra.myworkoutassistant.composables.userEditedTrendForTime
import com.gabstra.myworkoutassistant.composables.userEditedTrendForWeight
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.setdata.SetData
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import java.util.UUID

class ExerciseSetsViewerTrendIndicatorTest {

    @Test
    fun `work weight set shows better trend when reps increase`() {
        val state = createWeightSetState(
            previous = WeightSetData(actualReps = 8, actualWeight = 60.0, volume = 480.0),
            current = WeightSetData(actualReps = 9, actualWeight = 60.0, volume = 540.0),
            hasBeenExecuted = false
        )

        val indicator = resolveSetTrendIndicator(state)

        checkNotNull(indicator)
        assertEquals("↑", indicator.glyph)
    }

    @Test
    fun `work weight set shows better trend when weight increases`() {
        val state = createWeightSetState(
            previous = WeightSetData(actualReps = 8, actualWeight = 60.0, volume = 480.0),
            current = WeightSetData(actualReps = 8, actualWeight = 62.5, volume = 500.0),
            hasBeenExecuted = false
        )

        val indicator = resolveSetTrendIndicator(state)

        checkNotNull(indicator)
        assertEquals("↑", indicator.glyph)
    }

    @Test
    fun `work bodyweight set shows worse trend when reps decrease`() {
        val state = createBodyWeightSetState(
            previous = BodyWeightSetData(
                actualReps = 10,
                additionalWeight = 10.0,
                relativeBodyWeightInKg = 70.0,
                volume = 800.0
            ),
            current = BodyWeightSetData(
                actualReps = 8,
                additionalWeight = 10.0,
                relativeBodyWeightInKg = 70.0,
                volume = 640.0
            ),
            hasBeenExecuted = false
        )

        val indicator = resolveSetTrendIndicator(state)

        checkNotNull(indicator)
        assertEquals("↓", indicator.glyph)
    }

    @Test
    fun `warmup sets do not show trend indicator`() {
        val state = createWeightSetState(
            previous = WeightSetData(actualReps = 8, actualWeight = 60.0, volume = 480.0),
            current = WeightSetData(actualReps = 9, actualWeight = 60.0, volume = 540.0),
            subCategory = SetSubCategory.WarmupSet
        )

        assertNull(resolveSetTrendIndicator(state))
    }

    @Test
    fun `equal values do not show trend indicator`() {
        val state = createWeightSetState(
            previous = WeightSetData(actualReps = 8, actualWeight = 60.0, volume = 480.0),
            current = WeightSetData(actualReps = 8, actualWeight = 60.0, volume = 480.0)
        )

        assertNull(buildSetTrendIndicator(state))
    }

    @Test
    fun `weight set reports user edits when reps change from previous set data`() {
        val state = createWeightSetState(
            previous = WeightSetData(actualReps = 8, actualWeight = 60.0, volume = 480.0),
            current = WeightSetData(actualReps = 9, actualWeight = 60.0, volume = 540.0)
        )

        assertEquals("↑", userEditedTrendForReps(state)?.glyph)
    }

    @Test
    fun `timed duration set reports user edits when duration changes from previous set data`() {
        val state = createTimerSetState(
            set = TimedDurationSet(UUID.randomUUID(), timeInMillis = 60_000, autoStart = true, autoStop = true),
            previous = TimedDurationSetData(
                startTimer = 60_000,
                endTimer = 60_000,
                autoStart = true,
                autoStop = true
            ),
            current = TimedDurationSetData(
                startTimer = 45_000,
                endTimer = 45_000,
                autoStart = true,
                autoStop = true
            )
        )

        assertEquals("↓", userEditedTrendForTime(state)?.glyph)
    }

    @Test
    fun `endurance set returns no icon when duration matches previous set data`() {
        val state = createTimerSetState(
            set = EnduranceSet(UUID.randomUUID(), timeInMillis = 60_000, autoStart = true, autoStop = false),
            previous = EnduranceSetData(
                startTimer = 60_000,
                endTimer = 15_000,
                autoStart = true,
                autoStop = false
            ),
            current = EnduranceSetData(
                startTimer = 60_000,
                endTimer = 15_000,
                autoStart = true,
                autoStop = false
            )
        )

        assertNull(userEditedTrendForTime(state))
    }

    @Test
    fun `bodyweight set shows lower icon when additional weight is reduced from previous set data`() {
        val state = createBodyWeightSetState(
            previous = BodyWeightSetData(
                actualReps = 10,
                additionalWeight = 10.0,
                relativeBodyWeightInKg = 70.0,
                volume = 800.0
            ),
            current = BodyWeightSetData(
                actualReps = 10,
                additionalWeight = 5.0,
                relativeBodyWeightInKg = 70.0,
                volume = 750.0
            )
        )

        assertEquals("↓", userEditedTrendForWeight(state)?.glyph)
    }

    private fun createWeightSetState(
        previous: WeightSetData,
        current: WeightSetData,
        subCategory: SetSubCategory = SetSubCategory.WorkSet,
        hasBeenExecuted: Boolean = false,
    ): WorkoutState.Set {
        return WorkoutState.Set(
            exerciseId = UUID.randomUUID(),
            set = WeightSet(
                id = UUID.randomUUID(),
                reps = previous.actualReps,
                weight = previous.actualWeight,
                subCategory = subCategory
            ),
            setIndex = 0u,
            previousSetData = previous,
            currentSetDataState = mutableStateOf(current),
            historicalSetData = previous,
            hasNoHistory = false,
            skipped = false,
            currentBodyWeight = 0.0,
            streak = 0,
            progressionState = null,
            isWarmupSet = subCategory == SetSubCategory.WarmupSet,
            equipmentId = null,
            hasBeenExecuted = hasBeenExecuted
        )
    }

    private fun createBodyWeightSetState(
        previous: BodyWeightSetData,
        current: BodyWeightSetData,
        subCategory: SetSubCategory = SetSubCategory.WorkSet,
        hasBeenExecuted: Boolean = false,
    ): WorkoutState.Set {
        return WorkoutState.Set(
            exerciseId = UUID.randomUUID(),
            set = BodyWeightSet(
                id = UUID.randomUUID(),
                reps = previous.actualReps,
                additionalWeight = previous.additionalWeight,
                subCategory = subCategory
            ),
            setIndex = 0u,
            previousSetData = previous,
            currentSetDataState = mutableStateOf(current),
            historicalSetData = previous,
            hasNoHistory = false,
            skipped = false,
            currentBodyWeight = previous.relativeBodyWeightInKg,
            streak = 0,
            progressionState = null,
            isWarmupSet = subCategory == SetSubCategory.WarmupSet,
            equipmentId = null,
            hasBeenExecuted = hasBeenExecuted
        )
    }

    private fun createTimerSetState(
        set: Set,
        previous: SetData? = null,
        current: SetData,
    ): WorkoutState.Set {
        return WorkoutState.Set(
            exerciseId = UUID.randomUUID(),
            set = set,
            setIndex = 0u,
            previousSetData = previous,
            currentSetDataState = mutableStateOf(current),
            historicalSetData = previous,
            hasNoHistory = false,
            skipped = false,
            currentBodyWeight = 0.0,
            streak = 0,
            progressionState = null,
            isWarmupSet = false,
            equipmentId = null,
            hasBeenExecuted = false
        )
    }
}
