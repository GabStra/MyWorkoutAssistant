package com.gabstra.myworkoutassistant.shared.workout.presentation

import com.gabstra.myworkoutassistant.shared.Workout
import org.junit.Assert.assertEquals
import org.junit.Test
import java.time.LocalDate
import java.util.UUID

class RecurringWorkoutPresentationOrderTest {
    @Test
    fun groupsAtFirstOccurrenceSortsOrdinalsAndPreservesLegacyOrder() {
        val sessionId = UUID.randomUUID()
        val legacyA = workout("legacy-a")
        val later = workout("later", sessionId, ordinal = 2)
        val legacyB = workout("legacy-b")
        val earlier = workout("earlier", sessionId, ordinal = 1)

        assertEquals(
            listOf("legacy-a", "earlier", "later", "legacy-b"),
            orderWorkoutsForPresentation(listOf(legacyA, later, legacyB, earlier)).map { it.name },
        )
    }

    private fun workout(name: String, sessionId: UUID? = null, ordinal: Int? = null) = Workout(
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
}
