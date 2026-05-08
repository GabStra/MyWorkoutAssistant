package com.gabstra.myworkoutassistant.shared.workout.session

import androidx.compose.runtime.mutableStateOf
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.ProgressionMode
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.WorkoutRecord
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workout.state.ProgressionState
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDateTime
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

    @Test
    fun findResumptionIndex_whenGeneratedSetIdsChange_matchesByExerciseAndOrder() {
        val exerciseId = UUID.randomUUID()
        val originalWarmupSetId = UUID.randomUUID()
        val rebuiltWarmupSetId = UUID.randomUUID()
        val rebuiltWorkSetId = UUID.randomUUID()
        val workoutHistoryId = UUID.randomUUID()
        val now = LocalDateTime.now()

        val states = listOf(
            createSetState(exerciseId = exerciseId, setId = rebuiltWarmupSetId, setIndex = 0u, isWarmupSet = true),
            createSetState(exerciseId = exerciseId, setId = rebuiltWorkSetId, setIndex = 2u)
        )
        val history = listOf(
            SetHistory(
                id = UUID.randomUUID(),
                workoutHistoryId = workoutHistoryId,
                exerciseId = exerciseId,
                setId = originalWarmupSetId,
                order = 0u,
                startTime = now,
                endTime = now,
                setData = WeightSetData(
                    actualReps = 5,
                    actualWeight = 20.0,
                    volume = 100.0,
                    subCategory = SetSubCategory.WarmupSet
                ),
                skipped = false
            )
        )

        val result = service.findResumptionIndex(
            allWorkoutStates = states,
            executedSetsHistorySnapshot = history,
            workoutRecord = null,
            exercisesById = mapOf(exerciseId to createExercise(exerciseId))
        )

        assertEquals(1, result.index)
        assertTrue(result.workoutRecordMatchedTemplate)
    }

    private fun createSetState(
        exerciseId: UUID,
        setId: UUID,
        setIndex: UInt,
        isWarmupSet: Boolean = false
    ): WorkoutState.Set {
        val subCategory = if (isWarmupSet) SetSubCategory.WarmupSet else SetSubCategory.WorkSet
        val setData = WeightSetData(
            actualReps = 5,
            actualWeight = 20.0,
            volume = 100.0,
            subCategory = subCategory
        )
        return WorkoutState.Set(
            exerciseId = exerciseId,
            set = WeightSet(
                id = setId,
                reps = 5,
                weight = 20.0,
                subCategory = subCategory
            ),
            setIndex = setIndex,
            previousSetData = null,
            currentSetDataState = mutableStateOf(setData),
            historicalSetData = null,
            hasNoHistory = false,
            startTime = null,
            skipped = false,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            currentBodyWeight = 0.0,
            plateChangeResult = null,
            streak = 0,
            progressionState = ProgressionState.PROGRESS,
            isWarmupSet = isWarmupSet,
            equipmentId = null
        )
    }

    private fun createExercise(exerciseId: UUID): Exercise = Exercise(
        id = exerciseId,
        enabled = true,
        name = "Test Exercise",
        notes = "",
        sets = emptyList(),
        exerciseType = ExerciseType.WEIGHT,
        minLoadPercent = 0.0,
        maxLoadPercent = 100.0,
        minReps = 1,
        maxReps = 10,
        lowerBoundMaxHRPercent = null,
        upperBoundMaxHRPercent = null,
        equipmentId = null,
        bodyWeightPercentage = null,
        generateWarmUpSets = true,
        progressionMode = ProgressionMode.OFF
    )
}
