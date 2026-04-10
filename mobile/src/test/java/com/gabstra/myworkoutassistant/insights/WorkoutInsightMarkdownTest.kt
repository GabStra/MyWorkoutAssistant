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
}
