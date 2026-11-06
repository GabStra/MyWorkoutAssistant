package com.gabstra.myworkoutassistant.composables

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class CoarseStepTest {

    @Test
    fun `sustained hold uses the coarse step only when one is supplied`() {
        // Below the sustained-hold threshold: keep the normal step.
        assertFalse(shouldUseCoarseStep(0, hasCoarseStep = true))
        assertFalse(shouldUseCoarseStep(COARSE_STEP_AFTER_MILLIS - 1, hasCoarseStep = true))
        // At and after it: coarse.
        assertTrue(shouldUseCoarseStep(COARSE_STEP_AFTER_MILLIS, hasCoarseStep = true))
        assertTrue(shouldUseCoarseStep(COARSE_STEP_AFTER_MILLIS + 5_000, hasCoarseStep = true))
        // Screens without a coarse step never switch.
        assertFalse(shouldUseCoarseStep(10_000, hasCoarseStep = false))
    }
}
