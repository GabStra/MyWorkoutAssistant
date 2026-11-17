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
import org.junit.Assert.assertNull
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

    @Test
    fun `recurring history uses resolved current slot identity and leaves unmatched slots empty`() {
        val exerciseId = UUID.randomUUID()
        val currentSetId = UUID.randomUUID()
        val unmatchedSetId = UUID.randomUUID()
        val priorOccurrenceSetId = UUID.randomUUID()
        val historicalEquipmentId = UUID.randomUUID()
        val targetData = WeightSetData(actualReps = 9, actualWeight = 40.0, volume = 360.0)
        val historicalData = WeightSetData(actualReps = 8, actualWeight = 40.0, volume = 320.0)
        val resolvedState = WorkoutState.Set(
            exerciseId = exerciseId,
            set = WeightSet(id = currentSetId, reps = 9, weight = 40.0, subCategory = SetSubCategory.WorkSet),
            setIndex = 0u,
            previousSetData = null,
            currentSetDataState = mutableStateOf(targetData),
            historicalSetData = historicalData,
            hasNoHistory = false,
            skipped = false,
            currentBodyWeight = 0.0,
            streak = 0,
            progressionState = null,
            isWarmupSet = false,
            equipmentId = historicalEquipmentId,
        )
        val unmatchedState = resolvedState.copy(
            set = WeightSet(id = unmatchedSetId, reps = 9, weight = 40.0, subCategory = SetSubCategory.WorkSet),
            setIndex = 1u,
            currentSetDataState = mutableStateOf(targetData),
            historicalSetData = null,
            hasNoHistory = true,
            equipmentId = null,
        )
        val priorOccurrenceHistory = SetHistory(
            id = UUID.randomUUID(),
            workoutHistoryId = UUID.randomUUID(),
            exerciseId = UUID.randomUUID(),
            setId = priorOccurrenceSetId,
            order = 1u,
            startTime = null,
            endTime = null,
            setData = historicalData,
            skipped = false,
        )

        val historicalRows = buildHistoricalComparisonStates(
            templateStates = listOf(resolvedState, unmatchedState),
            histories = listOf(priorOccurrenceHistory),
        )

        assertEquals(listOf(currentSetId), historicalRows.map { it.set.id })
        assertEquals(historicalData, historicalRows.single().currentSetData)
        assertEquals(historicalEquipmentId, historicalRows.single().equipmentId)
        assertTrue(historicalRows.single().hasBeenExecuted)
        assertEquals(9, (resolvedState.set as WeightSet).reps)
        assertEquals(targetData, resolvedState.currentSetData)
    }

    @Test
    fun `imported strength set without timestamps still supplies comparison load`() {
        val exerciseId = UUID.randomUUID()
        val setId = UUID.randomUUID()
        val templateSetData = WeightSetData(actualReps = 5, actualWeight = 60.0, volume = 300.0)
        val importedSetData = WeightSetData(actualReps = 8, actualWeight = 72.5, volume = 580.0)
        val templateState = WorkoutState.Set(
            exerciseId = exerciseId,
            set = WeightSet(
                id = setId,
                reps = 5,
                weight = 60.0,
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
            equipmentId = null,
        )
        val importedHistory = SetHistory(
            id = UUID.randomUUID(),
            workoutHistoryId = UUID.randomUUID(),
            exerciseId = exerciseId,
            setId = setId,
            order = 1u,
            startTime = null,
            endTime = null,
            setData = importedSetData,
            skipped = false,
            exerciseNameSnapshot = "Reported machine press",
        )

        val historicalState = buildHistoricalComparisonStates(
            templateStates = listOf(templateState),
            histories = listOf(importedHistory),
        ).single()

        assertEquals(importedSetData, historicalState.currentSetData)
        assertNull(historicalState.startTime)
        assertTrue(canCompareProgressionSetData(historicalState.currentSetData, importedSetData))
    }
}
