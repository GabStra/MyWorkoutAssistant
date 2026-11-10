package com.gabstra.myworkoutassistant.screens

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PreparingReadinessTest {

    @Test
    fun `first watch sample is ready immediately`() {
        assertTrue(isWatchHeartRateReady(samplesSinceStart = 1, elapsedMillis = 0))
    }

    @Test
    fun `no sample blocks until the timeout`() {
        assertFalse(isWatchHeartRateReady(samplesSinceStart = 0, elapsedMillis = 0))
        assertFalse(
            isWatchHeartRateReady(
                samplesSinceStart = 0,
                elapsedMillis = WATCH_HR_READY_TIMEOUT_MS.toInt() - 1,
            )
        )
        assertTrue(
            isWatchHeartRateReady(
                samplesSinceStart = 0,
                elapsedMillis = WATCH_HR_READY_TIMEOUT_MS.toInt(),
            )
        )
    }
}
