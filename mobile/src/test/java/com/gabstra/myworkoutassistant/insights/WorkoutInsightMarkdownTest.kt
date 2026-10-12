package com.gabstra.myworkoutassistant.insights

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class WorkoutInsightMarkdownTest {

    private val factsContext = """
        FACT Session duration: 55:09 (55 minutes)
        FACT Average heart rate: 140 bpm; peak 154 bpm
        FACT Whole-session time in target zone: 80% of HR samples inside 60-70% of heart-rate reserve (135-150 bpm)
        FACT Previous-session target check: the target was average HR at or under 131 bpm for about 55 minutes; this session averaged 140 bpm across 55 minutes — target not met
        FACT Next-session target: average heart rate at or under 131 bpm for about 55 minutes

        ### Main Set
        #### Recovery Context
        - Work samples in target zone: 96% (135-150 bpm)
    """.trimIndent()
    @Test
    fun sanitizeInsightMarkdown_normalizes_triple_star_exercise_headings() {
        val raw =
            "Analysis of your performance:***Squat:** You did well.***Bench Press:** More text."
        val sanitized = sanitizeInsightMarkdown(raw)
        assertTrue(sanitized.contains("## Squat"))
        assertTrue(sanitized.contains("## Bench Press"))
        assertFalse(sanitized.contains("***Squat:**"))
    }

    @Test
    fun sanitizeInsightMarkdown_normalizes_double_star_colon_inside_headings() {
        val sanitized = sanitizeInsightMarkdown("Intro **Leg Press:** next line **Row:** done.")
        assertTrue(sanitized.contains("## Leg Press"))
        assertTrue(sanitized.contains("## Row"))
    }

    @Test
    fun sanitizeInsightMarkdown_normalizes_four_or_more_star_headings() {
        val sanitized = sanitizeInsightMarkdown("Start ****Accessory:** body here.")
        assertTrue(sanitized.contains("## Accessory"))
    }

    @Test
    fun sanitizeInsightMarkdown_preserves_bold_then_colon_not_heading() {
        val raw = "- **Back Squat**: text here."
        val sanitized = sanitizeInsightMarkdown(raw)
        assertTrue(sanitized.contains("**Back Squat**"))
        assertFalse(sanitized.contains("## Back Squat"))
    }

    @Test
    fun sanitizeInsightMarkdown_does_not_turn_metric_bold_into_heading() {
        val raw = "Peak **84:** kg range."
        val sanitized = sanitizeInsightMarkdown(raw)
        assertTrue(sanitized.contains("**84:**"))
        assertFalse(sanitized.contains("## 84"))
    }

    @Test
    fun sanitizeInsightMarkdown_splits_glued_exclamation_sentence() {
        val sanitized = sanitizeInsightMarkdown("Great work!Overall solid effort.")
        assertTrue(sanitized.contains("work!\n\nOverall"))
    }

    @Test
    fun sanitizeInsightMarkdown_splits_paren_before_new_sentence() {
        val sanitized = sanitizeInsightMarkdown("Volume was 536 kg).The history shows more.")
        assertTrue("Sanitized output was: $sanitized", sanitized.contains("536 kg).\n\nThe history"))
    }

    @Test
    fun sanitizeInsightMarkdown_strips_decorative_leading_indent_on_body_lines() {
        val raw = """
            ## Progression State

                  You are in the `PROGRESS` state.

                 ## Volume Trend

                  Your volume increased.
        """.trimIndent()
        val sanitized = sanitizeInsightMarkdown(raw)
        assertTrue(sanitized.contains("You are in the"))
        assertFalse(sanitized.contains("\n                  You"))
        assertTrue(sanitized.contains("Your volume increased."))
    }

    @Test
    fun compactTopLevelHeadingLevelsForDisplay_demotes_h2_to_h3_only() {
        val inMd = "## Volume Trend\n\n### Already small\n\n## Next\n"
        val out = compactTopLevelHeadingLevelsForDisplay(inMd)
        assertEquals(
            "### Volume Trend\n\n### Already small\n\n### Next\n",
            out,
        )
    }

    @Test
    fun sanitizeInsightMarkdown_splits_glued_sentences_and_colon_star_lists() {
        val raw = """
            Based on the history, you are in a PROGRESS state across all recorded sessions.Here is a summary of the progression:*Volume Trend: Your volume has increased.*Intensity/Load: You progressed.*Set/Rep Structure: Adjusted.
        """.trimIndent()

        val sanitized = sanitizeInsightMarkdown(raw)

        assertTrue(sanitized.contains("sessions.\n\nHere"))
        // List markers are normalized to "- " for MarkdownText.
        assertTrue(sanitized.contains("progression:\n\n- Volume"))
        assertTrue(sanitized.contains("- Intensity"))
    }

    @Test
    fun sanitizeInsightMarkdown_splits_glued_numbered_list_items() {
        val raw = "1. There is no evidence of a plateau based on the last three sessions.2. The last three sessions show matched performance against the target."

        val sanitized = sanitizeInsightMarkdown(raw)

        assertTrue(sanitized.contains("sessions.\n\n2. The last three sessions"))
    }

    @Test
    fun sanitizeInsightMarkdown_collapsesNestedDashBullets() {
        val sanitized = sanitizeInsightMarkdown(
            """
                ## Signals
                - - The heart rate showed significant fluctuation throughout the session.
            """.trimIndent()
        )

        assertTrue(sanitized.contains("- The heart rate showed significant fluctuation throughout the session."))
        assertFalse(sanitized.contains("- - The heart rate"))
    }


    @Test
    fun sanitizeInsightMarkdown_normalizes_raw_response_wrappers_and_broken_lists() {
        val brokenMarkdown = """
            workout_raw_response_start
            ## Summary- The session showed consistent progress across all tracked lifts, with volume increases in Squat, Bench Press, Pull-Ups, and Row.- Recovery HRs were generally stable, indicating a solid effort level without significant acute fatigue signals.## Signals- - The Squat volume increased from2.61 K kg to2.19 K kg, while the Bench Press volume progressed from1.68 K kg to2.11 K kg.- - All tracked exercises reported a 'progress' state, suggesting successful adherence to the progression plan.## Risks- - The session's overall HR profile suggests a moderate effort level, which may limit the stimulus for further strength adaptation.- - High-intensity exposure was0%, meaning the session did not push into high-intensity territory.## Next session- - Focus on increasing the load on the Squat or Bench Press to challenge the current progress state.- - - Maintain the current volume progression across the main lifts to continue building strength.
            workout_raw_response_end
        """.trimIndent()

        val sanitized = sanitizeInsightMarkdown(brokenMarkdown)

        assertEquals(
            """
            ## Summary

            - The session showed consistent progress across all tracked lifts, with volume increases in Squat, Bench Press, Pull-Ups, and Row.
            - Recovery HRs were generally stable, indicating a solid effort level without significant acute fatigue signals.

            ## Signals

            - The Squat volume increased from 2.61 K kg to 2.19 K kg, while the Bench Press volume progressed from 1.68 K kg to 2.11 K kg.
            - All tracked exercises reported a 'progress' state, suggesting successful adherence to the progression plan.

            ## Risks

            - The session's overall HR profile suggests a moderate effort level, which may limit the stimulus for further strength adaptation.
            - High-intensity exposure was 0%, meaning the session did not push into high-intensity territory.

            ## Next session

            - Focus on increasing the load on the Squat or Bench Press to challenge the current progress state.
            - Maintain the current volume progression across the main lifts to continue building strength.
            """.trimIndent(),
            sanitized
        )
    }

    @Test
    fun sanitizeInsightMarkdown_preservesBoldBulletLabels() {
        val sanitized = sanitizeInsightMarkdown(
            """
                ## Exercise highlights- **Back Squat**: You moved to a higher load while keeping the reps steady.- **Bench Press**: You increased the top load compared to the previous session.- **Pull-Ups**: You maintained the same load and rep scheme.
            """.trimIndent()
        )

        assertEquals(
            """
            ## Exercise highlights

            - **Back Squat**: You moved to a higher load while keeping the reps steady.
            - **Bench Press**: You increased the top load compared to the previous session.
            - **Pull-Ups**: You maintained the same load and rep scheme.
            """.trimIndent(),
            sanitized
        )
    }

    @Test
    fun postProcessInsightMarkdown_removes_low_intensity_hr_risk_for_lifting_sessions() {
        val markdown = """
            ## Summary
            - Bench press volume was lower than the previous session.

            ## Signals
            - Squat top load increased to 84 kg.

            ## Risks
            - High-intensity exposure was 0%, meaning the session did not push into high-intensity territory.
            - Bench press volume was lower than the previous session.

            ## Next session
            - Focus on increasing bench press volume.
        """.trimIndent()

        val processed = postProcessInsightMarkdown(
            markdown = markdown,
            toolContext = WorkoutInsightsToolContext.WorkoutSession(
                title = "Workout session insights",
                workoutLabel = "A Squat/Bench",
                markdown = """
                    HR Mean: 105 bpm | Avg % max HR: 55% | High-intensity exposure: 0% of samples
                    EXERCISE Back Squat
                    CONTEXT Type WEIGHT | Rep range 6-10
                    EXERCISE Bench Press
                    CONTEXT Type WEIGHT | Rep range 6-10
                """.trimIndent()
            )
        )

        assertFalse(processed.contains("High-intensity exposure was 0%"))
        assertTrue(processed.contains("Bench press volume was lower than the previous session."))
    }

    @Test
    fun postProcessInsightMarkdown_replacesMetricMentionsNotFoundInEvidencePrompt() {
        val markdown = """
            ## Exercise highlights
            - Back Squat matched the recorded work at 84 kg for 8 reps.
            - Bench Press total volume was 13600 kg versus 180 kg previously.
            - Pull-Ups used the same load of 677 kg, and Row jumped to 425 kg.
            - Heart rate averaged 10 bpm.
        """.trimIndent()

        val processed = postProcessInsightMarkdown(
            markdown = markdown,
            toolContext = WorkoutInsightsToolContext.Exercise(
                title = "Workout session insights",
                exerciseName = "Back Squat",
                markdown = ""
            ),
            evidencePrompt = """
                Workout session:
                EXERCISE Back Squat
                EXEC Sets: 3 sets at 84 kg for 8 reps | Volume: 2020 kg
                EXERCISE Bench Press
                EXEC Sets: 2 sets at 62 kg for 7 reps; 1 set at 62 kg for 8 reps | Volume: 1360 kg
                PREV Sets: 3 sets at 60 kg for 10 reps | Volume: 1800 kg
                EXERCISE Pull-Ups
                EXEC Sets: 3 sets at 67 kg for 7 reps | Volume: 1410 kg
                EXERCISE Row
                EXEC Sets: 3 sets at 42.5 kg for 8 reps | Volume: 1020 kg
            """.trimIndent()
        )

        assertTrue(processed.contains("84 kg"))
        assertTrue(processed.contains("8 reps"))
        assertFalse(processed.contains("13600 kg"))
        assertFalse(processed.contains("180 kg"))
        assertFalse(processed.contains("677 kg"))
        assertFalse(processed.contains("425 kg"))
        assertFalse(processed.contains("10 bpm"))
        // Lines whose every metric was unsupported are dropped outright instead of surviving
        // as broken "the recorded value" prose.
        assertFalse(processed.contains("the recorded value"))
        assertFalse(processed.contains("Bench Press total volume"))
        assertFalse(processed.contains("Pull-Ups used the same load"))
    }

    @Test
    fun postProcessInsightMarkdown_usesToolContextMarkdownForHistoryChatMetricAllowList() {
        val markdown = """
            You started using 677 kg and a different bodyweight of 5 kg.
            Compare S8 (677 x 8) with S9 (67 x 8).
        """.trimIndent()

        val processed = postProcessInsightMarkdown(
            markdown = markdown,
            toolContext = WorkoutInsightsToolContext.Exercise(
                title = "Pull-Ups chat",
                exerciseName = "Pull-Ups",
                markdown = """
                    # Pull-Ups
                    ## S8
                    - Sets: 67x8, 67x7, 67x7
                    - Session BW: 65 kg
                    ## S9
                    - Sets: 67x8, 67x8, 67x7
                    - Session BW: 65 kg
                """.trimIndent()
            ),
            evidencePrompt = """
                Current task: answer the User question at the end of this message.
                User question:
                am i in a plateau?
            """.trimIndent()
        )

        assertFalse(processed.contains("677 kg"))
        assertFalse(processed.contains("5 kg"))
        assertFalse(processed.contains("677 x 8"))
        assertTrue(processed.contains("67 x 8"))
        // "You started using 677 kg and a different bodyweight of 5 kg." had no supported
        // metric left after redaction, so the whole line is gone.
        assertFalse(processed.contains("the recorded value"))
        assertFalse(processed.contains("You started using"))
        assertTrue(processed.contains("the recorded set"))
    }

    @Test
    fun postProcessInsightMarkdown_allowsSpelledOutDurationsMatchingClockEvidence() {
        val markdown = """
            ## Exercise highlights
            - The session involved a total duration of 52 minutes and 30 seconds.
            - A fabricated stretch of 47 minutes was also claimed.
            - Distance covered was 0.8 km.
        """.trimIndent()

        val processed = postProcessInsightMarkdown(
            markdown = markdown,
            toolContext = WorkoutInsightsToolContext.Exercise(
                title = "Workout session insights",
                exerciseName = "Cyclette",
                markdown = "- Duration: 52:30\n- Distance: 0.8 km"
            ),
            evidencePrompt = """
                Workout session:
                - Total duration: 00:52:30
            """.trimIndent()
        )

        assertTrue(processed.contains("52 minutes"))
        assertTrue(processed.contains("30 seconds"))
        assertFalse(processed.contains("47 minutes"))
        assertTrue(processed.contains("0.8 km"))
        assertFalse(processed.contains("the recorded value"))
        assertFalse(processed.contains("fabricated"))
    }

    @Test
    fun postProcessInsightMarkdown_dropsExerciseHighlightsSectionThatSaysNothing() {
        val markdown = """
            ## What stood out
            - Trajectory is regressing: average HR 6 bpm above the recent 133 bpm average.

            ## Exercise highlights
            - No specific exercise-level highlights were retrieved.

            ## Next session target
            - Keep average HR at or under 140 bpm for about 55 minutes
        """.trimIndent()

        val processed = postProcessInsightMarkdown(
            markdown = markdown,
            toolContext = null,
        )

        assertFalse(processed.contains("Exercise highlights"))
        assertTrue(processed.contains("What stood out"))
        assertTrue(processed.contains("Next session target"))
        assertTrue(processed.contains("Keep average HR"))
    }

    @Test
    fun postProcessInsightMarkdown_keepsExerciseHighlightsSectionWithRealContent() {
        val markdown = """
            ## What stood out
            - Trajectory is regressing: average HR 6 bpm above the recent 133 bpm average.

            ## Exercise highlights
            - Main Set interval executed at 96% of samples inside the target zone.

            ## Next session target
            - Keep average HR at or under 140 bpm for about 55 minutes
        """.trimIndent()

        val processed = postProcessInsightMarkdown(
            markdown = markdown,
            toolContext = null,
        )

        assertTrue(processed.contains("Exercise highlights"))
        assertTrue(processed.contains("96%"))
    }

    @Test
    fun postProcessInsightMarkdown_allowsFactsQuotedVerbatimFromSessionFactsBlock() {
        // Regression for the on-device "the recorded value" stripping report: the model
        // may quote FACT lines verbatim (including the next-session target); those
        // numbers must survive because the facts ride in toolContext.markdown.
        val facts = """
            FACT Session duration: 55:09 (55 minutes)
            FACT Average heart rate: 140 bpm; peak 154 bpm
            FACT 80% of HR samples stayed inside the 60-70% target zone
            FACT Heart-rate drift: the second half averaged -2 bpm versus the first half
            FACT Next-session target: average heart rate at or under 140 bpm for about 55 minutes
        """.trimIndent()

        val markdown = """
            ## What stood out
            - The session duration was 55 minutes.
            - The average heart rate was 140 bpm, with a peak of 154 bpm.
            - 80% of the heart rate samples stayed within the 60-70% target zone.
            - The heart rate drift in the second half of the session was -2 bpm.

            ## Next session target
            - - average heart rate at or under 140 bpm for about 55 minutes
        """.trimIndent()

        val processed = postProcessInsightMarkdown(
            markdown = markdown,
            toolContext = WorkoutInsightsToolContext.WorkoutSession(
                title = "Workout session insights",
                workoutLabel = "Cyclette - LISS",
                markdown = facts,
            ),
        )

        assertTrue(processed.contains("55 minutes"))
        assertTrue(processed.contains("140 bpm"))
        assertTrue(processed.contains("154 bpm"))
        assertTrue(processed.contains("60-70%"))
        assertFalse(processed.contains("the recorded value"))
    }

    @Test
    fun postProcessInsightMarkdown_dropsFullyRedactedBulletsAndTheirEmptySection() {
        // Regression for the on-device report where a highlight read
        // "The session involved a total duration of the recorded value and the recorded value."
        val markdown = """
            ## What stood out
            - Average HR was 140 bpm, peak 154 bpm.

            ## Exercise highlights
            - The session involved a total duration of the recorded value and the recorded value.

            ## Next session target
            - Keep average HR at or under 140 bpm for about 55 minutes
        """.trimIndent()

        val processed = postProcessInsightMarkdown(
            markdown = markdown,
            toolContext = WorkoutInsightsToolContext.WorkoutSession(
                title = "Workout session insights",
                workoutLabel = "Cyclette - LISS",
                markdown = """
                    FACT Session duration: 55:09 (55 minutes)
                    FACT Average heart rate: 140 bpm; peak 154 bpm
                    FACT Next-session target: average heart rate at or under 140 bpm for about 55 minutes
                """.trimIndent(),
            ),
        )

        assertFalse(processed.contains("the recorded value"))
        assertFalse(processed.contains("total duration of"))
        // The emptied section heading is removed with its bullet.
        assertFalse(processed.contains("Exercise highlights"))
        assertTrue(processed.contains("What stood out"))
        assertTrue(processed.contains("140 bpm"))
        assertTrue(processed.contains("Keep average HR at or under 140 bpm"))
    }

    @Test
    fun composeNextSessionTargetSection_replacesModelSectionWithAppBullet() {
        val markdown = """
            ## What stood out
            - Target not met: 140 bpm against the 131 bpm bar.

            ## Next session target
            - Ride easier next time, around the recorded value bpm.
        """.trimIndent()

        val composed = composeNextSessionTargetSection(
            markdown = markdown,
            bullet = "Keep average heart rate at or under 131 bpm for about 55 minutes.",
        )

        assertTrue(composed.contains("## Next session target"))
        assertTrue(composed.contains("- Keep average heart rate at or under 131 bpm for about 55 minutes."))
        assertFalse(composed.contains("Ride easier"))
        assertTrue(composed.contains("Target not met"))
    }

    @Test
    fun composeNextSessionTargetSection_appendsSectionWhenModelOmittedIt() {
        val composed = composeNextSessionTargetSection(
            markdown = "## What stood out\n- Solid session.",
            bullet = "Keep average heart rate at or under 131 bpm for about 55 minutes.",
        )

        assertTrue(composed.contains("## Next session target"))
        assertTrue(composed.contains("- Keep average heart rate at or under 131 bpm for about 55 minutes."))
    }

    @Test
    fun postProcessInsightMarkdown_doesNotInjectTargetSectionWhenNotApplied() {
        val markdown = "## What stood out\n- Solid session.\n\n## Next session target\n- Model wrote this."

        val processed = postProcessInsightMarkdown(
            markdown = markdown,
            toolContext = WorkoutInsightsToolContext.WorkoutSession(
                title = "Workout session insights",
                workoutLabel = "Cyclette - LISS",
                markdown = "",
                nextSessionTargetBullet = "Keep average heart rate at or under 131 bpm for about 55 minutes.",
            ),
            applySessionTargetSection = false,
        )

        assertTrue(processed.contains("Model wrote this."))
        assertFalse(processed.contains("Keep average heart rate at or under 131 bpm"))
    }

    @Test
    fun postProcessInsightMarkdownWithDropReport_dropsAndReportsMisquotedLinesWhenEnforced() {
        val markdown = """
            ## What stood out
            - The session averaged 154 bpm.
            - Target not met: 140 bpm against 131.

            ## Next session target
            - Keep average heart rate at or under 131 bpm for about 55 minutes.
        """.trimIndent()

        val outcome = postProcessInsightMarkdownWithDropReport(
            markdown = markdown,
            toolContext = WorkoutInsightsToolContext.WorkoutSession(
                title = "Workout session insights",
                workoutLabel = "Cyclette - LISS",
                markdown = factsContext,
            ),
            enforceNumericContract = true,
        )

        assertFalse(outcome.markdown.contains("averaged 154 bpm"))
        assertTrue(outcome.markdown.contains("Target not met"))
        assertEquals(1, outcome.misquotedDrops.size)
        assertEquals("What stood out", outcome.misquotedDrops.single().sectionHeading)
        assertTrue(outcome.misquotedDrops.single().reason.contains("average is 140 bpm"))
    }

    @Test
    fun postProcessInsightMarkdown_keepsMisquotedLinesWhenNotEnforced() {
        val markdown = "## What stood out\n- The session averaged 154 bpm."

        val outcome = postProcessInsightMarkdownWithDropReport(
            markdown = markdown,
            toolContext = WorkoutInsightsToolContext.WorkoutSession(
                title = "Workout session insights",
                workoutLabel = "Cyclette - LISS",
                markdown = factsContext,
            ),
        )

        assertTrue(outcome.markdown.contains("averaged 154 bpm"))
        assertTrue(outcome.misquotedDrops.isEmpty())
    }

    @Test
    fun spliceRewrittenBullets_insertsIntoExistingSection() {
        val markdown = """
            ## What stood out
            - Target not met: 140 bpm against 131.

            ## Next session target
            - Keep average heart rate at or under 131 bpm for about 55 minutes.
        """.trimIndent()
        val drop = MisquotedLineDrop("What stood out", "- The session averaged 154 bpm.", "reason")

        val spliced = spliceRewrittenBullets(markdown, listOf(drop to "Average HR was 140 bpm, peak 154 bpm"))

        assertTrue(
            spliced.contains(
                "## What stood out\n\n- Target not met: 140 bpm against 131.\n- Average HR was 140 bpm, peak 154 bpm"
            )
        )
        assertTrue(spliced.contains("## Next session target"))
    }

    @Test
    fun spliceRewrittenBullets_recreatesSectionHeadingWhenDropEmptiedIt() {
        val markdown = """
            ## What stood out
            - Solid session.

            ## Next session target
            - Keep average heart rate at or under 131 bpm for about 55 minutes.
        """.trimIndent()
        val drop = MisquotedLineDrop("Exercise highlights", "- The session averaged 154 bpm.", "reason")

        val spliced = spliceRewrittenBullets(markdown, listOf(drop to "Average HR was 140 bpm, peak 154 bpm"))

        assertTrue(spliced.contains("## Exercise highlights\n\n- Average HR was 140 bpm, peak 154 bpm"))
        assertTrue(spliced.contains("Solid session."))
    }

    @Test
    fun validateRewrittenLines_acceptsFactQuotingAndRejectsTheRest() {
        val facts = parseSessionNumericFacts(factsContext)!!

        val accepted = validateRewrittenLines(
            listOf(
                "Average HR was 140 bpm, peak 154 bpm.",
                "The session averaged 154 bpm.",
                "Average HR was 999 bpm.",
            ),
            facts = facts,
            evidence = factsContext,
        )

        assertEquals(listOf("Average HR was 140 bpm, peak 154 bpm."), accepted)
    }

}
