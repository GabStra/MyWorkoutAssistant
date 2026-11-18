package com.gabstra.myworkoutassistant

import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutPlan
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.convertUnassignedPlansToUngroupedWorkouts
import com.gabstra.myworkoutassistant.shared.synchronizeWorkoutPlanMemberships
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate
import java.util.UUID

class WorkoutPlanMembershipTest {

    @Test
    fun movingToNoPlanPersistsNullMembershipWithoutRemovingEmptyPlans() {
        val plan = plan("Push")
        val emptyPlan = plan("Draft")
        val moving = workout("Moving", plan.id)
        val staying = workout("Staying", plan.id)
        val unknownPlanId = UUID.randomUUID()
        val orphaned = workout("Orphaned", unknownPlanId)
        val store = store(listOf(moving, staying, orphaned), listOf(plan, emptyPlan))

        val moved = store.withWorkoutsMovedToPlan(setOf(moving.id), null)

        assertNull(moved.workout(moving.id).workoutPlanId)
        assertEquals(plan.id, moved.workout(staying.id).workoutPlanId)
        assertEquals(unknownPlanId, moved.workout(orphaned.id).workoutPlanId)
        assertEquals(listOf(staying.id), moved.plan(plan.id).workoutIds)
        assertTrue(moved.plan(emptyPlan.id).workoutIds.isEmpty())
    }

    @Test
    fun explicitDetachIsNotReattachedByConservativeMembershipRepair() {
        val plan = plan("Push")
        val moving = workout("Moving", plan.id)
        val store = store(listOf(moving), listOf(plan))
            .copy(workoutPlans = listOf(plan.copy(workoutIds = listOf(moving.id))))

        val detached = store.withWorkoutsMovedToPlan(setOf(moving.id), null)
        val repaired = detached.convertUnassignedPlansToUngroupedWorkouts(
            repairPlanOnlyMembership = true,
        )

        assertNull(repaired.workout(moving.id).workoutPlanId)
        assertTrue(repaired.plan(plan.id).workoutIds.isEmpty())
    }

    @Test
    fun deletingPlanDetachesItsWorkoutsAndKeepsEveryOtherPlanAndAssociation() {
        val deletedPlan = plan("Delete me")
        val otherPlan = plan("Push")
        val detaching = workout("Detaching", deletedPlan.id)
        val untouched = workout("Untouched", otherPlan.id)
        val noPlanWorkout = workout("No plan", null)
        val store = store(
            listOf(detaching, untouched, noPlanWorkout),
            listOf(deletedPlan, otherPlan),
        )

        val deleted = store.withWorkoutPlanDeleted(deletedPlan.id)

        assertTrue(deleted.workoutPlans.none { it.id == deletedPlan.id })
        assertEquals(listOf(otherPlan.id), deleted.workoutPlans.map { it.id })
        assertNull(deleted.workout(detaching.id).workoutPlanId)
        assertEquals(otherPlan.id, deleted.workout(untouched.id).workoutPlanId)
        assertEquals(listOf(untouched.id), deleted.plan(otherPlan.id).workoutIds)
        assertNull(deleted.workout(noPlanWorkout.id).workoutPlanId)
    }

    @Test
    fun updatingPlanSettingsKeepsLatestMembershipOrderAndOtherPlans() {
        val editedPlan = plan("Push", order = 2)
        val otherPlan = plan("Pull", order = 5)
        val first = workout("First", editedPlan.id)
        val second = workout("Second", editedPlan.id)
        val store = store(listOf(first, second), listOf(editedPlan, otherPlan))
            .synchronizeWorkoutPlanMemberships()

        val updated = requireNotNull(
            store.withWorkoutPlanSettings(
                planId = editedPlan.id,
                name = "Upper",
                suggestNextPrescription = false,
            ),
        )

        val updatedPlan = updated.plan(editedPlan.id)
        assertEquals("Upper", updatedPlan.name)
        assertTrue(!updatedPlan.suggestNextPrescription)
        assertEquals(listOf(first.id, second.id), updatedPlan.workoutIds)
        assertEquals(editedPlan.order, updatedPlan.order)
        assertEquals(otherPlan, updated.plan(otherPlan.id))
        assertEquals(store.workouts, updated.workouts)
    }

    @Test
    fun updatingSettingsOfMissingPlanReportsFailure() {
        val store = store(emptyList(), listOf(plan("Push")))

        assertNull(
            store.withWorkoutPlanSettings(
                planId = UUID.randomUUID(),
                name = "Upper",
                suggestNextPrescription = false,
            ),
        )
    }

    private fun WorkoutStore.workout(id: UUID): Workout = workouts.single { it.id == id }

    private fun WorkoutStore.plan(id: UUID): WorkoutPlan = workoutPlans.single { it.id == id }

    private fun plan(name: String, order: Int = 0) = WorkoutPlan(
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

    private fun store(workouts: List<Workout>, plans: List<WorkoutPlan>) = WorkoutStore(
        workouts = workouts,
        workoutPlans = plans,
        birthDateYear = 1990,
        weightKg = 80.0,
        progressionPercentageAmount = 0.0,
    )
}
