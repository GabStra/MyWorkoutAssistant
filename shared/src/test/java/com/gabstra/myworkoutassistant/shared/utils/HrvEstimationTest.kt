package com.gabstra.myworkoutassistant.shared.utils

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.assertNull
import org.junit.Test

class HrvEstimationTest {

    @Test
    fun `hand computed vector matches expected rmssd and sdnn`() {
        // Successive differences: +50, -70, +40 -> squares 2500, 4900, 1600.
        // RMSSD = sqrt(9000 / 3) = 54.7723 ms.
        // Mean = 812.5; sum of squared deviations = 2675 -> SDNN = sqrt(2675 / 3) = 29.8609 ms.
        val ibi = listOf(800, 850, 780, 820)

        assertEquals(54.7723, HrvEstimation.rmssd(ibi)!!, 0.001)
        assertEquals(29.8609, HrvEstimation.sdnn(ibi)!!, 0.001)
    }

    @Test
    fun `implausible beats are filtered before computing`() {
        // 100 (too fast), 2500 (too slow), and 0 must be dropped.
        // Remaining: 800, 850, 780.
        val ibi = listOf(800, 100, 850, 2500, 780, 0)

        // Successive differences: +50, -70 -> squares 2500, 4900.
        // RMSSD = sqrt(7400 / 2) = 60.8276 ms.
        assertEquals(60.8276, HrvEstimation.rmssd(ibi)!!, 0.001)

        // Mean = 810; sum of squared deviations = 2600 -> SDNN = sqrt(2600 / 2) = 36.0555 ms.
        assertEquals(36.0555, HrvEstimation.sdnn(ibi)!!, 0.001)
    }

    @Test
    fun `insufficient data returns null`() {
        // RMSSD needs three successive intervals.
        assertNull(HrvEstimation.rmssd(listOf(800, 850)))
        assertNull(HrvEstimation.rmssd(emptyList()))

        // SDNN needs two intervals.
        assertNull(HrvEstimation.sdnn(listOf(800)))
        assertNull(HrvEstimation.sdnn(emptyList()))
    }

    @Test
    fun `median deviation rejects a single artifact beat`() {
        // Median of 800/810/1600/820/830 is 820; 1600 is >25% away and must be dropped.
        val ibi = listOf(800, 810, 1600, 820, 830)

        // Remaining: 800, 810, 820, 830 (mean 815) -> SDNN = sqrt(500 / 3) = 12.9099 ms.
        assertEquals(12.9099, HrvEstimation.sdnn(ibi)!!, 0.001)
    }

    @Test
    fun `beats flagged as moving or unreliable are dropped`() {
        val ibi = listOf(800, 805, 1200, 810)
        // 0 = NONE, -1 = ATTACHED, -2 = DETECT_MOVE, -8 = LOW_RELIABILITY.
        val statuses = listOf(0, -1, -2, 0)

        assertEquals(listOf(800, 805, 810), HrvEstimation.filterUsableBeats(ibi, statuses))
    }

    @Test
    fun `usable flags and missing statuses are kept whole`() {
        val ibi = listOf(800, 805, 810)
        assertEquals(ibi, HrvEstimation.filterUsableBeats(ibi, listOf(0, 1, -1)))
        assertEquals(ibi, HrvEstimation.filterUsableBeats(ibi, emptyList()))
    }

    @Test
    fun `heart rate status accepts only usable sensor flags`() {
        assertTrue(HeartRateQuality.isUsable(null))
        assertTrue(HeartRateQuality.isUsable(0))
        assertTrue(HeartRateQuality.isUsable(1))
        assertTrue(HeartRateQuality.isUsable(-1))
        assertFalse(HeartRateQuality.isUsable(-2))
        assertFalse(HeartRateQuality.isUsable(-8))
        assertFalse(HeartRateQuality.isUsable(-10))
    }

    @Test
    fun `all beats filtered out returns null`() {
        val implausible = listOf(100, 2500, 0, 5000)
        assertNull(HrvEstimation.rmssd(implausible))
        assertNull(HrvEstimation.sdnn(implausible))
    }
}
