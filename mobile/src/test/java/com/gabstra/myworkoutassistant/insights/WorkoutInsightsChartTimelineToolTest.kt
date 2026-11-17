package com.gabstra.myworkoutassistant.insights

import com.gabstra.myworkoutassistant.shared.HeartRateSource
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate
import java.time.LocalTime
import java.util.UUID

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

    @Test
    fun buildWorkoutSessionChartTimelineToolContext_returnsNullForUnknownImportedTiming() {
        val date = LocalDate.of(2026, 5, 20)
        val history = WorkoutHistory(
            id = UUID.randomUUID(),
            workoutId = UUID.randomUUID(),
            date = date,
            time = LocalTime.MIDNIGHT,
            startTime = date.atStartOfDay(),
            duration = 0,
            heartBeatRecords = emptyList(),
            isDone = true,
            hasBeenSentToHealth = false,
            globalId = UUID.randomUUID(),
            startTimeKnown = false,
            durationKnown = false,
        )
        val workout = Workout(
            id = history.workoutId,
            name = "Upper A",
            description = "",
            workoutComponents = emptyList(),
            order = 0,
            enabled = true,
            heartRateSource = HeartRateSource.WATCH_SENSOR,
            creationDate = date,
            globalId = UUID.randomUUID(),
            type = 56,
        )

        val context = buildWorkoutSessionChartTimelineToolContext(
            workoutHistory = history,
            workout = workout,
            setHistories = emptyList(),
            restHistories = emptyList(),
        )

        assertNull(context)
    }
}
