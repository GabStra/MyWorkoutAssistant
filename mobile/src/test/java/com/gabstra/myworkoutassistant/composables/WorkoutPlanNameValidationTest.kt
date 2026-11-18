package com.gabstra.myworkoutassistant.composables

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class WorkoutPlanNameValidationTest {

    @Test
    fun exactReservedNameIsRejected() {
        assertTrue(isReservedPlanNameInput("Unassigned"))
    }

    @Test
    fun surroundingWhitespaceStillRejectsReservedName() {
        assertTrue(isReservedPlanNameInput("  Unassigned  "))
    }

    @Test
    fun namesThatOnlyResembleReservedNameAreAllowed() {
        listOf("unassigned", "Unassigned 2", "My Unassigned").forEach { name ->
            assertFalse(name, isReservedPlanNameInput(name))
        }
    }
}
