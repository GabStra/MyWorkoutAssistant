package com.gabstra.myworkoutassistant.composables.workout.pages

import org.junit.Assert.assertEquals
import org.junit.Test

class PlatesPageSleeveGeometryTest {
    @Test
    fun `crops unused sleeve to plate thickness plus a small allowance`() {
        assertEquals(
            48f,
            displayedSleeveLogicalLength(
                physicalSleeveLength = 200f,
                maxPlateThickness = 40f,
            ),
            0f,
        )
    }

    @Test
    fun `never extends beyond the physical sleeve`() {
        assertEquals(
            200f,
            displayedSleeveLogicalLength(
                physicalSleeveLength = 200f,
                maxPlateThickness = 190f,
            ),
            0f,
        )
    }
}
