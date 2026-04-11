package com.gabstra.myworkoutassistant.insights

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class WorkoutInsightMarkdownTest {
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
}
