package com.gabstra.myworkoutassistant.shared.workout.progression

import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import java.time.LocalDateTime
import java.time.LocalTime
import java.util.UUID
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class DurationProgressionReasonTest {

    private val config = DurationProgressionConfig(
        incrementMinutes = 5,
        maximumMinutes = 60,
        successfulSessionsRequired = 3,
    )

    private val sessionStart: LocalDateTime = LocalDateTime.of(2026, 11, 17, 10, 0)

    @Test
    fun ceilingReasonKeepsCanonicalTextAndStructuredId() {
        val result = resolveDurationDecisionReason(
            currentSeconds = 3_600,
            nextSeconds = 3_600,
            successes = 3,
            config = config,
            assessments = emptyList(),
        )

        assertEquals("hold: configured duration ceiling reached", result.text)
        assertEquals(DurationProgressionReasonId.CEILING_REACHED, result.detail.id)
    }

    @Test
    fun increaseReasonCarriesSessionArguments() {
        val result = resolveDurationDecisionReason(
            currentSeconds = 900,
            nextSeconds = 1_200,
            successes = 3,
            config = config,
            assessments = emptyList(),
        )

        assertEquals("increase: 3 consecutive sessions met the configured criteria", result.text)
        assertEquals(DurationProgressionReasonId.INCREASE_CRITERIA_MET, result.detail.id)
        assertEquals(3, result.detail.qualifyingSessions)
        assertEquals(3, result.detail.requiredSessions)
    }

    @Test
    fun holdAssessmentPropagatesNestedAssessmentIdentity() {
        val assessment = DurationSessionAssessment(
            sessionId = UUID.randomUUID(),
            prescribedSeconds = 900,
            coveragePercent = 95.0,
            zonePercent = 40.0,
            qualifies = false,
            reason = "work HR zone adherence below configured threshold",
            reasonId = DurationSessionAssessmentReasonId.HR_ZONE_BELOW_THRESHOLD,
        )

        val result = resolveDurationDecisionReason(
            currentSeconds = 900,
            nextSeconds = 900,
            successes = 0,
            config = config,
            assessments = listOf(assessment),
        )

        assertEquals("hold: work HR zone adherence below configured threshold", result.text)
        assertEquals(DurationProgressionReasonId.HOLD_ASSESSMENT, result.detail.id)
        assertEquals(
            DurationSessionAssessmentReasonId.HR_ZONE_BELOW_THRESHOLD,
            result.detail.assessmentReasonId,
        )
    }

    @Test
    fun noComparableSessionsHasNoArguments() {
        val result = resolveDurationDecisionReason(
            currentSeconds = 900,
            nextSeconds = 900,
            successes = 0,
            config = config,
            assessments = emptyList(),
        )

        assertEquals(
            "hold: no comparable sessions recorded under this policy and duration",
            result.text,
        )
        assertEquals(DurationProgressionReasonId.NO_COMPARABLE_SESSIONS, result.detail.id)
        assertNull(result.detail.assessmentReasonId)
    }

    @Test
    fun insufficientQualifyingSessionsCarriesCounts() {
        // calculateDurationProgression() records each qualifying assessment before
        // incrementing the success count, so a real two-success state always carries
        // two qualifying assessments.
        val result = resolveDurationDecisionReason(
            currentSeconds = 900,
            nextSeconds = 900,
            successes = 2,
            config = config,
            assessments = listOf(qualifyingAssessment(), qualifyingAssessment()),
        )

        assertEquals("hold: 2 of 3 required consecutive qualifying sessions", result.text)
        assertEquals(DurationProgressionReasonId.INSUFFICIENT_QUALIFYING_SESSIONS, result.detail.id)
        assertEquals(2, result.detail.qualifyingSessions)
        assertEquals(3, result.detail.requiredSessions)
    }

    @Test
    fun assessmentLoadMismatchCarriesStructuredReason() {
        val assessment = assessDurationSession(
            history = history(),
            rows = listOf(
                row(
                    data = TimedDurationSetData(
                        startTimer = 900_000,
                        endTimer = 0,
                        autoStart = false,
                        autoStop = false,
                        hasBeenExecuted = true,
                        actualWeight = 20.0,
                    ),
                ),
            ),
            zone = 100..140,
            config = config,
        )

        assertEquals(DurationSessionAssessmentReasonId.LOAD_DIFFERS_FROM_PRESCRIPTION, assessment.reasonId)
        assertEquals(
            "recorded load differs from the unweighted duration prescription",
            assessment.reason,
        )
    }

    @Test
    fun assessmentMissingTimestampsCarriesStructuredReason() {
        val assessment = assessDurationSession(
            history = history(),
            rows = listOf(
                row(
                    data = TimedDurationSetData(
                        startTimer = 900_000,
                        endTimer = 0,
                        autoStart = false,
                        autoStop = false,
                        hasBeenExecuted = true,
                    ),
                    startTime = null,
                    endTime = null,
                ),
            ),
            zone = 100..140,
            config = config,
        )

        assertEquals(DurationSessionAssessmentReasonId.TIMESTAMPS_UNAVAILABLE, assessment.reasonId)
        assertEquals("work timestamps unavailable", assessment.reason)
    }

    @Test
    fun assessmentWithoutHeartRateSamplesReportsInsufficientCoverage() {
        val assessment = assessDurationSession(
            history = history(heartBeatRecords = emptyList()),
            rows = listOf(
                row(
                    data = TimedDurationSetData(
                        startTimer = 900_000,
                        endTimer = 0,
                        autoStart = false,
                        autoStop = false,
                        hasBeenExecuted = true,
                    ),
                ),
            ),
            zone = 100..140,
            config = config,
        )

        assertEquals(DurationSessionAssessmentReasonId.INSUFFICIENT_HR_COVERAGE, assessment.reasonId)
        assertEquals("insufficient HR coverage; cannot assess", assessment.reason)
    }

    private fun history(
        heartBeatRecords: List<Int> = emptyList(),
    ): WorkoutHistory = WorkoutHistory(
        id = UUID.randomUUID(),
        workoutId = UUID.randomUUID(),
        date = sessionStart.toLocalDate(),
        time = LocalTime.NOON,
        startTime = sessionStart,
        duration = 1_000,
        heartBeatRecords = heartBeatRecords,
        isDone = true,
        hasBeenSentToHealth = false,
        globalId = UUID.randomUUID(),
    )

    private fun row(
        data: TimedDurationSetData,
        startTime: LocalDateTime? = sessionStart,
        endTime: LocalDateTime? = sessionStart.plusSeconds(900),
    ): SetHistory = SetHistory(
        id = UUID.randomUUID(),
        workoutHistoryId = UUID.randomUUID(),
        exerciseId = UUID.randomUUID(),
        setId = UUID.randomUUID(),
        order = 0u,
        startTime = startTime,
        endTime = endTime,
        setData = data,
        skipped = false,
    )

    private fun qualifyingAssessment(): DurationSessionAssessment = DurationSessionAssessment(
        sessionId = UUID.randomUUID(),
        prescribedSeconds = 900,
        coveragePercent = 96.0,
        zonePercent = 95.0,
        qualifies = true,
        reason = "completed work with qualifying HR coverage and zone adherence",
        reasonId = DurationSessionAssessmentReasonId.QUALIFYING_WORK,
    )
}
