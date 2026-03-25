package com.gabstra.myworkoutassistant.shared.workout.session

import com.gabstra.myworkoutassistant.shared.WorkoutRecord
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.UUID

class WorkoutResumptionServiceTest {

    private val service = WorkoutResumptionService()

    @Test
    fun findResumptionIndex_whenRecordDoesNotMatchEmptyTemplate_flagsMismatch() {
        val exerciseId = UUID.randomUUID()
        val record = WorkoutRecord(
            id = UUID.randomUUID(),
            workoutId = UUID.randomUUID(),
            workoutHistoryId = UUID.randomUUID(),
            setIndex = 99u,
            exerciseId = exerciseId,
        )
        val result = service.findResumptionIndex(
            allWorkoutStates = emptyList(),
            executedSetsHistorySnapshot = emptyList(),
            workoutRecord = record,
            exercisesById = emptyMap()
        )
        assertEquals(0, result.index)
        assertFalse(result.workoutRecordMatchedTemplate)
    }

    @Test
    fun recordMatchesWorkoutStates_whenNoStates_returnsFalse() {
        val record = WorkoutRecord(
            id = UUID.randomUUID(),
            workoutId = UUID.randomUUID(),
            workoutHistoryId = UUID.randomUUID(),
            setIndex = 0u,
            exerciseId = UUID.randomUUID(),
        )
        assertFalse(service.recordMatchesWorkoutStates(record, emptyList()))
    }

    @Test
    fun findResumptionIndex_whenNoRecord_andNoStates_matchedFlagTrue() {
        val result = service.findResumptionIndex(
            allWorkoutStates = emptyList(),
            executedSetsHistorySnapshot = emptyList(),
            workoutRecord = null,
            exercisesById = emptyMap()
        )
        assertEquals(0, result.index)
        assertTrue(result.workoutRecordMatchedTemplate)
    }
}
