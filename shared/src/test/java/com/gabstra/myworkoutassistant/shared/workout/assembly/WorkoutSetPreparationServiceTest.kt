package com.gabstra.myworkoutassistant.shared.workout.assembly

import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.ProgressionMode
import com.gabstra.myworkoutassistant.shared.equipments.BaseWeight
import com.gabstra.myworkoutassistant.shared.equipments.Machine
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.UUID

class WorkoutSetPreparationServiceTest {

    @Test
    fun `auto regulation exercise keeps calibration before progression takes over`() {
        val equipment = Machine(
            id = UUID.randomUUID(),
            name = "Machine",
            availableWeights = listOf(BaseWeight(20.0), BaseWeight(25.0))
        )
        val workSet = WeightSet(
            id = UUID.randomUUID(),
            reps = 10,
            weight = 20.0,
            subCategory = SetSubCategory.CalibrationPendingSet
        )
        val exercise = Exercise(
            id = UUID.randomUUID(),
            enabled = true,
            name = "Calibration press",
            notes = "",
            sets = listOf(workSet),
            exerciseType = ExerciseType.WEIGHT,
            minReps = 8,
            maxReps = 12,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = equipment.id,
            bodyWeightPercentage = null,
            progressionMode = ProgressionMode.AUTO_REGULATION,
            requiresLoadCalibration = true
        )

        val preparedSets = WorkoutSetPreparationService().prepareExerciseSets(
            exercise = exercise,
            priorExercises = emptyList(),
            equipment = equipment,
            bodyWeightKg = 70.0,
            getAvailableTotals = { it.getWeightsCombinationsNoExtra() }
        )

        assertEquals(2, preparedSets.size)
        assertTrue(
            preparedSets.first() is WeightSet &&
                (preparedSets.first() as WeightSet).subCategory == SetSubCategory.CalibrationSet
        )
        assertEquals(workSet, preparedSets.last())
    }
}
