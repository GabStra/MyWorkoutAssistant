package com.gabstra.myworkoutassistant.shared.export

import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.util.UUID

class ExerciseSessionCoachingMarkdownTest {

    @Test
    fun appendExecutedSummaryMarkdown_formats_completed_timed_duration_sets_with_real_duration() {
        val session = comparableSession(
            setData = TimedDurationSetData(
                startTimer = 45_000,
                endTimer = 0,
                autoStart = false,
                autoStop = true,
                hasBeenExecuted = true
            )
        )

        val markdown = StringBuilder()
        appendExecutedSummaryMarkdown(markdown, session, achievableWeights = null)

        val rendered = markdown.toString()
        assertTrue(rendered.contains("- Total duration: 00:45"))
        assertTrue(rendered.contains("- Set summary: Duration: 00:45"))
    }

    @Test
    fun appendHistoricalSessionBlockMarkdown_formats_legacy_second_based_time_sets_without_zero_duration() {
        val timedSession = comparableSession(
            setData = TimedDurationSetData(
                startTimer = 45,
                endTimer = 0,
                autoStart = false,
                autoStop = true,
                hasBeenExecuted = true
            )
        )
        val enduranceSession = comparableSession(
            setData = EnduranceSetData(
                startTimer = 180,
                endTimer = 180,
                autoStart = false,
                autoStop = false,
                hasBeenExecuted = true
            )
        )

        val timedMarkdown = StringBuilder()
        appendHistoricalSessionBlockMarkdown(
            markdown = timedMarkdown,
            heading = "Previous Session",
            session = timedSession,
            achievableWeights = null
        )

        val enduranceMarkdown = StringBuilder()
        appendHistoricalSessionBlockMarkdown(
            markdown = enduranceMarkdown,
            heading = "Previous Session",
            session = enduranceSession,
            achievableWeights = null
        )

        assertTrue(timedMarkdown.toString().contains("- Total duration: 00:45"))
        assertTrue(timedMarkdown.toString().contains("- S1: Duration: 00:45"))
        assertTrue(enduranceMarkdown.toString().contains("- Total duration: 03:00"))
        assertTrue(enduranceMarkdown.toString().contains("- S1: Duration: 03:00"))
    }

    private fun comparableSession(
        setData: com.gabstra.myworkoutassistant.shared.setdata.SetData,
    ): ComparableExerciseSession {
        val date = LocalDate.of(2026, 3, 30)
        val time = LocalTime.of(19, 51, 38)
        val startTime = LocalDateTime.of(date, time)
        return ComparableExerciseSession(
            workoutHistory = WorkoutHistory(
                id = UUID.randomUUID(),
                workoutId = UUID.randomUUID(),
                date = date,
                time = time,
                startTime = startTime,
                duration = 2_400,
                heartBeatRecords = emptyList(),
                isDone = true,
                hasBeenSentToHealth = false,
                globalId = UUID.randomUUID()
            ),
            workout = null,
            activeSetHistories = listOf(
                SetHistory(
                    id = UUID.randomUUID(),
                    workoutHistoryId = UUID.randomUUID(),
                    exerciseId = UUID.randomUUID(),
                    equipmentIdSnapshot = null,
                    equipmentNameSnapshot = null,
                    equipmentTypeSnapshot = null,
                    setId = UUID.randomUUID(),
                    order = 0u,
                    startTime = startTime,
                    endTime = startTime.plusSeconds(45),
                    setData = setData,
                    skipped = false
                )
            ),
            progression = null
        )
    }
}
