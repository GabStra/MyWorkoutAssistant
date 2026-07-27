package com.gabstra.myworkoutassistant.composables.workout.pages

import org.junit.Assert.assertEquals
import org.junit.Test

class PlatesPagePlateWidthTest {
    @Test
    fun `raises a thin plate to the configured minimum`() {
        assertEquals(
            12f,
            constrainedPlateWidthPx(
                scaledThicknessPx = 4f,
                minWidthPx = 12f,
                maxWidthPx = 32f,
                remainingSleeveWidthPx = 100f,
            ),
            0f,
        )
    }

    @Test
    fun `caps a wide plate at the configured maximum`() {
        assertEquals(
            32f,
            constrainedPlateWidthPx(
                scaledThicknessPx = 80f,
                minWidthPx = 8f,
                maxWidthPx = 32f,
                remainingSleeveWidthPx = 100f,
            ),
            0f,
        )
    }

    @Test
    fun `still respects the remaining sleeve width`() {
        assertEquals(
            12f,
            constrainedPlateWidthPx(
                scaledThicknessPx = 80f,
                minWidthPx = 8f,
                maxWidthPx = 32f,
                remainingSleeveWidthPx = 12f,
            ),
            0f,
        )
    }
}
