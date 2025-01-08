package com.gabstra.myworkoutassistant

import com.gabstra.myworkoutassistant.shared.utils.PlateCalculator
import org.junit.Test
import org.junit.Assert.*

class PlateCalculatorTest {
    @Test
    fun addition_isCorrect() {
        assertEquals(4, 2 + 2)
    }

    @Test
    fun plate_changes_is_correct(){
        val plates = listOf(20.0, 10.0, 5.0, 5.0, 5.0, 2.5,1.25,1.0,0.5,0.25)
        val sets = listOf(70.0, 60.0, 65.0, 60.0)
        val barWeight = 9.0
        val initialSetup = listOf(10.0,20.0)
        val multiplier = 2.0
        val results = PlateCalculator.calculatePlateChanges(plates, sets, barWeight, initialSetup, multiplier)
        assertEquals(5, results.size)
    }
}