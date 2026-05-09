package com.gabstra.myworkoutassistant.shared.export

import com.gabstra.myworkoutassistant.shared.HeartRateSource
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutPlan
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate
import java.util.UUID

class WorkoutPlanExportTest {

    @Test
    fun buildWorkoutPlanMarkdown_usesLatestWorkoutVersionForPlanEntries() {
        val globalId = UUID.randomUUID()
        val oldWorkoutId = UUID.randomUUID()
        val latestWorkoutId = UUID.randomUUID()
        val planId = UUID.randomUUID()
        val oldWorkout = workout(
            id = oldWorkoutId,
            name = "Old Push",
            globalId = globalId,
            nextVersionId = latestWorkoutId,
            isActive = false,
            workoutPlanId = planId
        )
        val latestWorkout = workout(
            id = latestWorkoutId,
            name = "Latest Push",
            globalId = globalId,
            previousVersionId = oldWorkoutId,
            isActive = true,
            workoutPlanId = planId
        )
        val workoutStore = WorkoutStore(
            workouts = listOf(oldWorkout, latestWorkout),
            workoutPlans = listOf(
                WorkoutPlan(
                    id = planId,
                    name = "Main Plan",
                    workoutIds = listOf(oldWorkoutId),
                    order = 0
                )
            ),
            birthDateYear = 1990,
            weightKg = 80.0,
            progressionPercentageAmount = 2.5
        )

        val markdown = buildWorkoutPlanMarkdown(workoutStore)

        assertTrue(markdown.contains("Latest Push"))
        assertFalse(markdown.contains("Old Push"))
    }

    private fun workout(
        id: UUID,
        name: String,
        globalId: UUID,
        previousVersionId: UUID? = null,
        nextVersionId: UUID? = null,
        isActive: Boolean,
        workoutPlanId: UUID?,
    ): Workout {
        return Workout(
            id = id,
            name = name,
            description = "",
            workoutComponents = emptyList(),
            order = 0,
            enabled = true,
            heartRateSource = HeartRateSource.WATCH_SENSOR,
            creationDate = LocalDate.of(2026, 1, 1),
            previousVersionId = previousVersionId,
            nextVersionId = nextVersionId,
            isActive = isActive,
            globalId = globalId,
            type = 0,
            workoutPlanId = workoutPlanId
        )
    }
}
