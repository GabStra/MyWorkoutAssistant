package com.gabstra.myworkoutassistant.composables

import org.junit.Assert.assertEquals
import org.junit.Test

class PagePlatesScrollTargetTest {
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
}
