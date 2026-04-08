package com.gabstra.myworkoutassistant.insights

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class WorkoutInsightsPromptBuilderTest {

    @Test
    fun buildWorkoutSessionPrompt_keeps_full_prompt_within_reserved_input_budget() {
        val markdown = buildString {
            append("# Very Long Session\n")
            append("2026-04-08 09:00 | Dur: 75m\n\n")
            repeat(16) { sectionIndex ->
                append("### Exercise ${sectionIndex + 1}\n\n")
                append("#### Context\n")
                append("- Type: WEIGHT\n")
                append("- Rep range: 5-8\n")
                append("- Progression mode: DOUBLE_PROGRESSION\n\n")
                append("#### Planned\n")
                append("- P1: 80kgx5\n")
                append("- P2: 80kgx5\n")
                append("- P3: 80kgx5\n")
                append("- P4: 80kgx5\n\n")
                append("#### Athlete Context\n")
                append(largeBody("athlete", 12))
                append("\n\n")
                append("#### Session Heart Rate\n")
                append(largeBody("heart-rate", 12))
                append("\n\n")
                append("#### Executed\n")
                append(largeBody("executed", 12))
                append("\n\n")
                append("#### Previous Session\n")
                append(largeBody("previous", 12))
                append("\n\n")
                append("#### Best To Date\n")
                append(largeBody("best", 12))
                append("\n\n")
                append("#### Recovery Context\n")
                append(largeBody("recovery", 12))
                append("\n\n")
                append("#### Coaching Signals\n")
                append(largeBody("signals", 12))
                append("\n\n")
            }
        }

        val prompt = buildWorkoutSessionPrompt(
            markdown = markdown,
            workoutCategoryGuidance =
                "Category guidance: judge success mainly from lift performance, progression, and recovery, with HR as supporting context only.\n",
            workoutCategoryLine = "Workout category: Strength Training\n"
        )

        assertTrue(estimateTokenCount(WORKOUT_INSIGHTS_SYSTEM_PROMPT) + estimateTokenCount(prompt) <= 3_456)
        assertTrue(prompt.contains("Workout session:"))
        assertTrue(prompt.contains("_Timelines"))
        assertTrue(prompt.contains("CONTEXT "))
        assertTrue(prompt.contains("PLAN "))
    }

    @Test
    fun compactWorkoutSessionMarkdown_removes_low_signal_subsections_when_over_budget() {
        val markdown = buildString {
            append("# Push Day\n")
            append("2026-04-08 09:00 | Dur: 75m\n\n")
            repeat(3) { sectionIndex ->
                append("### Exercise ${sectionIndex + 1}\n\n")
                append("#### Context\n")
                append("- Type: WEIGHT\n")
                append("- Rep range: 5-8\n")
                append("- Progression mode: DOUBLE_PROGRESSION\n\n")
                append("#### Planned\n")
                append("- P1: 80kgx5\n")
                append("- P2: 80kgx5\n")
                append("- P3: 80kgx5\n\n")
                append("#### Athlete Context\n")
                append(largeBody("athlete", 25))
                append("\n\n")
                append("#### Executed\n")
                append(largeBody("executed", 25))
                append("\n\n")
                append("#### Coaching Signals\n")
                append(largeBody("signals", 25))
                append("\n\n")
                append("#### Executed Timeline\n")
                append(largeBody("timeline", 40))
                append("\n\n")
                append("#### Trend (last 3 sessions)\n")
                append(largeBody("trend", 40))
                append("\n\n")
            }
        }

        val compacted = compactWorkoutSessionMarkdown(markdown)

        assertTrue(compacted.length <= 12_000)
        assertTrue(compacted.contains("Timelines and trends trimmed"))
        assertTrue(compacted.contains("CONTEXT "))
        assertTrue(compacted.contains("PLAN "))
        assertFalse(compacted.contains("TIMELINE "))
        assertFalse(compacted.contains("Trend (last 3 sessions)"))
        assertFalse(compacted.contains("signals detail"))
    }

    @Test
    fun compactWorkoutSessionMarkdown_humanizes_dense_metrics_for_llm_input() {
        val markdown = """
            # B Hinge/OHP

            #### Session Heart Rate
            - Mean: 99 bpm
            - Median: 101 bpm
            - MinMax: 78124 bpm
            - Std dev: 8.9 bpm
            - Max HR reference: age-based estimate (191 bpm)
            - Time at or above 85% of max HR: 0% of samples
            - Standard zones (% of samples, bpm range):
              - Z0 (0.0%50.0% reserve): 99% of samples, 50120 bpm
            - Stored HR samples: 1896

            ### Romanian Deadlift
            #### Context
            - Type: WEIGHT
            - Rep range: 6-10
            - Load range: 70%-85%
            - Progression mode: DOUBLE_PROGRESSION

            #### Planned
            - P1: 69kg9
            - P2: 69kg9
            - P3: 69kg9

            #### Executed
            - Executed sets: 6
            - Total volume: 2.16Kkg
            - Set summary: 9kg5, 34kg5, 49kg3, 69kg9

            #### Recovery Context
            - Work HR: avg 99 bpm | peak 111 bpm
            - Rest HR: avg 99 bpm | peak 114 bpm

            #### Coaching Signals
            - best_to_date
            - vs_previous_session:above
            - progression_state:ready_to_progress

            #### Executed Timeline
            S1: 69kg9 Vol:621kg | HR: 99 bpm (94105)
        """.trimIndent()

        val compacted = compactWorkoutSessionMarkdown(markdown)

        assertTrue(compacted.contains("Range: 78 to 124 bpm"))
        assertTrue(compacted.contains("Hi exp: 0% of samples"))
        assertTrue(compacted.contains("CONTEXT Type WEIGHT"))
        assertTrue(compacted.contains("PLAN "))
        assertTrue(compacted.contains("Plan:"))
        assertTrue(compacted.contains("Vol: 2.16 k kg"))
        assertTrue(compacted.contains("Sets: 9 kg x 5, 34 kg x 5, 49 kg x 3, 69 kg x 9"))
        assertTrue(compacted.contains("Best to date"))
        assertTrue(compacted.contains("Vs prev: above"))
        assertTrue(compacted.contains("State: ready to progress"))
        assertFalse(compacted.contains("Standard zones"))
        assertFalse(compacted.contains("Stored HR samples"))
        assertFalse(compacted.contains("Median:"))
        assertFalse(compacted.contains("Std dev:"))
        assertFalse(compacted.contains("Max HR reference"))
        assertFalse(compacted.contains("- Date:"))
        assertFalse(compacted.contains("- Executed sets: 6"))
        assertFalse(compacted.contains("Recovery gap:"))
        assertFalse(compacted.contains("TIMELINE "))
    }

    @Test
    fun compactWorkoutSessionMarkdown_drops_empty_history_blocks_and_unused_context() {
        val markdown = """
            # Push Day
            2026-04-08 09:00 | Dur: 75m

            #### Athlete Context
            - Age: 31 years
            - Weight (kg): 65
            - Max HR: age-based estimate
            - Resting HR (bpm): 50

            ### Overhead Press
            #### Previous Session
            - None

            #### Best To Date
            - None

            #### Coaching Signals
            - None
        """.trimIndent()

        val compacted = compactWorkoutSessionMarkdown(markdown)

        assertTrue(compacted.contains("ATHLETE Age: 31 years"))
        assertTrue(compacted.contains("Wt: 65"))
        assertTrue(compacted.contains("Rest HR: 50"))
        assertFalse(compacted.contains("Max HR:"))
        assertFalse(compacted.contains("PREV "))
        assertFalse(compacted.contains("BEST "))
        assertFalse(compacted.contains("SIGNALS "))
    }

    @Test
    fun compactWorkoutSessionMarkdown_aggregates_repeated_interval_sections() {
        val markdown = """
            # Cyclette - HIIT
            2026-03-30 19:51:38 | Dur: 40:16

            #### Session Heart Rate
            - Mean: 153 bpm
            - MinMax: 99183 bpm
            - Average as % of max HR: 80.1%
            - Peak as % of max HR: 95.8%

            ### Main Set
            #### Recovery Context
            - Work HR: avg 178 bpm | peak 181 bpm
            - Work samples in target zone: 70%

            #### Coaching Signals
            - vs_previous_session:similar
            - best_to_date
            - trend:stable

            ### Active Rest
            #### Recovery Context
            - Work HR: avg 146 bpm | peak 172 bpm
            - Work samples in target zone: 73%

            #### Coaching Signals
            - vs_previous_session:similar
            - best_to_date
            - trend:stable

            ### Main Set
            #### Recovery Context
            - Work HR: avg 179 bpm | peak 183 bpm
            - Work samples in target zone: 83%

            #### Coaching Signals
            - vs_previous_session:similar
            - best_to_date
            - trend:stable

            ### Active Rest
            #### Recovery Context
            - Work HR: avg 149 bpm | peak 172 bpm
            - Work samples in target zone: 68%

            #### Coaching Signals
            - vs_previous_session:similar
            - best_to_date
            - trend:stable
        """.trimIndent()

        val compacted = compactWorkoutSessionMarkdown(markdown)

        assertTrue(compacted.contains("Range: 99 to 183 bpm"))
        assertTrue(compacted.contains("EXERCISE Main Set"))
        assertTrue(compacted.contains("Repeated 2 times"))
        assertTrue(compacted.contains("Work HR avg range: 178 to 179 bpm | peak range: 181 to 183 bpm"))
        assertTrue(compacted.contains("In-zone range: 70% to 83%"))
        assertTrue(compacted.contains("EXERCISE Active Rest"))
        assertTrue(compacted.contains("Work HR avg range: 146 to 149 bpm | peak range: 172 to 172 bpm"))
        assertEquals(1, Regex("(?m)^EXERCISE Main Set$").findAll(compacted).count())
        assertEquals(1, Regex("(?m)^EXERCISE Active Rest$").findAll(compacted).count())
        assertEquals(2, Regex("Vs prev: similar").findAll(compacted).count())
    }

    @Test
    fun compactExerciseHistoryMarkdown_keeps_recent_sessions_when_over_budget() {
        val markdown = buildString {
            append("# Bench Press\n")
            append("Sessions: 10 | Range: 2026-01-01 to 2026-03-10\n\n")
            repeat(10) { sessionIndex ->
                append("## S${sessionIndex + 1}: 2026-03-${(sessionIndex + 1).toString().padStart(2, '0')} 09:00 | Push A\n")
                append("Session: start at 2026-03-01T09:00 | sessionId: id-$sessionIndex\n")
                append(largeBody("session-$sessionIndex", 35))
                append("\n\n")
            }
        }

        val compacted = compactExerciseHistoryMarkdown(markdown, markdownCharBudget = 400)

        assertTrue(compacted.length <= 12_000)
        assertTrue(compacted.contains("Only the most recent"))
        assertTrue(compacted.contains("S10"))
        assertFalse(compacted.contains("## S1:"))
    }

    @Test
    fun compactExerciseHistoryMarkdown_compacts_session_details_for_llm_input() {
        val markdown = """
            # Back Squat
            Type: WEIGHT | Equipment: Barbell | Weights: 9,9.5,10,10.5,11 kg

            #### Athlete Context
            - Age: 31 years
            - Weight (kg): 65
            - Max HR: age-based estimate
            - Resting HR (bpm): 50

            Sessions: 4 | Range: 2026-03-02 to 2026-04-01

            ## S1: 2026-03-02 19:28:44 | A Squat/Bench | Dur: 01:04:25
            Session: start at 2026-03-02T18:24:19 | sessionId: 1 | globalId: 1
            - Template position: exercise 1 of 4 (flattened workout order)
            #### Session Heart Rate
            - Mean: 107 bpm
            - Median: 107 bpm
            - MinMax: 67132 bpm
            - Std dev: 10.1 bpm
            - Average as % of max HR: 56.0%
            - Peak as % of max HR: 69.1%
            - Time at or above 85% of max HR: 0% of samples
            - Standard zones (% of samples, bpm range):
              - Z0: 88%
            - Stored HR samples: 3741

            #### Progression Context
            - State: PROGRESS
            - Expected: 75kg10, 75kg10, 75kg10
            - Executed: 75kg12, 77kg12, 79kg10
            - Set Differences: S1...
            - Comparison vs expected: ABOVE
            - Comparison vs previous successful baseline: EQUAL
            - Volume: Prev 0kg | Exp 2.25Kkg | Exec 2.61Kkg

            #### Executed Timeline
            S1: 75kg12 Vol:900kg | HR: 98 bpm (90109)

            ## S2: 2026-03-11 19:51:31 | A Squat/Bench | Dur: 01:07:54
            #### Session Heart Rate
            - Mean: 102 bpm
            - MinMax: 67129 bpm
            - Average as % of max HR: 53.4%
            - Peak as % of max HR: 67.5%
            - Time at or above 85% of max HR: 0% of samples

            #### Progression Context
            - State: PROGRESS
            - Expected: 75kg10, 75kg10, 75kg10
            - Executed: 79kg11, 79kg10, 79kg12
            - Comparison vs expected: ABOVE
            - Comparison vs previous successful baseline: EQUAL
            - Volume: Prev 0kg | Exp 2.25Kkg | Exec 2.61Kkg

            ## S3: 2026-03-17 19:59:53 | A Squat/Bench | Dur: 01:07:44
            #### Session Heart Rate
            - Mean: 103 bpm
            - MinMax: 53135 bpm
            - Average as % of max HR: 53.9%
            - Peak as % of max HR: 70.7%
            - Time at or above 85% of max HR: 0% of samples

            #### Progression Context
            - State: PROGRESS
            - Expected: 81.5kg8, 81.5kg8, 81.5kg8
            - Executed: 81.5kg10, 81.5kg9, 81.5kg10
            - Comparison vs expected: ABOVE
            - Comparison vs previous successful baseline: EQUAL
            - Volume: Prev 0kg | Exp 1.96Kkg | Exec 2.36Kkg

            ## S4: 2026-04-01 19:24:20 | A Squat/Bench | Dur: 01:08:26
            - Template position: exercise 1 of 4 (flattened workout order)
            #### Session Heart Rate
            - Mean: 105 bpm
            - MinMax: 69132 bpm
            - Average as % of max HR: 55.0%
            - Peak as % of max HR: 69.1%
            - Time at or above 85% of max HR: 0% of samples

            #### Progression Context
            - State: PROGRESS
            - Expected: 84kg7, 84kg7, 84kg7
            - Executed: 9kg5, 41.5kg5, 59kg3, 84kg7, 84kg7, 84kg7
            - Note: Expected 3 sets but executed 6 sets.
            - Comparison vs expected: EQUAL
            - Comparison vs previous successful baseline: EQUAL
            - Volume: Prev 0kg | Exp 1.76Kkg | Exec 1.76Kkg

            #### Executed Timeline
            S1: 9kg5 Vol:45kg | HR: 107 bpm (93119)
        """.trimIndent()

        val compacted = compactExerciseHistoryMarkdown(markdown, markdownCharBudget = 1_400)

        assertFalse(compacted.contains("| Weights:"))
        assertFalse(compacted.contains("## S1:"))
        assertTrue(compacted.contains("S4 "))
        assertFalse(compacted.contains("- Age:"))
        assertFalse(compacted.contains("Range: 69 to 132 bpm"))
        assertFalse(compacted.contains("Hi exp: 0% of samples"))
        assertTrue(compacted.contains("PROG State: PROGRESS"))
        assertTrue(compacted.contains("Exp: 84 kg x 7, 84 kg x 7, 84 kg x 7"))
        assertFalse(compacted.contains("Set Differences"))
        assertFalse(compacted.contains("Stored HR samples"))
        assertFalse(compacted.contains("sessionId"))
        assertFalse(compacted.contains("Vs previous baseline"))
    }

    @Test
    fun buildExercisePrompt_keeps_full_prompt_within_reserved_input_budget() {
        val markdown = buildString {
            append("# Bench Press\n")
            append("Sessions: 12 | Range: 2026-01-01 to 2026-04-01\n\n")
            repeat(12) { sessionIndex ->
                append("## S${sessionIndex + 1}: 2026-04-${(sessionIndex + 1).toString().padStart(2, '0')} 09:00 | Push A\n")
                append("#### Session Heart Rate\n")
                append(largeBody("heart-rate", 28))
                append("\n\n")
                append("#### Progression Context\n")
                append(largeBody("progression", 28))
                append("\n\n")
            }
        }

        val prompt = buildExercisePrompt(markdown)

        assertTrue(estimateTokenCount(WORKOUT_INSIGHTS_SYSTEM_PROMPT) + estimateTokenCount(prompt) <= 3_456)
        assertTrue(prompt.contains("Exercise history:"))
        assertTrue(prompt.contains("## S12:"))
    }

    private fun largeBody(
        label: String,
        repeatCount: Int,
    ): String = buildString {
        repeat(repeatCount) { index ->
            append("- ")
            append(label)
            append(" detail ")
            append(index)
            append(": workload, recovery, and execution notes repeated for budget pressure.\n")
        }
    }.trimEnd()
}
