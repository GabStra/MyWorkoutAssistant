package com.gabstra.myworkoutassistant.reps

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class StillnessTrackerTest {

    @Test
    fun `steady gravity is still`() {
        val tracker = StillnessTracker()
        var still = true
        for (i in 0 until 50) {
            still = tracker.addSample(i * 20_000_000L, 0f, 0f, 9.81f)
        }
        assertTrue(still)
    }

    @Test
    fun `repeated movement is not still`() {
        val tracker = StillnessTracker()
        var still = true
        for (i in 0 until 100) {
            // 3 Hz, ±3 m/s² on Z: well above the stillness threshold.
            val z = 9.81f + 3f * kotlin.math.sin(2.0 * Math.PI * 3.0 * i * 20_000_000L / 1e9).toFloat()
            still = tracker.addSample(i * 20_000_000L, 0f, 0f, z)
        }
        assertFalse(still)
    }

    @Test
    fun `reset returns to still`() {
        val tracker = StillnessTracker()
        for (i in 0 until 100) {
            tracker.addSample(i * 20_000_000L, 0f, 0f, 9.81f + if (i % 2 == 0) 3f else -3f)
        }
        tracker.reset()
        assertTrue(tracker.addSample(0L, 0f, 0f, 9.81f))
    }
}
