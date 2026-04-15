package com.gabstra.myworkoutassistant.insights

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class WorkoutInsightsPromptBuilderTest {

    @Test
    fun toolEnabledPrompt_pushes_further_investigation_before_final_synthesis() {
        val prompt = buildToolEnabledSystemPrompt(WORKOUT_INSIGHTS_SYSTEM_PROMPT)
        val workflow = buildWorkoutSessionToolCallingPrompt(
            workoutLabel = "A Squat/Bench (Workout category: Workout)",
            sessionStatusSummary = "completed normally"
        )

        assertTrue(prompt.contains("Treat the first overview as scouting context, not final evidence"))
        assertTrue(prompt.contains("Investigate further whenever the current evidence is mixed, truncated, generic, or missing exercise-level detail"))
        assertTrue(prompt.contains("Do not write a workout-level risk from a generic overview alone"))
        assertFalse(prompt.contains("next-session guidance"))
        assertFalse(prompt.contains("next-step recommendation"))
        assertTrue(workflow.contains("Treat that overview as a first pass only"))
        assertTrue(workflow.contains("verify the clearest lagging or improving exercise with a narrower retrieval"))
        assertFalse(workflow.contains("next-session guidance"))
        assertFalse(workflow.contains("grounded next-session guidance"))
    }

    @Test
    fun workoutInsightsPrompts_include_conflict_and_formatting_guards() {
        assertTrue(WORKOUT_INSIGHTS_SYSTEM_PROMPT.contains("If metrics conflict, prefer the most explicit numeric fields first:"))
        assertTrue(WORKOUT_INSIGHTS_SYSTEM_PROMPT.contains("If a status label conflicts with explicit numeric values, trust the numeric values"))
        assertTrue(WORKOUT_INSIGHTS_SYSTEM_PROMPT.contains("Never describe a metric as improved if the numeric value is lower than the previous value."))
        assertTrue(WORKOUT_INSIGHTS_SYSTEM_PROMPT.contains("If one exercise improved and another regressed or lagged versus previous, say that explicitly."))
        assertTrue(WORKOUT_INSIGHTS_SYSTEM_PROMPT.contains("Double progression means the app normally adds reps at the current working load"))
        assertTrue(WORKOUT_INSIGHTS_SYSTEM_PROMPT.contains("Auto-regulation uses the same double-progression baseline"))
        assertTrue(WORKOUT_INSIGHTS_SYSTEM_PROMPT.contains("Do not omit grounded, decision-useful details just to satisfy brevity, but merge related exercises"))
        assertTrue(WORKOUT_INSIGHTS_SYSTEM_PROMPT.contains("Keep each bullet short, focused, and non-redundant."))
        assertTrue(WORKOUT_INSIGHTS_SYSTEM_PROMPT.contains("Do not repeat the same fact in multiple sections"))
        assertTrue(WORKOUT_INSIGHTS_SYSTEM_PROMPT.contains("Avoid writing exact metric values with units in the final markdown"))
        assertTrue(WORKOUT_INSIGHTS_SYSTEM_PROMPT.contains("copy it verbatim from the supplied evidence"))
        assertTrue(WORKOUT_INSIGHTS_SYSTEM_PROMPT.contains("Before finalizing, silently verify:"))
        assertFalse(WORKOUT_INSIGHTS_SYSTEM_PROMPT.contains("## Next session"))
        assertFalse(WORKOUT_INSIGHTS_SYSTEM_PROMPT.contains("at most 2 bullets per section"))

        val prompt = buildWorkoutSessionPrompt(
            markdown = "# Session\n\n### Back Squat",
            workoutCategoryGuidance = "",
            workoutCategoryLine = ""
        )

        assertTrue(prompt.contains("Compare each exercise against plan, previous, and best-to-date performance."))
        assertTrue(prompt.contains("Do not flatten mixed exercise results into overall progress when exercises diverge."))
        assertTrue(prompt.contains("account for planned double-progression load jumps or auto-regulated load changes before calling it below previous"))
        assertTrue(prompt.contains("If Exec, Prev, Best, or Expected numbers disagree with status labels, trust the numbers."))
        assertTrue(prompt.contains("Interpret DOUBLE_PROGRESSION and AUTO_REGULATION as progression systems"))
        assertTrue(prompt.contains("Stay concise by grouping exercises with the same takeaway and avoiding repeated facts across sections."))
        assertTrue(prompt.contains("Use exact numbers for reasoning only"))
        assertTrue(prompt.contains("Do not say an exercise reached the top or bottom of a rep range unless a TAKEAWAY line says that directly."))
        assertTrue(prompt.contains("do not recommend reducing load just to match previous volume"))
    }

    @Test
    fun exerciseInsightsPrompt_uses_exercise_specific_instructions() {
        assertTrue(EXERCISE_INSIGHTS_SYSTEM_PROMPT.contains("You are an exercise insights assistant."))
        assertTrue(EXERCISE_INSIGHTS_SYSTEM_PROMPT.contains("Focus on the latest completed session first"))
        assertTrue(EXERCISE_INSIGHTS_SYSTEM_PROMPT.contains("If the latest session met plan but still lagged previous, baseline, or recent trend, say that explicitly."))
        assertTrue(EXERCISE_INSIGHTS_SYSTEM_PROMPT.contains("Double progression means the app normally adds reps at the current working load"))
        assertTrue(EXERCISE_INSIGHTS_SYSTEM_PROMPT.contains("Auto-regulation uses the same double-progression baseline"))
        assertTrue(EXERCISE_INSIGHTS_SYSTEM_PROMPT.contains("Do not omit grounded, decision-useful details just to satisfy brevity, but merge related signals"))
        assertTrue(EXERCISE_INSIGHTS_SYSTEM_PROMPT.contains("Keep each bullet short, focused, and non-redundant."))
        assertTrue(EXERCISE_INSIGHTS_SYSTEM_PROMPT.contains("Do not repeat the same fact in multiple sections"))
        assertTrue(EXERCISE_INSIGHTS_SYSTEM_PROMPT.contains("Avoid writing exact metric values with units in the final markdown"))
        assertTrue(EXERCISE_INSIGHTS_SYSTEM_PROMPT.contains("copy it verbatim from the supplied evidence"))
        assertFalse(EXERCISE_INSIGHTS_SYSTEM_PROMPT.contains("## Next session"))
        assertFalse(EXERCISE_INSIGHTS_SYSTEM_PROMPT.contains("at most 2 bullets per section"))

        val prompt = buildExercisePrompt(
            markdown = "# Back Squat\n\n## S1: 2026-04-01"
        )

        assertTrue(prompt.contains("Focus on the latest completed session first, then use recent history only where it changes interpretation."))
        assertTrue(prompt.contains("Compare executed performance against expected work and the previous baseline, then explain any relevant trend."))
        assertTrue(prompt.contains("Stay concise by combining related signals and avoiding repeated facts across sections."))
        assertTrue(prompt.contains("Interpret DOUBLE_PROGRESSION and AUTO_REGULATION as progression systems"))
        assertTrue(prompt.contains("Use TAKEAWAY lines as authoritative user-facing comparison facts, and do not contradict them."))
        assertTrue(prompt.contains("do not recommend reducing load just to match previous volume"))
        assertTrue(prompt.contains("Use exact numbers for reasoning only"))
    }

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
        assertTrue(prompt.contains("CONTEXT "))
        assertTrue(prompt.contains("EXERCISE "))
        assertFalse(prompt.contains("_Timelines"))
        assertFalse(prompt.contains("PLAN "))
    }

    @Test
    fun buildWorkoutSessionPrompt_drops_redundant_prev_and_best_snapshots_when_signals_match() {
        val markdown = """
            # Intervals
            2026-04-08 09:00 | Dur: 32m

            ### Main Set

            #### Context
            - Type: COUNTDOWN
            - Progression mode: OFF
            - Exercise target zone: 90%-95% of max HR
            - Warm-up sets: disabled

            #### Executed
            - Set summary: Duration: 04:00 | Duration: 04:00

            #### Previous Session
            - Set summary: Duration: 04:00 | Duration: 04:00

            #### Best To Date
            - Duration: 04:00

            #### Recovery Context
            - Work HR: avg 177 bpm | peak 181 bpm
            - Work samples in target zone: 78%

            #### Coaching Signals
            - Vs prev: matched
            - Vs best: matched
            - Trend: stable
        """.trimIndent()

        val prompt = buildWorkoutSessionPrompt(
            markdown = markdown,
            workoutCategoryGuidance = "",
            workoutCategoryLine = ""
        )

        assertTrue(prompt.contains("EXERCISE Main Set"))
        assertTrue(prompt.contains("CONTEXT Type COUNTDOWN | Progression OFF | Target zone 90%-95% of max HR | Warm-up disabled"))
        assertTrue(prompt.contains("EXEC Sets: Duration: 04:00 | Duration: 04:00"))
        assertTrue(prompt.contains("RECOVERY Work HR: avg 177 bpm | peak 181 bpm | In target zone: 78%"))
        assertTrue(prompt.contains("SIGNALS Vs prev: matched | Vs best: matched | Trend: stable"))
        assertFalse(prompt.contains("PREV Sets: Duration: 04:00 | Duration: 04:00"))
        assertFalse(prompt.contains("BEST Duration: 04:00"))
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
        assertTrue(compacted.contains("CONTEXT "))
        assertFalse(compacted.contains("PLAN "))
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
        assertTrue(compacted.contains("High-intensity exposure: 0% of samples"))
        assertTrue(compacted.contains("CONTEXT Type WEIGHT"))
        assertFalse(compacted.contains("PLAN "))
        assertTrue(compacted.contains("Volume: 2160 kg"))
        assertTrue(compacted.contains("Sets: 1 set at 9 kg for 5 reps; 1 set at 34 kg for 5 reps; 1 set at 49 kg for 3 reps; 1 set at 69 kg for 9 reps"))
        assertTrue(compacted.contains("Vs best: matched"))
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
        assertTrue(compacted.contains("Body weight: 65"))
        assertTrue(compacted.contains("Rest HR: 50"))
        assertFalse(compacted.contains("Max HR:"))
        assertTrue(compacted.contains("PREV No previous session"))
        assertFalse(compacted.contains("BEST "))
        assertFalse(compacted.contains("SIGNALS "))
    }

    @Test
    fun compactWorkoutSessionMarkdown_keeps_repeated_interval_sections_separate() {
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
        assertTrue(compacted.contains("EXERCISE Active Rest"))
        assertTrue(compacted.contains("RECOVERY Work HR: avg 178 bpm | peak 181 bpm | In target zone: 70%"))
        assertTrue(compacted.contains("RECOVERY Work HR: avg 179 bpm | peak 183 bpm | In target zone: 83%"))
        assertTrue(compacted.contains("RECOVERY Work HR: avg 146 bpm | peak 172 bpm | In target zone: 73%"))
        assertTrue(compacted.contains("RECOVERY Work HR: avg 149 bpm | peak 172 bpm | In target zone: 68%"))
        assertFalse(compacted.contains("Repeated 2 times"))
        assertEquals(2, Regex("(?m)^EXERCISE Main Set$").findAll(compacted).count())
        assertEquals(2, Regex("(?m)^EXERCISE Active Rest$").findAll(compacted).count())
        assertEquals(4, Regex("Vs prev: similar").findAll(compacted).count())
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
        assertTrue(compacted.contains("HR Avg % max HR: 55% | Peak % max HR: 69%"))
        assertTrue(compacted.contains("PROG State: PROGRESS"))
        assertTrue(compacted.contains("Expected: 3 sets at 84 kg for 7 reps"))
        assertTrue(compacted.contains("Executed: 1 set at 9 kg for 5 reps; 1 set at 41.5 kg for 5 reps; 1 set at 59 kg for 3 reps; 3 sets at 84 kg for 7 reps"))
        assertTrue(compacted.contains("Vs success baseline: EQUAL"))
        assertTrue(compacted.contains("Volume: Prev 0 kg | Exp 1.76 k kg | Exec 1.76 k kg"))
        assertFalse(compacted.contains("Set Differences"))
        assertFalse(compacted.contains("Stored HR samples"))
        assertFalse(compacted.contains("sessionId"))
    }

    @Test
    fun compactExerciseHistoryMarkdown_adds_userFacingTakeaway_forSuccessfulLoadIncrease() {
        val markdown = """
            # Bench Press
            Type: WEIGHT | Equipment: Barbell

            Sessions: 2 | Range: 2026-03-25 to 2026-04-01

            ## S1: 2026-03-25 19:24:20 | A Squat/Bench
            #### Progression Context
            - State: PROGRESS
            - Expected: 60kg10, 60kg10, 60kg10
            - Executed: 60kg10, 60kg10, 60kg10
            - Comparison vs expected: EQUAL
            - Comparison vs previous successful baseline: EQUAL
            - Volume: Prev 0kg | Exp 1.8Kkg | Exec 1.8Kkg

            ## S2: 2026-04-01 19:24:20 | A Squat/Bench
            #### Progression Context
            - State: PROGRESS
            - Expected: 62kg7, 62kg7, 62kg7
            - Executed: 62kg7, 62kg7, 62kg8
            - Comparison vs expected: ABOVE
            - Comparison vs previous successful baseline: ABOVE
            - Volume: Prev 0kg | Exp 1.30Kkg | Exec 1.36Kkg
        """.trimIndent()

        val compacted = compactExerciseHistoryMarkdown(markdown)

        assertTrue(
            compacted,
            compacted.contains("TAKEAWAY successful load increase; lower reps and volume are expected after the jump; beat the plan; above the previous successful baseline.")
        )
    }

    @Test
    fun compactWorkoutSessionMarkdown_omits_planned_steps_from_compacted_payload() {
        val markdown = """
            # A Squat/Bench
            2026-04-01 19:24:20 | Dur: 01:08:26

            ### Back Squat
            #### Planned
            - P 1: 84 kg x 7 reps
            - P 2: 120 seconds rest
            - P 3: 84 kg x 7 reps
            - P 4: 120 seconds rest
            - P 5: 84 kg x 7 reps
        """.trimIndent()

        val compacted = compactWorkoutSessionMarkdown(markdown)

        assertFalse(compacted.contains("PLAN "))
    }

    @Test
    fun compactWorkoutSessionMarkdown_prioritizes_numeric_history_and_compacts_repeated_sets() {
        val markdown = """
            # A Squat/Bench
            2026-04-01 19:24:20 | Dur: 01:08:26

            ### Back Squat
            #### Executed
            - Date: 2026-04-01
            - Set summary: 9 kg x 5, 41.5 kg x 5, 59 kg x 3, 84 kg x 7, 84 kg x 7, 84 kg x 7
            - Total volume: 2.19Kkg

            #### Previous Session
            - Set summary: 84 kg x 7, 84 kg x 7, 84 kg x 7
            - Total volume: 2.61Kkg
            - Progression state: PROGRESS

            #### Best To Date
            - Set summary: 84 kg x 7, 84 kg x 7, 84 kg x 7
            - Total volume: 2.61Kkg
            - Progression state: PROGRESS
        """.trimIndent()

        val compacted = compactWorkoutSessionMarkdown(markdown)

        assertFalse(compacted.contains("Date: 2026-04-01"))
        assertTrue(compacted.contains("EXEC Sets: 3 sets at 84 kg for 7 reps | Volume: 2190 kg"))
        assertTrue(compacted.contains("PREV Sets: 3 sets at 84 kg for 7 reps | Volume: 2610 kg"))
        assertTrue(compacted.contains("BEST Volume: 2610 kg"))
        assertFalse(compacted.contains("PREV Sets: 3 sets at 84 kg for 7 reps | Volume: 2610 kg | State: PROGRESS"))
        assertFalse(compacted.contains("BEST Volume: 2610 kg | State: PROGRESS"))
        assertFalse(compacted.contains("BEST Sets:"))
    }

    @Test
    fun compactWorkoutSessionMarkdown_normalizes_decimal_commas_and_compact_ranges() {
        val markdown = """
            # A Squat/Bench
            2026-04-01 19:24:20 | Dur: 01:08:26

            #### Athlete Context
            - Age: 31 years
            - Weight (kg): 65
            - Resting HR (bpm): 50

            #### Session Heart Rate
            - Mean: 105 bpm
            - MinMax: 69132 bpm
            - Average as % of max HR: 55,0%
            - Peak as % of max HR: 69,1%
            - Time at or above 85% of max HR: 0% of samples
        """.trimIndent()

        val compacted = compactWorkoutSessionMarkdown(markdown)

        assertTrue(compacted.contains("ATHLETE Age: 31 years | Body weight: 65 | Rest HR: 50"))
        assertTrue(compacted.contains("HR Mean: 105 bpm | Range: 69 to 132 bpm | Avg % max HR: 55% | Peak % max HR: 69% | High-intensity exposure: 0% of samples"))
    }

    @Test
    fun compactWorkoutSessionMarkdown_marks_missing_previous_session_explicitly() {
        val markdown = """
            # A Push
            2026-04-01 19:24:20 | Dur: 00:45:00

            ### Overhead Press
            #### Executed
            - Set summary: 40 kg x 8, 40 kg x 8, 40 kg x 8
            - Total volume: 960kg

            #### Previous Session
            - None
        """.trimIndent()

        val compacted = compactWorkoutSessionMarkdown(markdown)

        assertTrue(compacted.contains("PREV No previous session"))
    }

    @Test
    fun compactWorkoutSessionMarkdown_builds_prev_sets_from_historical_set_lines() {
        val markdown = """
            # A Squat
            2026-04-01 19:24:20 | Dur: 00:45:00

            ### Back Squat
            #### Previous Session
            - Date: 2026-03-25 19:24:20
            - Executed sets: 3
            - Total volume: 1764kg
            - Progression state: PROGRESS
            - S1: 84kg×7
            - S2: 84kg×7
            - S3: 84kg×7
        """.trimIndent()

        val compacted = compactWorkoutSessionMarkdown(markdown)

        assertTrue(compacted.contains("PREV Sets: 3 sets at 84 kg for 7 reps | Volume: 1764 kg"))
        assertFalse(compacted.contains("PREV Sets: 3 sets at 84 kg for 7 reps | Volume: 1764 kg | State: PROGRESS"))
    }

    @Test
    fun compactWorkoutSessionMarkdown_highlights_top_load_increase_when_volume_is_lower() {
        val markdown = """
            # A Squat
            2026-04-01 19:24:20 | Dur: 00:45:00

            ### Back Squat
            #### Executed
            - Set summary: 9 kg x 5, 41.5 kg x 5, 59 kg x 3, 84 kg x 7, 84 kg x 7, 84 kg x 7
            - Total volume: 2.19Kkg

            #### Previous Session
            - Set summary: 81.5 kg x 11, 81.5 kg x 11, 81.5 kg x 10
            - Total volume: 2.61Kkg

            #### Coaching Signals
            - progression_state:progress
            - vs_expected:equal
            - vs_previous_session:below
        """.trimIndent()

        val compacted = compactWorkoutSessionMarkdown(markdown)

        assertTrue(compacted.contains("EXEC Sets: 3 sets at 84 kg for 7 reps | Volume: 2190 kg"))
        assertTrue(compacted.contains("PREV Sets: 2 sets at 81.5 kg for 11 reps; 1 set at 81.5 kg for 10 reps | Volume: 2610 kg"))
        assertTrue(compacted.contains("SIGNALS State: progress | Vs target: equal | Vs prev: below | Load profile vs prev: above | Top load vs prev: above (84 kg vs 81.5 kg) | Sets at top load: 3 vs 3"))
        assertTrue(compacted.contains("TAKEAWAY successful load increase; lower reps and volume are expected after the jump; met the plan."))
    }

    @Test
    fun compactWorkoutSessionMarkdown_adds_userFacingTakeaway_forSameLoadMoreReps() {
        val markdown = """
            # A Pull
            2026-04-01 19:24:20 | Dur: 00:45:00

            ### Pull-Ups
            #### Executed
            - Set summary: 67 kg x 7, 67 kg x 7, 67 kg x 7
            - Total volume: 1410kg

            #### Previous Session
            - Set summary: 67 kg x 7, 67 kg x 7, 67 kg x 6
            - Total volume: 1340kg

            #### Coaching Signals
            - progression_state:progress
            - vs_expected:equal
            - vs_previous_session:above
        """.trimIndent()

        val compacted = compactWorkoutSessionMarkdown(markdown)

        assertTrue(compacted.contains("TAKEAWAY same load as the previous session, with more reps and volume; met the plan."))
    }

    @Test
    fun compactWorkoutSessionMarkdown_highlights_top_load_drop_when_current_load_is_lighter() {
        val markdown = """
            # A Bench
            2026-04-01 19:24:20 | Dur: 00:45:00

            ### Bench Press
            #### Executed
            - Set summary: 80 kg x 8, 80 kg x 8, 80 kg x 8
            - Total volume: 1920kg

            #### Previous Session
            - Set summary: 82.5 kg x 8, 82.5 kg x 8, 82.5 kg x 8
            - Total volume: 1980kg

            #### Coaching Signals
            - progression_state:progress
            - vs_previous_session:below
        """.trimIndent()

        val compacted = compactWorkoutSessionMarkdown(markdown)

        assertTrue(compacted.contains("Load profile vs prev: below"))
        assertTrue(compacted.contains("Top load vs prev: below (80 kg vs 82.5 kg)"))
        assertTrue(compacted.contains("Sets at top load: 3 vs 3"))
        assertTrue(compacted.contains("TAKEAWAY lighter than the previous session."))
    }

    @Test
    fun compactWorkoutSessionMarkdown_highlights_mixed_load_profile_when_only_some_sets_are_heavier() {
        val markdown = """
            # A Squat
            2026-04-01 19:24:20 | Dur: 00:45:00

            ### Back Squat
            #### Executed
            - Set summary: 82.5 kg x 8, 80 kg x 8, 80 kg x 8
            - Total volume: 2425kg

            #### Previous Session
            - Set summary: 80 kg x 8, 80 kg x 8, 80 kg x 8
            - Total volume: 1920kg

            #### Coaching Signals
            - progression_state:progress
            - vs_previous_session:above
        """.trimIndent()

        val compacted = compactWorkoutSessionMarkdown(markdown)

        assertTrue(compacted.contains("Load profile vs prev: mixed"))
        assertTrue(compacted.contains("Top load vs prev: above (82.5 kg vs 80 kg)"))
        assertTrue(compacted.contains("Sets at top load: 1 vs 3"))
        assertTrue(compacted.contains("TAKEAWAY heavier than the previous session with more total work."))
    }

    @Test
    fun compactWorkoutSessionMarkdown_keeps_zone_time_without_exercise_snapshots() {
        val markdown = """
            # A Squat/Bench
            2026-04-01 19:24:20 | Dur: 01:08:26

            #### Session Heart Rate
            - Mean: 105 bpm
            - MinMax: 69132 bpm
            - Average as % of max HR: 55.0%
            - Peak as % of max HR: 69.1%
            - Time at or above 85% of max HR: 0% of samples
            - Valid HR samples: 600
            - Standard zones (% of samples, bpm range):
              - Z0 (0.0%50.0% reserve): 70% of samples, 50120 bpm
              - Z1 (50.0%60.0% reserve): 30% of samples, 120140 bpm

            ### Back Squat
            #### Context
            - Type: WEIGHT
            - Equipment: Barbell

            #### Executed
            - Total volume: 2.19Kkg

            #### Previous Session
            - Total volume: 2.61Kkg

            #### Best To Date
            - Total volume: 2.61Kkg

            #### Coaching Signals
            - progression_state:progress
            - vs_expected:equal
            - vs_previous_session:below
            - below_best_to_date

            ### Bench Press
            #### Context
            - Type: WEIGHT
            - Equipment: Barbell

            #### Executed
            - Total volume: 2.11Kkg

            #### Previous Session
            - Total volume: 1.68Kkg

            #### Best To Date
            - Total volume: 2.11Kkg

            #### Coaching Signals
            - progression_state:progress
            - vs_expected:above
            - vs_previous_session:above
            - best_to_date

            ### Row
            #### Context
            - Type: WEIGHT
            - Equipment: Barbell

            #### Executed
            - Total volume: 893kg

            #### Previous Session
            - Total volume: 1.25Kkg

            #### Best To Date
            - Total volume: 893kg

            #### Coaching Signals
            - progression_state:progress
            - vs_expected:equal
            - vs_previous_successful_baseline:equal
            - vs_previous_session:above
        """.trimIndent()

        val compacted = compactWorkoutSessionMarkdown(markdown)

        assertTrue(compacted.contains("HR Mean: 105 bpm | Range: 69 to 132 bpm | Avg % max HR: 55% | Peak % max HR: 69% | High-intensity exposure: 0% of samples | Approx zone time: Z0 07:00 | Z1 03:00"))
        assertTrue(compacted.contains("EXEC Volume: 2190 kg"))
        assertTrue(compacted.contains("PREV Volume: 2610 kg"))
        assertTrue(compacted.contains("BEST Volume: 2610 kg"))
        assertTrue(compacted.contains("PREV Volume: 1250 kg"))
        assertFalse(compacted.contains("Range: 69132 bpm"))
        assertFalse(compacted.contains("k kg"))
        assertFalse(compacted.contains("EXERCISE SNAPSHOT"))
        assertFalse(compacted.contains("_Timelines and trends trimmed._"))
        assertTrue(compacted.contains("SIGNALS State: progress | Vs target: equal | Vs success baseline: equal | Vs prev: below"))
    }

    @Test
    fun buildWorkoutSessionPrompt_adds_lifting_guidance_for_generic_workout_category_when_exercise_mix_is_strength_dominant() {
        val prompt = buildWorkoutSessionPrompt(
            markdown = """
                # A Squat/Bench

                ### Back Squat
                #### Context
                - Type: WEIGHT

                ### Pull-Ups
                #### Context
                - Type: BODY_WEIGHT
            """.trimIndent(),
            workoutCategoryGuidance = "Category guidance: balance performance, effort, and recovery signals according to the workout type.",
            workoutCategoryLine = "Workout category: Workout\n"
        )

        assertTrue(prompt.contains("Exercise mix guidance: this session is lifting-dominant even though the workout category label is generic"))
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

        assertTrue(estimateTokenCount(EXERCISE_INSIGHTS_SYSTEM_PROMPT) + estimateTokenCount(prompt) <= 3_456)
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
