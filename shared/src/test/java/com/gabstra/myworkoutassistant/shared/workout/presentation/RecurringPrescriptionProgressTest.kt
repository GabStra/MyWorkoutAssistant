package com.gabstra.myworkoutassistant.shared.workout.presentation

import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.RecurringWorkoutAuthoring
import com.gabstra.myworkoutassistant.shared.workout.model.WorkoutSessionEndReason
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate
import java.time.LocalDateTime
import java.util.UUID

class RecurringPrescriptionProgressTest {

    @Test
    fun separatesUnrelatedFamiliesWithSameNames() {
        val firstSession = UUID.randomUUID()
        val secondSession = UUID.randomUUID()
        val firstFamily = listOf(
            prescription(firstSession, "Push", ordinal = 1),
            prescription(firstSession, "Push", ordinal = 2),
        )
        val secondFamily = listOf(
            prescription(secondSession, "Push", ordinal = 1),
            prescription(secondSession, "Push", ordinal = 2),
        )

        val progress = resolveRecurringPrescriptionProgress(
            workouts = listOf(firstFamily[1], secondFamily[0], firstFamily[0], secondFamily[1]),
            histories = emptyList(),
        )

        assertEquals(setOf(firstSession, secondSession), progress.keys)
        assertEquals(firstFamily[0].id, progress.getValue(firstSession).suggestedWorkoutId)
        assertEquals(secondFamily[0].id, progress.getValue(secondSession).suggestedWorkoutId)
        assertEquals(firstFamily[0].id, progress.getValue(firstSession).firstWorkoutId)
        assertEquals(secondFamily[0].id, progress.getValue(secondSession).firstWorkoutId)
        assertNull(progress.getValue(firstSession).lastCompletedWorkoutId)
        assertNull(progress.getValue(secondSession).lastCompletedWorkoutId)
        assertFalse(progress.getValue(firstSession).reachedEnd)
        assertFalse(progress.getValue(secondSession).reachedEnd)
    }

    @Test
    fun noHistorySuggestsFirstWorkout() {
        val sessionId = UUID.randomUUID()
        val first = workout(sessionId, "First", ordinal = 1)
        val second = workout(sessionId, "Second", ordinal = 2)

        val progress = resolveRecurringPrescriptionProgress(listOf(second, first), emptyList())
            .getValue(sessionId)

        assertNull(progress.lastCompletedWorkoutId)
        assertEquals(first.id, progress.suggestedWorkoutId)
        assertFalse(progress.reachedEnd)
        assertEquals(first.id, progress.firstWorkoutId)
    }

    @Test
    fun latestCompletionSuggestsNextWorkout() {
        val sessionId = UUID.randomUUID()
        val first = workout(sessionId, "First", ordinal = 1)
        val second = workout(sessionId, "Second", ordinal = 2)
        val third = workout(sessionId, "Third", ordinal = 3)

        val progress = resolveRecurringPrescriptionProgress(
            workouts = listOf(third, first, second),
            histories = listOf(completedHistory(first)),
        ).getValue(sessionId)

        assertEquals(first.id, progress.lastCompletedWorkoutId)
        assertEquals(second.id, progress.suggestedWorkoutId)
        assertFalse(progress.reachedEnd)
        assertEquals(first.id, progress.firstWorkoutId)
    }

    @Test
    fun reorderedListSelectsFirstUnfinishedWhileHistoryStaysWithCompletedPrescription() {
        val sessionId = UUID.randomUUID()
        val first = workout(sessionId, "First", ordinal = 1)
        val second = workout(sessionId, "Second", ordinal = 2)
        val third = workout(sessionId, "Third", ordinal = 3)
        val workouts = listOf(first, second, third)
        val firstHistory = completedHistory(first)

        val beforeReorder = resolveRecurringPrescriptionProgress(workouts, listOf(firstHistory))
            .getValue(sessionId)
        assertEquals(first.id, beforeReorder.lastCompletedWorkoutId)
        assertEquals(second.id, beforeReorder.suggestedWorkoutId)

        val reordered = RecurringWorkoutAuthoring.reorderFamily(
            workouts,
            orderedWorkoutIds = listOf(third.id, first.id, second.id),
        )
        val afterReorder = resolveRecurringPrescriptionProgress(reordered, listOf(firstHistory))
            .getValue(sessionId)

        assertEquals(first.id, afterReorder.lastCompletedWorkoutId)
        assertEquals(third.id, afterReorder.suggestedWorkoutId)
        assertEquals(first.globalId, firstHistory.globalId)
        assertEquals(listOf(1, 2, 3), reordered.sortedBy { it.prescriptionOrdinal }.map { it.prescriptionOrdinal })
    }

    @Test
    fun cancelledAndUnfinishedHistoriesAreIgnored() {
        val sessionId = UUID.randomUUID()
        val first = workout(sessionId, "First", ordinal = 1)
        val second = workout(sessionId, "Second", ordinal = 2)
        val third = workout(sessionId, "Third", ordinal = 3)

        val progress = resolveRecurringPrescriptionProgress(
            workouts = listOf(first, second, third),
            histories = listOf(
                completedHistory(first, startTime = LocalDateTime.of(2026, 1, 1, 8, 0)),
                completedHistory(
                    second,
                    startTime = LocalDateTime.of(2026, 1, 2, 8, 0),
                    isDone = false,
                ),
                completedHistory(
                    second,
                    startTime = LocalDateTime.of(2026, 1, 3, 8, 0),
                    endReason = WorkoutSessionEndReason.FINISHED_EARLY,
                ),
            ),
        ).getValue(sessionId)

        assertEquals(first.id, progress.lastCompletedWorkoutId)
        assertEquals(second.id, progress.suggestedWorkoutId)
        assertFalse(progress.reachedEnd)
    }

    @Test
    fun editedWorkoutIdWithSameGlobalIdIsRecognized() {
        val sessionId = UUID.randomUUID()
        val first = workout(sessionId, "First", ordinal = 1)
        val editedSecond = workout(sessionId, "Second", ordinal = 2)
        val third = workout(sessionId, "Third", ordinal = 3)
        val oldSecondVersionId = UUID.randomUUID()

        val progress = resolveRecurringPrescriptionProgress(
            workouts = listOf(first, editedSecond, third),
            histories = listOf(
                completedHistory(first, startTime = LocalDateTime.of(2026, 1, 1, 8, 0)),
                completedHistory(editedSecond, workoutId = oldSecondVersionId,
                    startTime = LocalDateTime.of(2026, 1, 2, 8, 0)),
            ),
        ).getValue(sessionId)

        assertEquals(editedSecond.id, progress.lastCompletedWorkoutId)
        assertEquals(third.id, progress.suggestedWorkoutId)
        assertFalse(progress.reachedEnd)
    }

    @Test
    fun outOfOrderCompletionSuggestsFirstUnfinishedAndAllCompletedRemainsComplete() {
        val sessionId = UUID.randomUUID()
        val first = workout(sessionId, "First", ordinal = 1)
        val second = workout(sessionId, "Second", ordinal = 2)
        val third = workout(sessionId, "Third", ordinal = 3)
        val workouts = listOf(first, second, third)

        val atEnd = resolveRecurringPrescriptionProgress(
            workouts = workouts,
            histories = listOf(completedHistory(first), completedHistory(second), completedHistory(third)),
        ).getValue(sessionId)
        assertEquals(third.id, atEnd.lastCompletedWorkoutId)
        assertNull(atEnd.suggestedWorkoutId)
        assertTrue(atEnd.reachedEnd)
        assertEquals(first.id, atEnd.firstWorkoutId)

        val partial = resolveRecurringPrescriptionProgress(
            workouts = workouts,
            histories = listOf(
                completedHistory(third, startTime = LocalDateTime.of(2026, 1, 1, 8, 0)),
                completedHistory(first, startTime = LocalDateTime.of(2026, 1, 2, 8, 0)),
            ),
        ).getValue(sessionId)
        assertEquals(first.id, partial.lastCompletedWorkoutId)
        assertEquals(second.id, partial.suggestedWorkoutId)
        assertFalse(partial.reachedEnd)
    }

    @Test
    fun legacyNullSessionMatchesButForeignSessionIsIgnored() {
        val sessionId = UUID.randomUUID()
        val detachedSessionId = UUID.randomUUID()
        val first = workout(sessionId, "First", ordinal = 1)
        val second = workout(sessionId, "Second", ordinal = 2)

        val progress = resolveRecurringPrescriptionProgress(
            workouts = listOf(first, second),
            histories = listOf(
                completedHistory(
                    second,
                    recurringSessionId = detachedSessionId,
                    startTime = LocalDateTime.of(2026, 1, 3, 8, 0),
                ),
                completedHistory(
                    first,
                    recurringSessionId = null,
                    startTime = LocalDateTime.of(2026, 1, 1, 8, 0),
                ),
            ),
        ).getValue(sessionId)

        assertEquals(first.id, progress.lastCompletedWorkoutId)
        assertEquals(second.id, progress.suggestedWorkoutId)
        assertFalse(progress.reachedEnd)
    }

    @Test
    fun nonRecurringWorkoutsAreUnchanged() {
        val nonRecurring = workout(sessionId = null, name = "Standalone", ordinal = null)

        val progress = resolveRecurringPrescriptionProgress(
            workouts = listOf(nonRecurring),
            histories = listOf(completedHistory(nonRecurring)),
        )

        assertTrue(progress.isEmpty())
    }

    private fun prescription(sessionId: UUID, name: String, ordinal: Int): Workout =
        workout(sessionId, name, ordinal)

    private fun workout(sessionId: UUID?, name: String, ordinal: Int?) = Workout(
        id = UUID.randomUUID(),
        name = name,
        description = "",
        workoutComponents = emptyList(),
        order = 0,
        creationDate = LocalDate.of(2026, 1, 1),
        globalId = UUID.randomUUID(),
        type = 0,
        recurringSessionId = sessionId,
        prescriptionOrdinal = ordinal,
    )

    private fun completedHistory(
        workout: Workout,
        workoutId: UUID = workout.id,
        recurringSessionId: UUID? = workout.recurringSessionId,
        startTime: LocalDateTime = LocalDateTime.of(2026, 1, 1, 8, 0),
        isDone: Boolean = true,
        endReason: WorkoutSessionEndReason = WorkoutSessionEndReason.COMPLETED,
    ) = WorkoutHistory(
        id = UUID.randomUUID(),
        workoutId = workoutId,
        date = startTime.toLocalDate(),
        time = startTime.toLocalTime(),
        startTime = startTime,
        duration = 30,
        heartBeatRecords = emptyList(),
        isDone = isDone,
        hasBeenSentToHealth = false,
        globalId = workout.globalId,
        endReason = endReason,
        recurringSessionId = recurringSessionId,
    )
}
