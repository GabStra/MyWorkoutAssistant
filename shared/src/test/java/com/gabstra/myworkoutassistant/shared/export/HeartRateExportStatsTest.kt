package com.gabstra.myworkoutassistant.shared.export

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDateTime

class HeartRateExportStatsTest {

    @Test
    fun sliceHeartRateRecords_clampsWhenIntervalExtendsPastBuffer() {
        val start = LocalDateTime.of(2020, 1, 1, 10, 0, 0)
        val records = List(100) { 120 }
        val intervalStart = start
        val intervalEnd = start.plusSeconds(60)
        val slice = sliceHeartRateRecords(start, records, intervalStart, intervalEnd)
        assertEquals(100, slice.size)
    }

    @Test
    fun sliceHeartRateRecords_returnsEmptyWhenNoOverlap() {
        val start = LocalDateTime.of(2020, 1, 1, 10, 0, 0)
        val records = List(10) { 100 }
        val intervalStart = start.plusSeconds(100)
        val intervalEnd = start.plusSeconds(110)
        val slice = sliceHeartRateRecords(start, records, intervalStart, intervalEnd)
        assertTrue(slice.isEmpty())
    }

    @Test
    fun medianInt_handlesOddAndEven() {
        assertEquals(120, medianInt(listOf(100, 120, 140)))
        assertEquals(125, medianInt(listOf(100, 120, 130, 150)))
    }

    @Test
    fun standardZoneSampleFractions_sumsToOne() {
        val bounds = heartRateZoneBoundsBpm(30, measuredMaxHeartRate = 200, restingHeartRate = 60)
        val samples = listOf(100, 120, 140, 180)
        val fr = standardZoneSampleFractions(samples, bounds)
        assertEquals(bounds.size, fr.size)
        val sum = fr.sum()
        assertTrue(sum in 0.99..1.01)
    }
}
