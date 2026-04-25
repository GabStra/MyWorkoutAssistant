package com.gabstra.myworkoutassistant.insights

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
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

    @Test
    fun workoutSessionOverview_denseSummaryIncludesAccessorySectionsByDefault() {
        val compactMarkdown = """
            Session status: Completed normally
            Workout category: Workout
            # A Squat/Bench
            2026-04-10 20:32:05 | Dur: 01:03:38
            ATHLETE Age: 31 years | Body weight: 65 | Rest HR: 50
            HR Mean: 109 bpm | Range: 71-143 bpm | Avg % max HR: 57% | Peak % max HR: 75% | High-intensity exposure: 0% of samples

            EXERCISE Back Squat
            EXEC Sets: 84 kg x 8 (3 sets) | Volume: 2450 kg
            PREV Sets: 84 kg x 7 (3 sets) | Volume: 2190 kg
            SIGNALS State: progress | Vs prev: above | Load profile vs prev: above | Top load vs prev: matched (84 kg vs 84 kg)

            EXERCISE Bench Press
            EXEC Sets: 62 kg x 7 (2 sets), 62 kg x 8 | Volume: 1700 kg
            PREV Sets: 60 kg x 10 (3 sets) | Volume: 2110 kg
            SIGNALS State: progress | Vs prev: below | Load profile vs prev: above | Top load vs prev: above (62 kg vs 60 kg)

            EXERCISE Pull-ups
            EXEC Sets: Body weight x 8 (3 sets)
            PREV Sets: Body weight x 8, Body weight x 7 (2 sets)
            SIGNALS State: progress | Vs prev: above

            EXERCISE Row
            EXEC Sets: 52 kg x 10 (3 sets)
            PREV Sets: 52 kg x 9 (3 sets)
            SIGNALS State: progress | Vs prev: above

            EXERCISE Abs
            EXEC Sets: 12 reps (3 sets)
            PREV Sets: 12 reps (3 sets)
            SIGNALS State: stable | Vs prev: matched
        """.trimIndent()
        val (topLevelOverview, sections) = splitWorkoutSessionOverviewAndSections(compactMarkdown)
        val overview = buildWorkoutSessionOverview(
            topLevelOverview = topLevelOverview,
            sectionBlocks = sections.values.toList()
        )

        assertTrue(overview.contains("EXERCISE Pull-ups"))
        assertTrue(overview.contains("EXERCISE Abs"))
        assertFalse(overview.endsWith("..."))
    }

    @Test
    fun exerciseTools_return_compact_session_markdown() {
        val markdown = """
            # Bench Press
            Type: WEIGHT | Equipment: Barbell | Weights: 20,40,60 kg

            #### Athlete Context
            - Age: 31 years
            - Weight (kg): 65

            Sessions: 2 | Range: 2026-03-25 to 2026-04-01

            ## S1: 2026-03-25 19:24:20 | Push A | Dur: 01:00:00
            Session: start at 2026-03-25T18:24:20 | sessionId: old | globalId: old
            - Template position: exercise 1 of 4 (flattened workout order)
            #### Session Heart Rate
            - Mean: 107 bpm
            - Median: 107 bpm
            - MinMax: 67132 bpm
            - Std dev: 10.1 bpm
            - Average as % of max HR: 56.0%
            - Peak as % of max HR: 69.1%
            - Time at or above 85% of max HR: 0% of samples
            - Stored HR samples: 3741

            #### Progression Context
            - State: PROGRESS
            - Expected: 60kg10, 60kg10, 60kg10
            - Executed: 60kg10, 60kg10, 60kg10
            - Set Differences: verbose details
            - Comparison vs expected: EQUAL
            - Comparison vs previous successful baseline: EQUAL
            - Volume: Prev 0kg | Exp 1.8Kkg | Exec 1.8Kkg

            #### Executed Timeline
            S1: 60kg10 Vol:600kg | HR: 98 bpm (90109)
            S2: 60kg10 Vol:600kg | HR: 99 bpm (90110)
            S3: 60kg10 Vol:600kg | HR: 100 bpm (90111)

            ## S2: 2026-04-01 19:24:20 | Push A | Dur: 01:00:00
            Session: start at 2026-04-01T18:24:20 | sessionId: new | globalId: new
            - Template position: exercise 1 of 4 (flattened workout order)
            #### Progression Context
            - State: PROGRESS
            - Expected: 62kg7, 62kg7, 62kg7
            - Executed: 62kg7, 62kg7, 62kg8
            - Set Differences: verbose details
            - Comparison vs expected: ABOVE
            - Comparison vs previous successful baseline: ABOVE
            - Volume: Prev 0kg | Exp 1.30Kkg | Exec 1.36Kkg
        """.trimIndent()

        val compactHistory = compactExerciseHistoryParts(markdown)
        val latest = compactHistory.sessions.last()
        val overview = compactHistory.header

        assertTrue(latest.contains("S2 2026-04-01"))
        assertTrue(latest.contains("PROG State: PROGRESS"))
        assertTrue(latest.contains("Executed: 2 sets at 62 kg for 7 reps; 1 set at 62 kg for 8 reps"))
        assertTrue(latest.contains("TAKEAWAY successful load increase"))
        assertFalse(latest.contains("Session: start at"))
        assertFalse(latest.contains("sessionId"))
        assertFalse(latest.contains("Set Differences"))
        assertFalse(latest.contains("Stored HR samples"))
        assertFalse(overview.contains("| Weights:"))
        assertFalse(overview.contains("- Age:"))
    }
}
