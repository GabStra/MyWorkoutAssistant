package com.gabstra.myworkoutassistant.shared.utils

import org.junit.Assert.assertEquals
import org.junit.Test

class HydrationEstimationTest {

    @Test
    fun `replacement target is 125 percent of loss`() {
        assertEquals(1250, HydrationEstimation.replacementTargetMl(1000))
        assertEquals(500, HydrationEstimation.replacementTargetMl(400))
    }

    @Test
    fun `replacement target rounds to nearest millilitre`() {
        assertEquals(1, HydrationEstimation.replacementTargetMl(1))
        assertEquals(3, HydrationEstimation.replacementTargetMl(2))
        assertEquals(13, HydrationEstimation.replacementTargetMl(10))
    }

    @Test
    fun `replacement target is floored at zero`() {
        assertEquals(0, HydrationEstimation.replacementTargetMl(0))
        assertEquals(0, HydrationEstimation.replacementTargetMl(-100))
    }

    @Test
    fun `sweat loss is the library's cumulative total`() {
        assertEquals(10, HydrationEstimation.accumulateSweatLoss(0, 10))
        assertEquals(25, HydrationEstimation.accumulateSweatLoss(10, 25))
        assertEquals(40, HydrationEstimation.accumulateSweatLoss(25, 40))
    }

    @Test
    fun `a lower repeat never reduces the total`() {
        assertEquals(25, HydrationEstimation.accumulateSweatLoss(25, 10))
    }

    @Test
    fun `negative samples are ignored`() {
        assertEquals(12, HydrationEstimation.accumulateSweatLoss(12, -4))
    }
}
