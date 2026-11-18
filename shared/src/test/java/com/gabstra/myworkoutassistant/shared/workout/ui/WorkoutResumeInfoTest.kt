package com.gabstra.myworkoutassistant.shared.workout.ui

import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import java.util.UUID
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class WorkoutResumeInfoTest {

    private fun weightSet(subCategory: SetSubCategory): WeightSet = WeightSet(
        id = UUID.randomUUID(),
        reps = 5,
        weight = 50.0,
        subCategory = subCategory,
    )

    private fun restSet(): RestSet = RestSet(
        id = UUID.randomUUID(),
        timeInSeconds = 60,
    )

    private val mixedSets: List<Set> = listOf(
        weightSet(SetSubCategory.WarmupSet),
        weightSet(SetSubCategory.WarmupSet),
        weightSet(SetSubCategory.WorkSet),
        restSet(),
        weightSet(SetSubCategory.CalibrationSet),
        weightSet(SetSubCategory.RestPauseSet),
        weightSet(SetSubCategory.BackOffSet),
    )

    @Test
    fun resolveWorkoutResumeSetLabel_numbersWithinSetTypeUsingResumeIndex() {
        assertEquals(
            WorkoutResumeSetLabel(WorkoutResumeSetType.WARM_UP, setNumber = 2),
            resolveWorkoutResumeSetLabel(mixedSets, setIndex = 1u),
        )
        assertEquals(
            WorkoutResumeSetLabel(WorkoutResumeSetType.WORK, setNumber = 1),
            resolveWorkoutResumeSetLabel(mixedSets, setIndex = 2u),
        )
        assertEquals(
            WorkoutResumeSetLabel(WorkoutResumeSetType.CALIBRATION, setNumber = 1),
            resolveWorkoutResumeSetLabel(mixedSets, setIndex = 4u),
        )
        assertEquals(
            WorkoutResumeSetLabel(WorkoutResumeSetType.REST_PAUSE, setNumber = 1),
            resolveWorkoutResumeSetLabel(mixedSets, setIndex = 5u),
        )
        assertEquals(
            WorkoutResumeSetLabel(WorkoutResumeSetType.BACK_OFF, setNumber = 1),
            resolveWorkoutResumeSetLabel(mixedSets, setIndex = 6u),
        )
    }

    @Test
    fun resolveWorkoutResumeSetLabel_restKeepsItsTypeWithoutAnOrdinal() {
        val label = resolveWorkoutResumeSetLabel(mixedSets, setIndex = 3u)

        assertEquals(WorkoutResumeSetType.REST, label.type)
        assertNull(label.setNumber)
    }

    @Test
    fun resolveWorkoutResumeSetLabel_missingExerciseOrIndexFallsBackToFirstWorkSet() {
        val expected = WorkoutResumeSetLabel(WorkoutResumeSetType.WORK, setNumber = 1)

        assertEquals(expected, resolveWorkoutResumeSetLabel(sets = null, setIndex = 4u))
        assertEquals(expected, resolveWorkoutResumeSetLabel(mixedSets, setIndex = 99u))
    }

    @Test
    fun resolveWorkoutResumeSetLabel_calibrationPendingMapsToCalibration() {
        val sets = listOf(weightSet(SetSubCategory.CalibrationPendingSet))

        assertEquals(
            WorkoutResumeSetLabel(WorkoutResumeSetType.CALIBRATION, setNumber = 1),
            resolveWorkoutResumeSetLabel(sets, setIndex = 0u),
        )
    }
}
