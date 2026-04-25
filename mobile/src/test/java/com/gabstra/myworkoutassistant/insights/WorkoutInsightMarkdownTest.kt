package com.gabstra.myworkoutassistant.insights

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class WorkoutInsightMarkdownTest {
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
        assertTrue(processed.contains("the recorded value"))
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
        assertTrue(processed.contains("the recorded value"))
        assertTrue(processed.contains("the recorded set"))
    }
}
