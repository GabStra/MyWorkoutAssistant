package com.gabstra.myworkoutassistant.composables.workout.pages

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PlatesPageScrollTargetTest {
    @Test
    fun `keeps the plate stack centered when labels already fit`() {
        val target = resolveInitialBarbellScrollTargetPx(
            plateCenterPx = 250f,
            labelBoundsLeftPx = 120f,
            labelBoundsRightPx = 250f,
            viewportWidthPx = 300f,
            maxScrollPx = 200f,
        )

        assertEquals(100, target)
    }

    @Test
    fun `shifts only enough to keep fitting labels visible`() {
        val target = resolveInitialBarbellScrollTargetPx(
            plateCenterPx = 250f,
            labelBoundsLeftPx = 90f,
            labelBoundsRightPx = 340f,
            viewportWidthPx = 300f,
            maxScrollPx = 200f,
        )

        assertEquals(90, target)
    }

    @Test
    fun `keeps the plate stack centered when labels exceed the viewport`() {
        val target = resolveInitialBarbellScrollTargetPx(
            plateCenterPx = 250f,
            labelBoundsLeftPx = 20f,
            labelBoundsRightPx = 360f,
            viewportWidthPx = 300f,
            maxScrollPx = 200f,
        )

        assertEquals(100, target)
    }

    @Test
    fun `disables panning when the complete visual group fits`() {
        assertFalse(
            shouldEnableBarbellHorizontalPan(
                visualWidthPx = 300f,
                viewportWidthPx = 300f,
            )
        )
    }

    @Test
    fun `enables panning only when the complete visual group overflows`() {
        assertTrue(
            shouldEnableBarbellHorizontalPan(
                visualWidthPx = 301f,
                viewportWidthPx = 300f,
            )
        )
    }
}
