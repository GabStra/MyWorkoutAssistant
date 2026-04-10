package com.gabstra.myworkoutassistant.insights

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class WorkoutInsightsToolingTest {

    @Test
    fun workoutSessionTools_parse_exercise_sections_from_compact_markdown() {
        val compactMarkdown = """
            Session status: Completed normally
            Workout category: Workout
            # A Squat/Bench
            2026-04-01 19:24:20 | Dur: 01:08:26
            ATHLETE Age: 31 years | Body weight: 65 | Rest HR: 50
            HR Mean: 105 bpm | Avg % max HR: 55% | Peak % max HR: 69% | High-intensity exposure: 0% of samples

            EXERCISE Back Squat
            EXEC Sets: 84 kg x 7 (3 sets) | Volume: 2190 kg
            PREV Sets: 81.5 kg x 11 (2 sets), 81.5 kg x 10 | Volume: 2610 kg
            SIGNALS State: progress | Vs prev: below | Top load vs prev: above

            EXERCISE Bench Press
            EXEC Sets: 60 kg x 10 (3 sets) | Volume: 2110 kg
            PREV Sets: 57.5 kg x 11 (3 sets) | Volume: 1897.5 kg
            SIGNALS State: progress | Vs prev: above | Top load vs prev: above
        """.trimIndent()
        val (topLevelOverview, sections) = splitWorkoutSessionOverviewAndSections(compactMarkdown)
        val overview = buildWorkoutSessionOverview(
            topLevelOverview = topLevelOverview,
            sectionBlocks = sections.values.toList()
        )
        val benchSection = sections.getValue("Bench Press")

        assertTrue(overview.contains("EXERCISE Back Squat"))
        assertTrue(overview.contains("EXERCISE Bench Press"))
        assertTrue(benchSection.contains("EXEC Sets: 60 kg x 10 (3 sets) | Volume: 2110 kg"))
        assertEquals(setOf("Back Squat", "Bench Press"), sections.keys)
    }
}
