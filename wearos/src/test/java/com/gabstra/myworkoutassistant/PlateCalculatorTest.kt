package com.gabstra.myworkoutassistant

import com.gabstra.myworkoutassistant.shared.utils.PlateCalculator
import org.junit.Assert.assertEquals
import org.junit.Test

class PlateCalculatorTest {
    @Test
    fun addition_isCorrect() {
        assertEquals(4, 2 + 2)
    }

    @Test
    fun plate_changes_is_correct(){
        val plates = listOf(20.0, 10.0, 5.0, 5.0, 5.0, 2.5,1.25,1.0,0.5,0.25)
        val sets = listOf(107.0, 107.0, 100.5)
        val barWeight = 9.0
        val initialSetup = emptyList<Double>()
        val results = PlateCalculator.calculatePlateChanges(plates, sets, barWeight, initialSetup)
        assertEquals(5, results.size)
    }

    @Test
    fun find_closest_combo_with_min_plates_and_changes(){
        val plates = listOf(20.0, 10.0, 5.0, 5.0, 5.0, 2.5,1.25,1.0,0.5,0.25)
        val totals = listOf(11.5, 18.0, 29.0)
        val barWeight = 9.0
        val initialSetup = emptyList<Double>()
        val results = PlateCalculator.closestAchievableWeights(plates, totals, barWeight, initialSetup)
        assertEquals(5, results.size)
    }
}