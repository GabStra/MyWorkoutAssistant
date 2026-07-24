package com.gabstra.myworkoutassistant.composables.workout.pages

import androidx.compose.runtime.mutableStateOf
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import org.junit.Assert.assertFalse
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDateTime
import java.util.UUID

class ProgressionComparisonPageLogicTest {
    @Test
    fun `matching supported set data can be compared`() {
        assertTrue(
            canCompareProgressionSetData(
                WeightSetData(actualReps = 8, actualWeight = 80.0, volume = 640.0),
                WeightSetData(actualReps = 9, actualWeight = 80.0, volume = 720.0),
            )
        )
        assertTrue(
            canCompareProgressionSetData(
                BodyWeightSetData(
                    actualReps = 8,
                    additionalWeight = 0.0,
                    relativeBodyWeightInKg = 75.0,
                    volume = 600.0,
                ),
                BodyWeightSetData(
                    actualReps = 9,
                    additionalWeight = 0.0,
                    relativeBodyWeightInKg = 75.0,
                    volume = 675.0,
                ),
            )
        )
        assertTrue(
            canCompareProgressionSetData(
                EnduranceSetData(startTimer = 0, endTimer = 60_000, autoStart = false, autoStop = false),
                EnduranceSetData(startTimer = 0, endTimer = 65_000, autoStart = false, autoStop = false),
            )
        )
        assertTrue(
            canCompareProgressionSetData(
                TimedDurationSetData(startTimer = 0, endTimer = 60_000, autoStart = false, autoStop = false),
                TimedDurationSetData(startTimer = 0, endTimer = 65_000, autoStart = false, autoStop = false),
            )
        )
    }

    @Test
    fun `missing or mismatched set data is not reported as equal`() {
        val weightData = WeightSetData(actualReps = 8, actualWeight = 80.0, volume = 640.0)
        val enduranceData = EnduranceSetData(
            startTimer = 0,
            endTimer = 60_000,
            autoStart = false,
            autoStop = false,
        )

        assertFalse(canCompareProgressionSetData(null, weightData))
        assertFalse(canCompareProgressionSetData(weightData, null))
        assertFalse(canCompareProgressionSetData(weightData, enduranceData))
    }

    @Test
    fun `historical row uses executed data and equipment snapshot`() {
        val exerciseId = UUID.randomUUID()
        val setId = UUID.randomUUID()
        val templateEquipmentId = UUID.randomUUID()
        val historicalEquipmentId = UUID.randomUUID()
        val templateSetData = WeightSetData(actualReps = 8, actualWeight = 80.0, volume = 640.0)
        val executedSetData = WeightSetData(actualReps = 10, actualWeight = 82.5, volume = 825.0)
        val templateState = WorkoutState.Set(
            exerciseId = exerciseId,
            set = WeightSet(
                id = setId,
                reps = 8,
                weight = 80.0,
                subCategory = SetSubCategory.WorkSet,
            ),
            setIndex = 1u,
            previousSetData = null,
            currentSetDataState = mutableStateOf(templateSetData),
            hasNoHistory = true,
            skipped = false,
            currentBodyWeight = 0.0,
            streak = 0,
            progressionState = null,
            isWarmupSet = false,
            equipmentId = templateEquipmentId,
        )
        val history = SetHistory(
            id = UUID.randomUUID(),
            workoutHistoryId = UUID.randomUUID(),
            exerciseId = exerciseId,
            equipmentIdSnapshot = historicalEquipmentId,
            setId = setId,
            order = 1u,
            startTime = LocalDateTime.now().minusMinutes(1),
            endTime = LocalDateTime.now(),
            setData = executedSetData,
            skipped = false,
        )

        val historicalState = buildHistoricalComparisonStates(
            templateStates = listOf(templateState),
            histories = listOf(history),
        ).single()

        assertEquals(executedSetData, historicalState.currentSetData)
        assertEquals(historicalEquipmentId, historicalState.equipmentId)
        assertTrue(historicalState.hasBeenExecuted)
    }
}
