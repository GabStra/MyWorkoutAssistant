package com.gabstra.myworkoutassistant

import com.gabstra.myworkoutassistant.shared.AppBackup
import com.gabstra.myworkoutassistant.shared.FullBackup
import com.gabstra.myworkoutassistant.shared.UNASSIGNED_PLAN_NAME
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutPlan
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.convertUnassignedPlansToUngroupedWorkouts
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate
import java.util.UUID

class BackupRestoreWorkoutsTest {

    @Test
    fun fullRestoreSharedStorePreservesPlanOnlyMembershipAndWorkoutIdentity() {
        val member = workout(name = "Plan-only member", isActive = true, workoutPlanId = null)
        val plan = WorkoutPlan(
            id = UUID.randomUUID(),
            name = "Push",
            workoutIds = listOf(member.id),
            order = 0,
        )
        val fullBackup = FullBackup(
            sharedStore = WorkoutStore(
                workouts = listOf(member),
                workoutPlans = listOf(plan),
                birthDateYear = 1990,
                weightKg = 80.0,
                progressionPercentageAmount = 0.0,
            ),
        )

        val restored = fullBackup.sharedStoreForRestore()

        assertEquals(listOf(member.id), restored.workouts.map { it.id })
        assertEquals(member.name, restored.workouts.single().name)
        assertEquals(plan.id, restored.workouts.single().workoutPlanId)
        assertEquals(listOf(member.id), restored.workoutPlans.single().workoutIds)
    }

    @Test
    fun inactiveWorkoutWithoutHistorySurvivesRestoreAndUnassignedConversion() {
        val sentinel = WorkoutPlan(
            id = UUID.randomUUID(),
            name = UNASSIGNED_PLAN_NAME,
            workoutIds = emptyList(),
            order = 0,
        )
        val archived = workout(name = "Archived", isActive = false, workoutPlanId = sentinel.id)
        val backupStore = WorkoutStore(
            workouts = listOf(archived),
            workoutPlans = listOf(sentinel),
            birthDateYear = 1990,
            weightKg = 80.0,
            progressionPercentageAmount = 0.0,
        )
        val backup = AppBackup(
            WorkoutStore = backupStore,
            WorkoutHistories = emptyList(),
            SetHistories = emptyList(),
            ExerciseInfos = emptyList(),
            WorkoutSchedules = emptyList(),
            WorkoutRecords = emptyList(),
            ExerciseSessionProgressions = emptyList(),
        )

        val restored = backup.restoredWorkoutStore()
        assertEquals(listOf(archived), restored.workouts)

        val converted = restored.convertUnassignedPlansToUngroupedWorkouts()
        assertEquals(listOf(archived.id), converted.workouts.map { it.id })
        assertEquals(archived.name, converted.workouts.single().name)
        assertNull(converted.workouts.single().workoutPlanId)
        assertTrue(converted.workoutPlans.isEmpty())
    }

    private fun workout(
        name: String,
        isActive: Boolean,
        workoutPlanId: UUID?,
    ): Workout = Workout(
        id = UUID.randomUUID(),
        name = name,
        description = "",
        workoutComponents = emptyList(),
        order = 0,
        creationDate = LocalDate.of(2026, 1, 1),
        isActive = isActive,
        globalId = UUID.randomUUID(),
        type = 0,
        workoutPlanId = workoutPlanId,
    )
}
