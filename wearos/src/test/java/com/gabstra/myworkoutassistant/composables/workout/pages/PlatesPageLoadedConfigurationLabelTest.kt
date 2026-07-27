package com.gabstra.myworkoutassistant.composables.workout.pages

import org.junit.Assert.assertEquals
import org.junit.Test

class PlatesPageLoadedConfigurationLabelTest {
    @Test
    fun `groups repeated plates into a compact single-line label`() {
        assertEquals(
            "20×4 · 10×2 · 2.5",
            formatPlateConfigurationLabel(
                listOf(2.5, 20.0, 10.0, 20.0, 10.0, 20.0, 20.0)
            ),
        )
    }

    @Test
    fun `labels an empty configuration as bar only`() {
        assertEquals("Bar only", formatPlateConfigurationLabel(emptyList()))
    }
}
