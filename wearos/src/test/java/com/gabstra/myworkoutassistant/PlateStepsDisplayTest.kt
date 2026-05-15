package com.gabstra.myworkoutassistant

import com.gabstra.myworkoutassistant.composables.PlateUiStep
import com.gabstra.myworkoutassistant.composables.applyPlateUiSteps
import com.gabstra.myworkoutassistant.composables.navigablePlateUiSteps
import com.gabstra.myworkoutassistant.composables.squashPlateStepsForDisplay
import com.gabstra.myworkoutassistant.shared.utils.PlateCalculator
import org.junit.Assert.assertEquals
import org.junit.Test

class PlateStepsDisplayTest {

    private fun plateChangeResult(
        previous: List<Double>,
        current: List<Double>,
        steps: List<PlateCalculator.Companion.PlateStep>,
    ): PlateCalculator.Companion.PlateChangeResult {
        return PlateCalculator.Companion.PlateChangeResult(
            change = PlateCalculator.Companion.PlateChange(
                from = previous.sum(),
                to = current.sum(),
                steps = steps,
            ),
            previousPlates = previous,
            currentPlates = current,
        )
    }

    @Test
    fun squashPlateStepsForDisplay_mergesConsecutiveAdds() {
        val previous = listOf(20.0)
        val steps = listOf(
            PlateCalculator.Companion.PlateStep(PlateCalculator.Companion.Action.ADD, 10.0),
            PlateCalculator.Companion.PlateStep(PlateCalculator.Companion.Action.ADD, 5.0),
        )
        val squashed = squashPlateStepsForDisplay(steps, previous)

        assertEquals(1, squashed.size)
        assertEquals(PlateCalculator.Companion.Action.ADD, squashed[0].action)
        assertEquals(listOf(10.0, 5.0), squashed[0].weights)
        assertEquals(
            listOf(20.0, 10.0, 5.0),
            applyPlateUiSteps(previous, squashed, stepCount = 1),
        )
    }

    @Test
    fun squashPlateStepsForDisplay_mergesConsecutiveOuterRemoves() {
        val previous = listOf(20.0, 10.0, 5.0)
        val steps = listOf(
            PlateCalculator.Companion.PlateStep(PlateCalculator.Companion.Action.REMOVE, 5.0),
            PlateCalculator.Companion.PlateStep(PlateCalculator.Companion.Action.REMOVE, 10.0),
        )
        val squashed = squashPlateStepsForDisplay(steps, previous)

        assertEquals(1, squashed.size)
        assertEquals(PlateCalculator.Companion.Action.REMOVE, squashed[0].action)
        assertEquals(listOf(5.0, 10.0), squashed[0].weights)
        assertEquals(listOf(20.0), applyPlateUiSteps(previous, squashed, stepCount = 1))
    }

    @Test
    fun squashPlateStepsForDisplay_doesNotMergeNonAdjacentAdds() {
        val previous = listOf(20.0, 10.0, 5.0)
        val steps = listOf(
            PlateCalculator.Companion.PlateStep(PlateCalculator.Companion.Action.ADD, 20.0),
            PlateCalculator.Companion.PlateStep(PlateCalculator.Companion.Action.ADD, 5.0),
        )
        val squashed = squashPlateStepsForDisplay(steps, previous)

        assertEquals(2, squashed.size)
        assertEquals(listOf(20.0), squashed[0].weights)
        assertEquals(listOf(5.0), squashed[1].weights)
    }

    @Test
    fun squashPlateStepsForDisplay_doesNotMergeNonOuterRemoves() {
        val previous = listOf(20.0, 10.0, 5.0)
        val steps = listOf(
            PlateCalculator.Companion.PlateStep(PlateCalculator.Companion.Action.REMOVE, 20.0),
            PlateCalculator.Companion.PlateStep(PlateCalculator.Companion.Action.REMOVE, 10.0),
        )
        val squashed = squashPlateStepsForDisplay(steps, previous)

        assertEquals(2, squashed.size)
        assertEquals(listOf(20.0), squashed[0].weights)
        assertEquals(listOf(10.0), squashed[1].weights)
    }

    @Test
    fun navigablePlateUiSteps_filtersNoOpSteps() {
        val result = plateChangeResult(
            previous = listOf(20.0),
            current = listOf(20.0, 10.0),
            steps = listOf(
                PlateCalculator.Companion.PlateStep(PlateCalculator.Companion.Action.ADD, 10.0),
                PlateCalculator.Companion.PlateStep(PlateCalculator.Companion.Action.REMOVE, 99.0),
            ),
        )

        val uiSteps = navigablePlateUiSteps(result)
        assertEquals(1, uiSteps.size)
        assertEquals(
            PlateUiStep(PlateCalculator.Companion.Action.ADD, listOf(10.0)),
            uiSteps.single(),
        )
    }
}
