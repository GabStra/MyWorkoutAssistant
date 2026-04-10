package com.gabstra.myworkoutassistant.insights

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class LiteRtLmInsightsRepositoryTest {

    @Test
    fun stripRedundantHeartRateTextMetrics_removes_compact_session_hr_lines_only() {
        val prompt = """
            Analyze this completed workout session and provide practical coaching insights.

            Workout session:
            HR Mean: 105 bpm | Range: 69 to 132 bpm | Avg % max HR: 55% | Peak % max HR: 69% | High-intensity exposure: 0% of samples
            EXERCISE Back Squat
            RECOVERY Work HR: avg 104 bpm | peak 121 bpm | Rest HR: avg 97 bpm | peak 117 bpm
        """.trimIndent()

        val stripped = stripRedundantHeartRateTextMetrics(prompt)

        assertFalse(stripped.contains("HR Mean: 105 bpm"))
        assertTrue(stripped.contains("EXERCISE Back Squat"))
        assertTrue(stripped.contains("RECOVERY Work HR: avg 104 bpm | peak 121 bpm | Rest HR: avg 97 bpm | peak 117 bpm"))
    }

    @Test
    fun buildHeartRateChartAwarePrompt_appends_image_guidance_after_removing_redundant_hr_summary() {
        val prompt = """
            Workout session:
            HR Mean: 153 bpm | Range: 99 to 183 bpm
            EXERCISE Main Set
        """.trimIndent()

        val multimodalPrompt = buildHeartRateChartAwarePrompt(prompt)

        assertFalse(multimodalPrompt.contains("HR Mean: 153 bpm"))
        assertTrue(multimodalPrompt.contains("EXERCISE Main Set"))
        assertTrue(multimodalPrompt.contains("Attached image context:"))
        assertTrue(multimodalPrompt.contains("The attached image is the workout session heart-rate chart."))
    }

    @Test
    fun buildHeartRateChartImageOnlyPrompt_focuses_on_chart_only() {
        val prompt = buildHeartRateChartImageOnlyPrompt()

        assertTrue(prompt.contains("Analyze the attached workout session heart-rate chart only."))
        assertTrue(prompt.contains("Do not use any hidden assumptions about the workout."))
        assertTrue(prompt.contains("whether the pattern looks steady, intermittent, or drifted"))
        assertTrue(prompt.contains("Do not estimate bpm values, intensity zones, or exact recovery durations from the image."))
    }

    @Test
    fun buildHeartRateChartImageOnlyPrompt_includes_complete_timeline_heading_when_context_present() {
        val prompt = buildHeartRateChartImageOnlyPrompt(
            chartAnalysisContext = "- 00:00-00:45 Squat\n- 00:45-01:30 Rest after Squat",
        )

        assertTrue(prompt.contains("Complete session timeline (elapsed time from workout start; one row per contiguous block):"))
        assertTrue(prompt.contains("- 00:00-00:45 Squat"))
    }

    @Test
    fun buildHeartRateChartImageOnlyPrompt_prefers_timeline_tool_instructions_when_tool_context_present() {
        val prompt = buildHeartRateChartImageOnlyPrompt(
            chartAnalysisContext = "SHOULD NOT APPEAR",
            chartTimelineToolContext = WorkoutInsightsChartTimelineContext(
                durationSeconds = 3600,
                segments = listOf(
                    WorkoutInsightsChartTimelineSegment(0, 60, "Warmup"),
                ),
            ),
        )

        assertTrue(prompt.contains("Session duration: 3600 seconds elapsed from start to end."))
        assertTrue(prompt.contains("get_session_timeline_for_time_range"))
        assertTrue(prompt.contains("If the chart shows repeated peaks or distinct phases, prefer at least one targeted tool call"))
        assertFalse(prompt.contains("SHOULD NOT APPEAR"))
    }

    @Test
    fun buildHeartRateChartAnalysisSystemPrompt_encourages_targeted_timeline_investigation() {
        val prompt = buildHeartRateChartAnalysisSystemPrompt(hasSessionTimelineTool = true)

        assertTrue(prompt.contains("investigate with the available timeline tool instead of guessing"))
        assertTrue(prompt.contains("prefer at least one targeted timeline lookup before finalizing"))
        assertTrue(prompt.contains("Investigate visible peaks, clusters, phase changes, or ambiguous late-session behavior"))
    }

    @Test
    fun formatHeartRateChartAnalysisForPrompt_normalizes_broken_chart_markdown() {
        val formatted = formatHeartRateChartAnalysisForPrompt(
            """
                ## Chart Summary- The heart rate fluctuates between approximately121 and135 bpm.## Chart Signals- - Repeated rises and drops are visible.- - No sustained peak is visible.
            """.trimIndent()
        )

        assertTrue(formatted!!.contains("CHART SUMMARY The heart rate fluctuates between approximately 121 and 135 bpm."))
        assertTrue(formatted.contains("CHART SIGNAL Repeated rises and drops are visible."))
        assertTrue(formatted.contains("CHART SIGNAL No sustained peak is visible."))
    }

    @Test
    fun formatHeartRateChartAnalysisForPrompt_splits_concatenated_summary_and_signal_tokens() {
        val formatted = formatHeartRateChartAnalysisForPrompt(
            "SUMMARY: Heart rate fluctuated within a range from approximately100 to150.SUMMARY: The heart rate pattern appears intermittent with significant variation throughout the session.SIGNAL: Heart rate shows periods of sustained activity followed by drops.SIGNAL: Recoveries appear relatively short between peaks."
        )

        assertEquals(
            listOf(
                "CHART SUMMARY Heart rate fluctuated within a range from approximately 100 to 150.",
                "CHART SUMMARY The heart rate pattern appears intermittent with significant variation throughout the session.",
                "CHART SIGNAL Heart rate shows periods of sustained activity followed by drops.",
                "CHART SIGNAL Recoveries appear relatively short between peaks."
            ),
            formatted!!.lines()
        )
    }

    @Test
    fun buildPromptWithHeartRateChartAnalysis_merges_chart_analysis_with_explicit_workout_metrics() {
        val prompt = """
            Workout session:
            HR Mean: 153 bpm | Range: 99 to 183 bpm
            EXERCISE Main Set
            RECOVERY Work HR: avg 178 bpm | peak 183 bpm
        """.trimIndent()

        val merged = buildPromptWithHeartRateChartAnalysis(
            prompt = prompt,
            chartAnalysis = """
                ## Chart Summary
                - Four clear peaks with consistent recovery between them.
            """.trimIndent()
        )

        assertTrue(merged.contains("HR Mean: 153 bpm"))
        assertTrue(merged.contains("EXERCISE Main Set"))
        assertTrue(merged.contains("RECOVERY Work HR: avg 178 bpm | peak 183 bpm"))
        assertTrue(merged.contains("Heart-rate chart observations:"))
        assertTrue(merged.contains("CHART SUMMARY Four clear peaks with consistent recovery between them."))
        assertTrue(merged.contains("Treat chart observations as secondary context for the final insight."))
    }
}
