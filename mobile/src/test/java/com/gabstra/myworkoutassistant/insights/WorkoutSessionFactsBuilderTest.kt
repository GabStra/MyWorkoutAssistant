package com.gabstra.myworkoutassistant.insights

import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate
import java.time.LocalTime
import java.util.UUID

class WorkoutSessionFactsBuilderTest {

    private fun history(
        heartBeats: List<Int>,
        durationSeconds: Int,
        workoutId: UUID = UUID.randomUUID(),
    ) = WorkoutHistory(
        id = UUID.randomUUID(),
        workoutId = workoutId,
        date = LocalDate.of(2026, 10, 9),
        time = LocalTime.of(10, 0),
        startTime = LocalDate.of(2026, 10, 9).atTime(10, 0),
        duration = durationSeconds,
        heartBeatRecords = heartBeats,
        isDone = true,
        hasBeenSentToHealth = false,
        globalId = UUID.randomUUID(),
    )

    @Test
    fun `builds duration average peak drift and zone facts`() {
        val heartRates = List(20) { sample -> if (sample < 10) 120 else 130 }
        val facts = WorkoutSessionFactsBuilder.build(
            workoutHistory = history(heartRates, durationSeconds = 3150),
            previousSessionsNewestFirst = emptyList(),
            targetBoundsPercentMaxHr = 60f to 70f,
            userAge = 30,
            measuredMaxHeartRate = null,
            restingHeartRate = null,
        )

        val text = facts.lines.joinToString("\n")
        assertTrue(text.contains("FACT Session duration: 52:30 (53 minutes)"))
        assertTrue(text.contains("FACT Average heart rate: 125 bpm; peak 130 bpm"))
        assertTrue(text.contains("FACT Heart-rate drift: the second half averaged +10 bpm versus the first half"))
        assertTrue(Regex("""FACT \d+% of HR samples stayed inside the 60-70% target zone""").containsMatchIn(text))
        assertFalse(text.contains("versus recent sessions"))
    }

    @Test
    fun `builds trend facts against recent sessions of the same workout`() {
        val sameWorkoutId = UUID.randomUUID()
        val facts = WorkoutSessionFactsBuilder.build(
            workoutHistory = history(List(10) { 130 }, durationSeconds = 3150, workoutId = sameWorkoutId),
            previousSessionsNewestFirst = listOf(
                history(List(10) { 140 }, durationSeconds = 3000, workoutId = sameWorkoutId),
                history(List(10) { 140 }, durationSeconds = 3060, workoutId = sameWorkoutId),
            ),
            targetBoundsPercentMaxHr = null,
            userAge = 30,
            measuredMaxHeartRate = null,
            restingHeartRate = null,
        )

        val text = facts.lines.joinToString("\n")
        assertTrue(text.contains("FACT Session duration versus recent sessions of this workout: 53 minutes versus 51 minutes typical"))
        assertTrue(text.contains("FACT Average heart rate versus recent sessions of this workout: -10 bpm versus 140 bpm (at a similar duration, a lower average HR means better aerobic efficiency)"))
    }

    @Test
    fun `skips heart rate facts when no heart rate was recorded`() {
        val facts = WorkoutSessionFactsBuilder.build(
            workoutHistory = history(emptyList(), durationSeconds = 1800),
            previousSessionsNewestFirst = emptyList(),
            targetBoundsPercentMaxHr = 60f to 70f,
            userAge = 30,
            measuredMaxHeartRate = null,
            restingHeartRate = null,
        )

        val text = facts.lines.joinToString("\n")
        assertEquals(
            "FACT Session duration: 30:00 (30 minutes)",
            facts.lines.single(),
        )
        assertFalse(text.contains("bpm"))
        assertFalse(text.contains("target zone"))
    }

    @Test
    fun `prompt block is empty without facts and prefixed when present`() {
        assertEquals("", WorkoutSessionFacts(emptyList()).asPromptBlock())
        val block = WorkoutSessionFacts(listOf("FACT Session duration: 30:00 (30 minutes)")).asPromptBlock()
        assertTrue(block.startsWith("\n\nPrecomputed session facts"))
        assertTrue(block.contains("FACT Session duration: 30:00 (30 minutes)"))
    }
}
