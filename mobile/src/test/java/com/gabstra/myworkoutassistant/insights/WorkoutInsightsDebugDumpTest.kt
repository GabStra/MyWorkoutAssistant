package com.gabstra.myworkoutassistant.insights

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.Date

class WorkoutInsightsDebugDumpTest {

    @Test
    fun buildWorkoutInsightsDebugDumpFileName_sanitizesTitleAndIncludesMode() {
        val fileName = buildWorkoutInsightsDebugDumpFileName(
            timestamp = Date(0),
            mode = WorkoutInsightsMode.LOCAL,
            title = "Workout Session: A/B + heavy singles",
        )

        assertEquals(
            "workout_insights_debug_1970-01-01_00-00-00_local_workout_session_a_b_heavy_singles.json",
            fileName,
        )
    }

    @Test
    fun buildWorkoutInsightsDebugDumpFileName_usesUntitledWhenSlugWouldBeEmpty() {
        val fileName = buildWorkoutInsightsDebugDumpFileName(
            timestamp = Date(0),
            mode = WorkoutInsightsMode.REMOTE,
            title = "!!!",
        )

        assertTrue(fileName.endsWith("_remote_untitled.json"))
    }
}
