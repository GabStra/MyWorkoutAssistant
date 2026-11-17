package com.gabstra.myworkoutassistant.sync

import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryOrigin
import com.gabstra.myworkoutassistant.shared.workout.model.WorkoutSessionEndReason
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.util.UUID

class MobileSyncToWatchRecurringHistoryPruningTest {

    private val sessionId = UUID.randomUUID()
    private val firstGlobalId = UUID.randomUUID()
    private val secondGlobalId = UUID.randomUUID()

    @Test
    fun `completed imported recurring parent survives without measured set rows`() {
        val first = workout(globalId = firstGlobalId, recurringSessionId = sessionId)
        val second = workout(globalId = secondGlobalId, recurringSessionId = sessionId)
        val importedParent = history(workoutId = first.id, globalId = firstGlobalId)

        val required = requiredRecurringPrescriptionHistoryIds(
            allowedWorkouts = listOf(first, second),
            histories = listOf(importedParent),
        )

        assertEquals(setOf(importedParent.id), required)
        assertEquals(WorkoutHistoryOrigin.USER_IMPORTED, importedParent.origin)
        assertEquals(false, importedParent.startTimeKnown)
        assertEquals(false, importedParent.durationKnown)
    }

    @Test
    fun `only latest normally completed history of an active recurring family is required`() {
        val first = workout(globalId = firstGlobalId, recurringSessionId = sessionId)
        val earlier = history(
            workoutId = first.id,
            globalId = firstGlobalId,
            date = LocalDate.of(2026, 11, 9),
        )
        val latest = history(
            workoutId = first.id,
            globalId = firstGlobalId,
            date = LocalDate.of(2026, 11, 13),
        )

        val required = requiredRecurringPrescriptionHistoryIds(
            allowedWorkouts = listOf(first),
            histories = listOf(earlier, latest),
        )

        assertEquals(setOf(latest.id), required)
    }

    @Test
    fun `inactive recurring and unrelated completions are not required`() {
        val inactive = workout(
            globalId = firstGlobalId,
            recurringSessionId = sessionId,
            isActive = false,
        )
        val plain = workout(globalId = secondGlobalId, recurringSessionId = null)
        val inactiveHistory = history(workoutId = inactive.id, globalId = firstGlobalId)
        val plainHistory = history(workoutId = plain.id, globalId = secondGlobalId)

        val required = requiredRecurringPrescriptionHistoryIds(
            allowedWorkouts = listOf(inactive, plain),
            histories = listOf(inactiveHistory, plainHistory),
        )

        assertTrue(required.isEmpty())
    }

    private fun workout(
        globalId: UUID,
        recurringSessionId: UUID?,
        isActive: Boolean = true,
    ): Workout = Workout(
        id = UUID.randomUUID(),
        name = "Prescription",
        description = "",
        workoutComponents = emptyList(),
        order = 0,
        creationDate = LocalDate.of(2026, 11, 1),
        isActive = isActive,
        globalId = globalId,
        type = 0,
        recurringSessionId = recurringSessionId,
    )

    private fun history(
        workoutId: UUID,
        globalId: UUID,
        date: LocalDate = LocalDate.of(2026, 11, 13),
    ): WorkoutHistory = WorkoutHistory(
        id = UUID.randomUUID(),
        workoutId = workoutId,
        date = date,
        time = LocalTime.MIDNIGHT,
        startTime = LocalDateTime.of(date, LocalTime.MIDNIGHT),
        duration = 0,
        heartBeatRecords = emptyList(),
        isDone = true,
        hasBeenSentToHealth = false,
        globalId = globalId,
        endReason = WorkoutSessionEndReason.COMPLETED,
        recurringSessionId = sessionId,
        origin = WorkoutHistoryOrigin.USER_IMPORTED,
        startTimeKnown = false,
        durationKnown = false,
    )
}
