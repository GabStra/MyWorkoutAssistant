package com.gabstra.myworkoutassistant.screens

import com.gabstra.myworkoutassistant.shared.Workout
import org.junit.Assert.assertEquals
import org.junit.Test
import java.time.LocalDate
import java.util.UUID

class WorkoutsListTabSelectionTest {
    @Test
    fun prescriptionDisplayPreservesExplicitLabelsAndUsesOrdinalFallbackWithoutWeekInference() {
        val prescriptionWord = "Prescription"
        assertEquals("Week1", recurringPrescriptionDisplayLabel(workout("Session", ordinal = 1, label = "Week1"), prescriptionWord))
        assertEquals("Foundation", recurringPrescriptionDisplayLabel(workout("Session", ordinal = 2, label = "Foundation"), prescriptionWord))
        assertEquals("Prescription 2", recurringPrescriptionDisplayLabel(workout("Session", ordinal = 2, label = " "), prescriptionWord))
        assertEquals("Prescription", recurringPrescriptionDisplayLabel(workout("Session"), prescriptionWord))
    }

    @Test
    fun selectingSessionCardsExpandsOnlyTheirActiveFamiliesAndStandaloneRows() {
        val sessionA = UUID.randomUUID()
        val sessionB = UUID.randomUUID()
        val a1 = workout("Shared session name", sessionA, ordinal = 1)
        val a2Disabled = workout("Shared session name", sessionA, ordinal = 2, enabled = false)
        val aOld = workout("Shared session name", sessionA, ordinal = 0, isActive = false)
        val b1 = workout("Shared session name", sessionB, ordinal = 1)
        val b2 = workout("Shared session name", sessionB, ordinal = 2)
        val standalone = workout("Standalone")
        val current = listOf(a1, a2Disabled, aOld, b1, b2, standalone)

        val selected = expandWorkoutCardSelection(listOf(a1, b1, standalone), current)

        assertEquals(
            setOf(a1.id, a2Disabled.id, b1.id, b2.id, standalone.id),
            selected.map { it.id }.toSet(),
        )
    }

    private fun workout(
        name: String,
        sessionId: UUID? = null,
        ordinal: Int? = null,
        label: String? = null,
        enabled: Boolean = true,
        isActive: Boolean = true,
    ) = Workout(
        id = UUID.randomUUID(),
        name = name,
        description = "",
        workoutComponents = emptyList(),
        order = ordinal ?: 1,
        enabled = enabled,
        creationDate = LocalDate.of(2026, 1, 1),
        globalId = UUID.randomUUID(),
        type = 0,
        recurringSessionId = sessionId,
        prescriptionOrdinal = ordinal,
        prescriptionLabel = label,
        isActive = isActive,
    )
}
