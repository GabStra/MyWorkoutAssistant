package com.gabstra.myworkoutassistant.shared.workout.persistence

import androidx.compose.runtime.mutableStateOf
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.ProgressionMode
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutStateQueries
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import java.util.UUID
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class WorkoutSetHistoryOpsTest {

    private val exerciseId = UUID.randomUUID()

    @Test
    fun shouldSkipPersistingState_skipsRest() {
        val restSet = RestSet(UUID.randomUUID(), 90, SetSubCategory.WorkSet)
        val restState = WorkoutState.Rest(
            set = restSet,
            order = 0u,
            currentSetDataState = mutableStateOf(RestSetData(90, 90, SetSubCategory.WorkSet)),
            exerciseId = exerciseId,
            isIntraSetRest = false
        )
        assertTrue(
            WorkoutSetHistoryOps.shouldSkipPersistingState(
                restState,
                emptyMap()
            )
        )
    }

    @Test
    fun shouldSkipPersistingState_doesNotSkipWeightWorkSet() {
        val setId = UUID.randomUUID()
        val exId = UUID.randomUUID()
        val equipmentId = UUID.randomUUID()
        val exercise = Exercise(
            id = exId,
            enabled = true,
            name = "Squat",
            notes = "",
            sets = listOf(WeightSet(setId, 5, 100.0)),
            exerciseType = ExerciseType.WEIGHT,
            minLoadPercent = 0.0,
            maxLoadPercent = 100.0,
            minReps = 5,
            maxReps = 10,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = equipmentId,
            bodyWeightPercentage = null,
            generateWarmUpSets = false,
            progressionMode = ProgressionMode.OFF,
            keepScreenOn = false,
            showCountDownTimer = false,
            intraSetRestInSeconds = null,
            loadJumpDefaultPct = null,
            loadJumpMaxPct = null,
            loadJumpOvercapUntil = null
        )
        val setState = WorkoutState.Set(
            exerciseId = exId,
            set = WeightSet(setId, 5, 100.0),
            setIndex = 0u,
            previousSetData = null,
            currentSetDataState = mutableStateOf(WeightSetData(5, 100.0, 500.0)),
            hasNoHistory = false,
            startTime = null,
            skipped = false,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            currentBodyWeight = 75.0,
            plateChangeResult = null,
            streak = 0,
            progressionState = null,
            isWarmupSet = false,
            equipmentId = equipmentId,
            isUnilateral = false,
            intraSetTotal = null,
            intraSetCounter = 0u,
            isCalibrationSet = false
        )
        assertFalse(
            WorkoutSetHistoryOps.shouldSkipPersistingState(
                setState,
                mapOf(exId to exercise)
            )
        )
    }

    @Test
    fun shouldSkipPersistingState_doesNotSkipWeightWarmupSet() {
        val setId = UUID.randomUUID()
        val exId = UUID.randomUUID()
        val equipmentId = UUID.randomUUID()
        val exercise = Exercise(
            id = exId,
            enabled = true,
            name = "Bench Press",
            notes = "",
            sets = listOf(WeightSet(setId, 8, 60.0, subCategory = SetSubCategory.WarmupSet)),
            exerciseType = ExerciseType.WEIGHT,
            minLoadPercent = 0.0,
            maxLoadPercent = 100.0,
            minReps = 5,
            maxReps = 10,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = equipmentId,
            bodyWeightPercentage = null,
            generateWarmUpSets = false,
            progressionMode = ProgressionMode.OFF,
            keepScreenOn = false,
            showCountDownTimer = false,
            intraSetRestInSeconds = null,
            loadJumpDefaultPct = null,
            loadJumpMaxPct = null,
            loadJumpOvercapUntil = null
        )
        val setState = WorkoutState.Set(
            exerciseId = exId,
            set = WeightSet(setId, 8, 60.0, subCategory = SetSubCategory.WarmupSet),
            setIndex = 0u,
            previousSetData = null,
            currentSetDataState = mutableStateOf(
                WeightSetData(
                    actualReps = 8,
                    actualWeight = 60.0,
                    volume = 480.0,
                    subCategory = SetSubCategory.WarmupSet
                )
            ),
            hasNoHistory = false,
            startTime = null,
            skipped = false,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            currentBodyWeight = 75.0,
            plateChangeResult = null,
            streak = 0,
            progressionState = null,
            isWarmupSet = true,
            equipmentId = equipmentId,
            isUnilateral = false,
            intraSetTotal = null,
            intraSetCounter = 0u,
            isCalibrationSet = false
        )

        assertFalse(
            WorkoutSetHistoryOps.shouldSkipPersistingState(
                setState,
                mapOf(exId to exercise)
            )
        )
    }

    @Test
    fun buildSetHistory_returnsNullForRest() {
        val restSet = RestSet(UUID.randomUUID(), 90, SetSubCategory.WorkSet)
        val restState = WorkoutState.Rest(
            set = restSet,
            order = 0u,
            currentSetDataState = mutableStateOf(RestSetData(90, 90, SetSubCategory.WorkSet)),
            exerciseId = exerciseId,
            isIntraSetRest = false
        )
        assertNull(
            WorkoutSetHistoryOps.buildSetHistory(
                restState,
                WorkoutStateQueries.StateHistoryIdentity(
                    setId = UUID.randomUUID(),
                    order = 0u,
                    exerciseId = exerciseId
                )
            )
        )
    }
}
