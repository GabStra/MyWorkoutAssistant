package com.gabstra.myworkoutassistant.shared.export

import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetData
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import org.junit.Assert.assertFalse
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

    @Test
    fun appendHistoricalSessionBlockMarkdown_excludes_warmup_and_calibration_sets_from_previous_session_metrics() {
        val date = LocalDate.of(2026, 3, 30)
        val time = LocalTime.of(19, 51, 38)
        val startTime = LocalDateTime.of(date, time)
        val workoutHistory = workoutHistory(date, time, startTime)
        val session = ComparableExerciseSession(
            workoutHistory = workoutHistory,
            workout = null,
            activeSetHistories = listOf(
                setHistory(
                    workoutHistory = workoutHistory,
                    startTime = startTime,
                    order = 0u,
                    setData = WeightSetData(
                        actualReps = 5,
                        actualWeight = 40.0,
                        volume = 200.0,
                        subCategory = SetSubCategory.WarmupSet
                    )
                ),
                setHistory(
                    workoutHistory = workoutHistory,
                    startTime = startTime.plusSeconds(60),
                    order = 1u,
                    setData = WeightSetData(
                        actualReps = 3,
                        actualWeight = 70.0,
                        volume = 210.0,
                        subCategory = SetSubCategory.CalibrationSet
                    )
                ),
                setHistory(
                    workoutHistory = workoutHistory,
                    startTime = startTime.plusSeconds(120),
                    order = 2u,
                    setData = WeightSetData(
                        actualReps = 8,
                        actualWeight = 80.0,
                        volume = 640.0,
                        subCategory = SetSubCategory.WorkSet
                    )
                )
            ).filterForInsightComparisonSets(),
            progression = null
        )

        val markdown = StringBuilder()
        appendHistoricalSessionBlockMarkdown(
            markdown = markdown,
            heading = "Previous Session",
            session = session,
            achievableWeights = null
        )

        val rendered = markdown.toString()
        assertTrue(rendered.contains("- Executed sets: 1"))
        assertTrue(rendered.contains("- Total volume: 640 kg"))
        assertTrue(rendered.contains("- S1: 80kg×8"))
        assertFalse(rendered.contains("40kg×5"))
        assertFalse(rendered.contains("70kg×3"))
    }

    @Test
    fun appendExecutedAndHistoricalMarkdown_include_autoRegulationRir_when_present() {
        val session = comparableSession(
            setData = WeightSetData(
                actualReps = 8,
                actualWeight = 80.0,
                volume = 640.0,
                autoRegulationRIR = 2.0
            )
        )

        val executedMarkdown = StringBuilder()
        appendExecutedSummaryMarkdown(executedMarkdown, session, achievableWeights = null)

        val historicalMarkdown = StringBuilder()
        appendHistoricalSessionBlockMarkdown(
            markdown = historicalMarkdown,
            heading = "Previous Session",
            session = session,
            achievableWeights = null
        )

        assertTrue(executedMarkdown.toString().contains("- Set summary: 80kg×8 (auto RIR 2)"))
        assertTrue(historicalMarkdown.toString().contains("- S1: 80kg×8 (auto RIR 2)"))
    }

    private fun comparableSession(
        setData: SetData,
    ): ComparableExerciseSession {
        val date = LocalDate.of(2026, 3, 30)
        val time = LocalTime.of(19, 51, 38)
        val startTime = LocalDateTime.of(date, time)
        val workoutHistory = workoutHistory(date, time, startTime)
        return ComparableExerciseSession(
            workoutHistory = workoutHistory,
            workout = null,
            activeSetHistories = listOf(
                setHistory(workoutHistory, startTime, 0u, setData)
            ),
            progression = null
        )
    }

    private fun workoutHistory(
        date: LocalDate,
        time: LocalTime,
        startTime: LocalDateTime,
    ): WorkoutHistory {
        return WorkoutHistory(
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
        )
    }

    private fun setHistory(
        workoutHistory: WorkoutHistory,
        startTime: LocalDateTime,
        order: UInt,
        setData: SetData,
    ): SetHistory {
        return SetHistory(
            id = UUID.randomUUID(),
            workoutHistoryId = workoutHistory.id,
            exerciseId = UUID.randomUUID(),
            equipmentIdSnapshot = null,
            equipmentNameSnapshot = null,
            equipmentTypeSnapshot = null,
            setId = UUID.randomUUID(),
            order = order,
            startTime = startTime,
            endTime = startTime.plusSeconds(45),
            setData = setData,
            skipped = false
        )
    }
}
