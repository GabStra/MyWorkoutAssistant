package com.gabstra.myworkoutassistant.shared.workout.assembly

import androidx.compose.runtime.mutableStateOf
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workout.state.ExerciseChildItem
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotSame
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.UUID

class WorkoutSetStateFactoryTest {

    @Test
    fun `buildUnilateralSetBlock creates distinct states for each side`() {
        val factory = WorkoutSetStateFactory()
        val exercise = Exercise(
            id = UUID.randomUUID(),
            enabled = true,
            name = "Dumbbell Curl",
            notes = "",
            sets = emptyList(),
            exerciseType = ExerciseType.WEIGHT,
            minLoadPercent = 0.0,
            maxLoadPercent = 0.0,
            minReps = 8,
            maxReps = 12,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = null,
            bodyWeightPercentage = null,
            generateWarmUpSets = false,
            keepScreenOn = false,
            showCountDownTimer = false,
            requiresLoadCalibration = false,
            intraSetRestInSeconds = 30
        )
        val setState = WorkoutState.Set(
            exerciseId = exercise.id,
            set = WeightSet(
                id = UUID.randomUUID(),
                reps = 10,
                weight = 12.5,
                subCategory = SetSubCategory.WorkSet
            ),
            setIndex = 1u,
            previousSetData = null,
            currentSetDataState = mutableStateOf(
                WeightSetData(
                    actualReps = 10,
                    actualWeight = 12.5,
                    volume = 125.0
                )
            ),
            hasNoHistory = true,
            skipped = false,
            currentBodyWeight = 0.0,
            streak = 0,
            progressionState = null,
            isWarmupSet = false,
            equipmentId = null
        )

        val block = factory.buildUnilateralSetBlock(
            exercise = exercise,
            setState = setState,
            setIndex = 1
        ) as ExerciseChildItem.UnilateralSetBlock

        val firstSide = block.childStates[0] as WorkoutState.Set
        val rest = block.childStates[1] as WorkoutState.Rest
        val secondSide = block.childStates[2] as WorkoutState.Set

        assertTrue(firstSide.isUnilateral)
        assertTrue(secondSide.isUnilateral)
        assertEquals(1u, firstSide.intraSetCounter)
        assertEquals(2u, secondSide.intraSetCounter)
        assertNotSame(firstSide, secondSide)
        assertSame(secondSide, rest.nextState)
    }
}
