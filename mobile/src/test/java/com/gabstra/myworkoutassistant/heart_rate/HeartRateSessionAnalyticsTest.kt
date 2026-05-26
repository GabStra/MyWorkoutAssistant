package com.gabstra.myworkoutassistant.heart_rate

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class HeartRateSessionAnalyticsTest {
    @Test
    fun analyzeHeartRateSession_calculatesMinMaxAverageAndZones() {
        val analysis = analyzeHeartRateSession(
            heartRateSeries = listOf(0, 120, 130, 145, 160, 0),
            durationSeconds = 5,
            userAge = 30,
        )

        assertNotNull(analysis)
        assertEquals(120, analysis!!.minHeartRate)
        assertEquals(160, analysis.maxHeartRate)
        assertEquals(138, analysis.averageHeartRate)
        assertEquals(4, analysis.validHeartRateCount)
        assertEquals(4, analysis.zoneCounts.values.sum())
    }

    @Test
    fun analyzeHeartRateSession_returnsNullWhenNoValidSamples() {
        val analysis = analyzeHeartRateSession(
            heartRateSeries = listOf(0, 0, 0),
            durationSeconds = 2,
            userAge = 30,
        )

        assertNull(analysis)
    }

    @Test
    fun getHeartRateZoneBounds_returnsOrderedNonOverlappingRanges() {
        val ranges = getHeartRateZoneBounds(userAge = 30)

        assertTrue(ranges.isNotEmpty())
        ranges.zipWithNext().forEach { (current, next) ->
            assertTrue(current.last < next.first)
        }
    }
}
