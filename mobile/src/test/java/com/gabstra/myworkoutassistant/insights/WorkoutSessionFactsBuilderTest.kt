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
    fun `builds duration average peak drift zone and next-session target`() {
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
        assertTrue(text.contains("FACT Next-session target: average heart rate at or under 125 bpm for about 50 minutes"))
        assertFalse(text.contains("target check"))
        assertFalse(text.contains("versus recent sessions"))
    }

    @Test
    fun `builds trend drift-comparison and target-check facts against recent sessions`() {
        val sameWorkoutId = UUID.randomUUID()
        val facts = WorkoutSessionFactsBuilder.build(
            workoutHistory = history(List(20) { sample -> if (sample < 10) 125 else 135 }, durationSeconds = 3150, workoutId = sameWorkoutId),
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
        assertTrue(text.contains("FACT Trend over the last 2 sessions of this workout: improving — average HR is 10 bpm below the recent 140 bpm average; at a similar duration, a lower average HR means better aerobic efficiency"))
        assertTrue(text.contains("FACT HR drift this session: +10 bpm versus your typical +0 bpm on this workout"))
        assertTrue(text.contains("FACT Previous-session target check: the target was average HR at or under 140 bpm for about 50 minutes; this session averaged 130 bpm across 53 minutes — target met"))
        assertTrue(text.contains("FACT Next-session target: average heart rate at or under 130 bpm for about 50 minutes"))
    }

    @Test
    fun `reports regressing trend and unmet target when HR is higher`() {
        val sameWorkoutId = UUID.randomUUID()
        val facts = WorkoutSessionFactsBuilder.build(
            workoutHistory = history(List(10) { 150 }, durationSeconds = 2400, workoutId = sameWorkoutId),
            previousSessionsNewestFirst = listOf(
                history(List(10) { 130 }, durationSeconds = 3150, workoutId = sameWorkoutId),
            ),
            targetBoundsPercentMaxHr = null,
            userAge = 30,
            measuredMaxHeartRate = null,
            restingHeartRate = null,
        )

        val text = facts.lines.joinToString("\n")
        assertTrue(text.contains("regressing — average HR is 20 bpm above the recent 130 bpm average"))
        assertTrue(text.contains("this session averaged 150 bpm across 40 minutes — target not met"))
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

        assertEquals(
            "FACT Session duration: 30:00 (30 minutes)",
            facts.lines.single(),
        )
    }

    @Test
    fun `prompt block is empty without facts and prefixed when present`() {
        assertEquals("", WorkoutSessionFacts(emptyList()).asPromptBlock())
        val block = WorkoutSessionFacts(listOf("FACT Session duration: 30:00 (30 minutes)")).asPromptBlock()
        assertTrue(block.startsWith("\n\nPrecomputed session facts"))
        assertTrue(block.contains("FACT Session duration: 30:00 (30 minutes)"))
    }
}
