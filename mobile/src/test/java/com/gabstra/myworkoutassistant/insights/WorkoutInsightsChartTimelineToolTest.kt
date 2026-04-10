package com.gabstra.myworkoutassistant.insights

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class WorkoutInsightsChartTimelineToolTest {

    private val sampleTimeline = WorkoutInsightsChartTimelineContext(
        durationSeconds = 600,
        segments = listOf(
            WorkoutInsightsChartTimelineSegment(0, 120, "Block A"),
            WorkoutInsightsChartTimelineSegment(100, 200, "Block B"),
            WorkoutInsightsChartTimelineSegment(400, 600, "Block C"),
        ),
    )

    @Test
    fun buildChartTimelineRangeResult_returns_overlapping_blocks() {
        val result = buildChartTimelineRangeResult(
            timeline = sampleTimeline,
            startSecondsArg = 90,
            endSecondsArg = 150,
            maxChars = 4000,
        )
        assertEquals(true, result["ok"])
        assertEquals(2, result["blockCount"])
        val blocks = result["blocks"] as String
        assertTrue(blocks.contains("Block A"))
        assertTrue(blocks.contains("Block B"))
        assertTrue(blocks.contains("00:00"))
    }

    @Test
    fun buildChartTimelineRangeResult_swaps_inverted_range() {
        val result = buildChartTimelineRangeResult(
            timeline = sampleTimeline,
            startSecondsArg = 200,
            endSecondsArg = 50,
            maxChars = 4000,
        )
        assertEquals(50, result["requestedStartSeconds"])
        assertEquals(200, result["requestedEndSeconds"])
    }
}
