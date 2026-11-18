package com.gabstra.myworkoutassistant

import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutPlan
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate
import java.util.UUID

class WorkoutPlanSelectionTest {

    @Test
    fun explicitNoPlanSelectionSurvivesStoreMutation() {
        val push = plan("Push", order = 0)
        val pull = plan("Pull", order = 1)

        val result = resolveWorkoutPlanSelection(
            plans = listOf(push, pull),
            workouts = emptyList(),
            currentSelection = null,
            isResolved = true,
        )

        assertNull(result.planId)
        assertTrue(result.isResolved)
    }

    @Test
    fun explicitPlanSelectionSurvivesStoreMutation() {
        val push = plan("Push", order = 0)
        val pull = plan("Pull", order = 1)

        val result = resolveWorkoutPlanSelection(
            plans = listOf(push, pull),
            workouts = emptyList(),
            currentSelection = pull.id,
            isResolved = true,
        )

        assertEquals(pull.id, result.planId)
        assertTrue(result.isResolved)
    }

    @Test
    fun deletedSelectedPlanFallsBackToNoPlan() {
        val push = plan("Push", order = 0)

        val result = resolveWorkoutPlanSelection(
            plans = listOf(push),
            workouts = emptyList(),
            currentSelection = UUID.randomUUID(),
            isResolved = true,
        )

        assertNull(result.planId)
        assertTrue(result.isResolved)
    }

    @Test
    fun requestedMissingPlanBecomesExplicitNoPlanSelection() {
        val push = plan("Push", order = 0)
        val missingPlanId = UUID.randomUUID()

        assertNull(resolveRequestedWorkoutPlanSelection(listOf(push), missingPlanId))
        assertEquals(push.id, resolveRequestedWorkoutPlanSelection(listOf(push), push.id))
        assertNull(resolveRequestedWorkoutPlanSelection(listOf(push), null))
    }

    @Test
    fun unresolvedSelectionDefaultsToFirstPlanByOrder() {
        val later = plan("Later", order = 2)
        val first = plan("First", order = 1)

        val result = resolveWorkoutPlanSelection(
            plans = listOf(later, first),
            workouts = emptyList(),
            currentSelection = null,
            isResolved = false,
        )

        assertEquals(first.id, result.planId)
        assertTrue(result.isResolved)
    }

    @Test
    fun emptyStoreStaysUnresolvedUntilPlansExist() {
        val result = resolveWorkoutPlanSelection(
            plans = emptyList(),
            workouts = listOf(workout("Loose", workoutPlanId = null)),
            currentSelection = null,
            isResolved = false,
        )

        assertNull(result.planId)
        assertFalse(result.isResolved)
    }

    private fun plan(name: String, order: Int) = WorkoutPlan(
        id = UUID.randomUUID(),
        name = name,
        workoutIds = emptyList(),
        order = order,
    )

    private fun workout(name: String, workoutPlanId: UUID?) = Workout(
        id = UUID.randomUUID(),
        name = name,
        description = "",
        workoutComponents = emptyList(),
        order = 0,
        creationDate = LocalDate.of(2026, 1, 1),
        globalId = UUID.randomUUID(),
        type = 0,
        workoutPlanId = workoutPlanId,
    )
}
