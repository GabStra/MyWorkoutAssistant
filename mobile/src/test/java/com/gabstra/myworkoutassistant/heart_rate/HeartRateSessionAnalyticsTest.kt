package com.gabstra.myworkoutassistant.heart_rate

import com.gabstra.myworkoutassistant.shared.HeartRateSource
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
        assertEquals(4.0, analysis.zoneCounts.values.sum(), 1e-9)
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
    fun analyzeHeartRateSession_summarisesSecondarySourceSeparately() {
        val analysis = analyzeHeartRateSession(
            heartRateSeries = listOf(120, 130, 140),
            durationSeconds = 2,
            userAge = 30,
            extraSeries = listOf(
                HeartRateSourceSeries(label = "Strap", samples = listOf(0, 100, 110, 130))
            ),
        )

        assertNotNull(analysis)
        // The primary stream keeps driving zones and averages; the chart ranges cover both.
        assertEquals(130, analysis!!.averageHeartRate)
        assertEquals(120, analysis.minHeartRate)
        assertEquals(100.0, analysis.minChartY, 0.0)

        val secondary = analysis.extraSummaries.single()
        assertEquals("Strap", secondary.label)
        assertEquals(113, secondary.averageHeartRate)
        assertEquals(100, secondary.minHeartRate)
        assertEquals(130, secondary.maxHeartRate)
    }

    @Test
    fun analyzeHeartRateSession_hasNoSecondarySummaryWithoutSecondarySamples() {
        val analysis = analyzeHeartRateSession(
            heartRateSeries = listOf(120, 130, 140),
            durationSeconds = 2,
            userAge = 30,
            extraSeries = listOf(
                HeartRateSourceSeries(label = "Strap", samples = listOf(0, 0))
            ),
        )

        assertTrue(analysis!!.extraSummaries.isEmpty())
    }

    @Test
    fun buildExtraHeartRateSeries_excludesActiveSourceAndOrdersWatchFirst() {
        val series = buildExtraHeartRateSeries(
            streams = mapOf(
                "WHOOP_BLE" to listOf(100, 110),
                "WATCH_SENSOR" to listOf(120, 130),
                "POLAR_BLE" to listOf(0, 0),
            ),
            activeSource = HeartRateSource.POLAR_BLE,
        )

        // Polar is the stream of record, so it is not repeated; the empty one is dropped.
        assertEquals(listOf("Watch sensor", "WHOOP"), series.map { it.label })
    }

    @Test
    fun analyzeHeartRateSession_weightsZoneTimeByRealSampleTimes() {
        // Second sample lasts 3 s, the last one defaults to 1 s.
        val analysis = analyzeHeartRateSession(
            heartRateSeries = listOf(120, 130, 140),
            durationSeconds = 1,
            userAge = 30,
            heartRateTimesMs = listOf(0L, 1_000L, 4_000L),
        )

        assertNotNull(analysis)
        assertEquals(5.0, analysis!!.zoneCounts.values.sum(), 1e-9)
        assertEquals(4, analysis.durationSeconds)
    }

    @Test
    fun alignedHeartRateTimes_fallsBackToOneSamplePerSecond() {
        assertEquals(listOf(0L, 1000L, 2000L), alignedHeartRateTimes(null, 3))
        assertEquals(listOf(0L, 500L), alignedHeartRateTimes(listOf(0L, 500L), 2))
        // A mismatched length is untrustworthy; fall back rather than mis-align.
        assertEquals(listOf(0L, 1000L), alignedHeartRateTimes(listOf(0L, 500L, 900L), 2))
    }

    @Test
    fun secondsInHeartRateRange_usesTimesAndRange() {
        val samples = listOf(120, 130, 200, 0)
        val times = listOf(0L, 1_000L, 2_000L, 3_000L)

        // 0..2500 ms: 120 (1 s) and 130 (1 s) are in range; 200 is not.
        assertEquals(
            2.0,
            secondsInHeartRateRange(samples, times, fromMs = 0, toMs = 2_500, lowHr = 100, highHr = 150),
            1e-9,
        )
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
