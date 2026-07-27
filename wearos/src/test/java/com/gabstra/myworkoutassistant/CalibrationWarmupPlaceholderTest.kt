package com.gabstra.myworkoutassistant

import androidx.compose.runtime.mutableStateOf
import com.gabstra.myworkoutassistant.composables.buildCalibrationWarmupPlaceholderSetIdentifier
import com.gabstra.myworkoutassistant.composables.expandCalibrationWarmupPlaceholderSlots
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workout.display.ExerciseSetDisplayRow
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.UUID

class CalibrationWarmupPlaceholderTest {

    @Test
    fun `standalone calibration warmup placeholder has no exercise prefix`() {
        assertEquals(
            "W?",
            buildCalibrationWarmupPlaceholderSetIdentifier(supersetPrefix = null),
        )
    }

    @Test
    fun `superset calibration warmup placeholder identifies its exercise`() {
        assertEquals(
            "B · W?",
            buildCalibrationWarmupPlaceholderSetIdentifier(supersetPrefix = "B"),
        )
    }

    @Test
    fun `every unconfirmed calibration exercise in a superset gets a placeholder`() {
        val firstExerciseId = UUID.randomUUID()
        val secondExerciseId = UUID.randomUUID()
        val displayRows = listOf(
            calibrationLoadRow(firstExerciseId),
            calibrationLoadRow(secondExerciseId),
        )

        val slots = expandCalibrationWarmupPlaceholderSlots(displayRows)
        val placeholderExerciseIds = slots
            .filter { it.isWarmupPlaceholder }
            .map {
                (it.displayRow as ExerciseSetDisplayRow.CalibrationLoadSelectRow).state.exerciseId
            }

        assertEquals(listOf(firstExerciseId, secondExerciseId), placeholderExerciseIds)
        assertEquals(listOf(false, true, false, true), slots.map { it.isWarmupPlaceholder })
        assertTrue(slots.all { it.sourceRowIndex in displayRows.indices })
    }

    private fun calibrationLoadRow(
        exerciseId: UUID,
    ): ExerciseSetDisplayRow.CalibrationLoadSelectRow {
        val calibrationSet = WeightSet(
            id = UUID.randomUUID(),
            reps = 5,
            weight = 0.0,
            subCategory = SetSubCategory.CalibrationSet,
        )
        val setData = WeightSetData(
            actualReps = 5,
            actualWeight = 0.0,
            volume = 0.0,
            subCategory = SetSubCategory.CalibrationSet,
        )
        return ExerciseSetDisplayRow.CalibrationLoadSelectRow(
            WorkoutState.CalibrationLoadSelection(
                exerciseId = exerciseId,
                calibrationSet = calibrationSet,
                setIndex = 0u,
                previousSetData = null,
                currentSetDataState = mutableStateOf(setData),
                equipmentId = null,
                currentBodyWeight = 80.0,
            )
        )
    }
}
